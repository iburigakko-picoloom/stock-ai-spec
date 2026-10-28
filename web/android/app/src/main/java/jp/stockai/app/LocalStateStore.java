package jp.stockai.app;

import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import com.getcapacitor.JSObject;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

/** Existing encrypted format, shared by the application compute owner and backups. */
final class LocalStateStore {
    static final String DATABASE = "stockai-device.sqlite3";
    static final String KEY_ALIAS = "stockai-local-v1";
    static final int CHUNK_CHARACTERS = 256 * 1024;
    // Stream quota, independent of heap and the legacy whole-String API.
    static final int MAX_CHARACTERS = 256 * 1024 * 1024;
    static final int MAX_INLINE_CHARACTERS = 128 * 1024 * 1024;
    static final long MAX_GENERATION = 9007199254740991L;
    static final String FORMAT = "stockai-state-chunks-v1:";
    final SQLiteDatabase database;

    static String hex(byte[] value) {
        StringBuilder result = new StringBuilder();
        for (byte part : value) result.append(String.format("%02x", part & 255));
        return result.toString();
    }

    LocalStateStore(SQLiteDatabase database) {
        this.database = database;
        database.execSQL("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL, payload BLOB NOT NULL)");
        database.execSQL("CREATE TABLE IF NOT EXISTS state_chunks (piece INTEGER PRIMARY KEY, payload BLOB NOT NULL)");
        database.execSQL("CREATE TABLE IF NOT EXISTS operations_state (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)");
        database.execSQL("CREATE TABLE IF NOT EXISTS operations_chunks (piece INTEGER PRIMARY KEY, payload BLOB NOT NULL)");
    }

    static synchronized SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (!store.containsAlias(KEY_ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(KEY_ALIAS, null);
    }

    static byte[] encrypt(String value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        ByteArrayOutputStream output = new ByteArrayOutputStream(); output.write(cipher.getIV());
        output.write(cipher.doFinal(value.getBytes(StandardCharsets.UTF_8))); return output.toByteArray();
    }

    static String decrypt(byte[] value) throws Exception {
        if (value.length < 28) throw new SecurityException();
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, value, 0, 12));
        return new String(cipher.doFinal(value, 12, value.length - 12), StandardCharsets.UTF_8);
    }

    private static byte[] encryptChunk(String value, long generation, int index) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        cipher.updateAAD(("state:" + generation + ":" + index).getBytes(StandardCharsets.US_ASCII));
        ByteArrayOutputStream output = new ByteArrayOutputStream(); output.write(cipher.getIV());
        output.write(cipher.doFinal(value.getBytes(StandardCharsets.UTF_8))); return output.toByteArray();
    }

    private static String decryptChunk(byte[] value, long generation, int index) throws Exception {
        if (value.length < 28 || value.length > CHUNK_CHARACTERS * 4 + 28) throw new SecurityException();
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, value, 0, 12));
        cipher.updateAAD(("state:" + generation + ":" + index).getBytes(StandardCharsets.US_ASCII));
        return new String(cipher.doFinal(value, 12, value.length - 12), StandardCharsets.UTF_8);
    }

    JSObject read() throws Exception {
        // Preserve the inline reader's original atomic snapshot across handles.
        database.beginTransaction();
        try {
            try (ReadLease saved = openReadLease()) {
                if (saved.length > MAX_INLINE_CHARACTERS) throw new SecurityException();
                StringBuilder result = new StringBuilder(saved.length);
                for (int index = 0; index < saved.chunks; index++) result.append(saved.next(index));
                saved.finish();
                return new JSObject().put("generation", saved.generation).put("payload", result.toString());
            }
        } finally { database.endTransaction(); }
    }

    long write(long generation, String payload) throws Exception {
        if (generation < 0 || generation >= MAX_GENERATION || payload == null || payload.length() > MAX_INLINE_CHARACTERS) throw new IllegalArgumentException();
        database.beginTransaction();
        // SQLite may already roll back a full transaction. Keep that original
        // write failure and suppress any secondary endTransaction failure.
        try (AutoCloseable transaction = database::endTransaction) {
            long current = 0;
            try (Cursor cursor = database.rawQuery("SELECT generation FROM state WHERE id=1", null)) {
                if (cursor.moveToFirst()) current = cursor.getLong(0);
            }
            if (current != generation) throw new IllegalStateException("state conflict");
            database.execSQL("DELETE FROM state_chunks");
            database.execSQL("DELETE FROM operations_state");
            database.execSQL("DELETE FROM operations_chunks");
            MessageDigest digest = MessageDigest.getInstance("SHA-256"); int index = 0;
            for (int offset = 0; offset < payload.length(); offset += CHUNK_CHARACTERS) {
                String fragment = payload.substring(offset, Math.min(offset + CHUNK_CHARACTERS, payload.length()));
                digest.update(fragment.getBytes(StandardCharsets.UTF_8));
                database.execSQL("INSERT INTO state_chunks(piece,payload) VALUES(?,?)", new Object[]{index, encryptChunk(fragment, current + 1, index++)});
            }
            JSONObject metadata = new JSONObject().put("length", payload.length()).put("chunks", index).put("sha256", hex(digest.digest()));
            database.execSQL("INSERT OR REPLACE INTO state(id,generation,payload) VALUES(1,?,?)", new Object[]{current + 1, encrypt(FORMAT + metadata)});
            database.setTransactionSuccessful(); return current + 1;
        }
    }

    long currentGeneration() {
        try (Cursor row = database.rawQuery("SELECT generation FROM state WHERE id=1", null)) {
            long value = row.moveToFirst() ? row.getLong(0) : 0;
            if (value < 0 || value > MAX_GENERATION) throw new SecurityException();
            return value;
        }
    }

    /** Authenticated bounded reader; no complete capsule String is allocated. */
    final class ReadLease implements AutoCloseable {
        final long generation;
        final int length, chunks;
        final String expectedHash;
        final boolean chunked;
        private String legacy;
        private DataInputStream input;
        private long cipherGeneration;
        private boolean operations;
        private PendingWrite owned;
        private final MessageDigest digest = MessageDigest.getInstance("SHA-256");
        private int next, characters;
        private boolean closed, finished;

        ReadLease(long generation, int length, int chunks, String expectedHash,
                boolean chunked, String legacy) throws Exception {
            this.generation = generation; this.length = length; this.chunks = chunks;
            this.expectedHash = expectedHash; this.chunked = chunked; this.legacy = legacy;
            this.cipherGeneration = generation;
        }

        synchronized String next(int index) throws Exception {
            if (closed || finished || index != next || index >= chunks) throw new SecurityException();
            String fragment;
            if (input != null) {
                if (currentGeneration() != generation) throw new IllegalStateException("STATE_CONFLICT");
                int size = input.readInt();
                if (size < 28 || size > CHUNK_CHARACTERS * 4 + 28) throw new SecurityException();
                byte[] bytes = new byte[size]; input.readFully(bytes);
                fragment = decryptChunk(bytes, cipherGeneration, index);
            } else if (chunked) {
                // One statement binds the ciphertext to the current envelope generation.
                try (Cursor row = database.rawQuery(
                        "SELECT c.payload FROM state s JOIN " + (operations ? "operations_chunks" : "state_chunks") + " c ON c.piece=? "
                            + "WHERE s.id=1 AND s.generation=?",
                        new String[]{String.valueOf(index), String.valueOf(generation)})) {
                    if (!row.moveToFirst()) {
                        if (currentGeneration() != generation) throw new IllegalStateException("STATE_CONFLICT");
                        throw new SecurityException("MISSING_STATE_CHUNK");
                    }
                    fragment = decryptChunk(row.getBlob(0), cipherGeneration, index);
                }
            } else {
                if (currentGeneration() != generation) throw new IllegalStateException("STATE_CONFLICT");
                fragment = legacy.substring(index * CHUNK_CHARACTERS,
                    Math.min((index + 1) * CHUNK_CHARACTERS, length));
            }
            if (fragment.length() > CHUNK_CHARACTERS || characters + fragment.length() > length)
                throw new SecurityException();
            digest.update(fragment.getBytes(StandardCharsets.UTF_8));
            characters += fragment.length(); next++;
            return fragment;
        }

        synchronized void finish() throws Exception {
            if (closed || finished || next != chunks || characters != length
                    || currentGeneration() != generation) throw new SecurityException();
            if (chunked) {
                try (Cursor rows = database.rawQuery("SELECT COUNT(*) FROM " + (operations ? "operations_chunks" : "state_chunks"), null)) {
                    rows.moveToFirst(); if (rows.getInt(0) != chunks) throw new SecurityException();
                }
            }
            if (input != null && input.read() != -1) throw new SecurityException();
            if (expectedHash != null && !hex(digest.digest()).equals(expectedHash)) throw new SecurityException();
            finished = true; legacy = null;
        }

        synchronized boolean finished() { return finished && !closed; }
        @Override public synchronized void close() {
            closed = true; legacy = null;
            if (input != null) { try { input.close(); } catch (IOException ignored) { } input = null; }
            if (owned != null) { owned.close(); owned = null; }
        }
    }

    private ReadLease openBaseLease() throws Exception {
        database.beginTransactionNonExclusive();
        try {
            ReadLease result;
            try (Cursor row = database.rawQuery("SELECT generation,payload FROM state WHERE id=1", null)) {
                if (!row.moveToFirst()) {
                    result = new ReadLease(0, 0, 0, null, false, "");
                } else {
                    long generation = row.getLong(0);
                    if (generation < 0 || generation > MAX_GENERATION) throw new SecurityException();
                    String envelope = decrypt(row.getBlob(1));
                    if (envelope.startsWith(FORMAT)) {
                        JSONObject metadata = new JSONObject(envelope.substring(FORMAT.length()));
                        int length = metadata.getInt("length"), count = metadata.getInt("chunks");
                        String hash = metadata.getString("sha256");
                        if (length < 0 || length > MAX_CHARACTERS
                                || count != (length + CHUNK_CHARACTERS - 1) / CHUNK_CHARACTERS
                                || !hash.matches("[a-f0-9]{64}")) throw new SecurityException();
                        result = new ReadLease(generation, length, count, hash, true, null);
                        result.cipherGeneration = metadata.optLong("cipher_generation", generation);
                        if (result.cipherGeneration < 0 || result.cipherGeneration > generation) throw new SecurityException();
                    } else {
                        if (envelope.length() > MAX_INLINE_CHARACTERS) throw new SecurityException();
                        result = new ReadLease(generation, envelope.length(),
                            (envelope.length() + CHUNK_CHARACTERS - 1) / CHUNK_CHARACTERS,
                            null, false, envelope);
                    }
                }
            }
            database.setTransactionSuccessful(); return result;
        } finally { database.endTransaction(); }
    }

    StartupLease openStartupLease() throws Exception {
        ReadLease base = openBaseLease();
        ReadLease delta = null;
        try {
            try (Cursor row = database.rawQuery("SELECT payload FROM operations_state WHERE id=1", null)) {
                if (row.moveToFirst()) {
                    JSONObject info = new JSONObject(decrypt(row.getBlob(0)));
                    int length = info.getInt("length"), chunks = info.getInt("chunks");
                    String hash = info.getString("sha256");
                    if (info.getLong("generation") != base.generation || length < 0 || length > MAX_CHARACTERS
                            || chunks != (length + CHUNK_CHARACTERS - 1) / CHUNK_CHARACTERS
                            || !hash.matches("[a-f0-9]{64}")) throw new SecurityException();
                    delta = new ReadLease(base.generation, length, chunks, hash, true, null);
                    delta.operations = true;
                }
            }
            if (delta == null) {
                if (base.cipherGeneration != base.generation) throw new SecurityException();
                return new StartupLease(base, null);
            }
            return new StartupLease(base, delta);
        } catch (Exception error) {
            base.close(); if (delta != null) delta.close();
            throw error;
        }
    }

    static final class StartupLease implements AutoCloseable {
        final ReadLease base, operations;
        StartupLease(ReadLease base, ReadLease operations) { this.base = base; this.operations = operations; }
        @Override public void close() { base.close(); if (operations != null) operations.close(); }
    }

    ReadLease openReadLease() throws Exception {
        ReadLease base = openBaseLease();
        ReadLease delta = null;
        PendingWrite merged = null;
        try {
            try (Cursor row = database.rawQuery("SELECT payload FROM operations_state WHERE id=1", null)) {
                if (row.moveToFirst()) {
                    JSONObject info = new JSONObject(decrypt(row.getBlob(0)));
                    int length = info.getInt("length"), chunks = info.getInt("chunks");
                    String hash = info.getString("sha256");
                    if (info.getLong("generation") != base.generation || length < 0 || length > MAX_CHARACTERS
                            || chunks != (length + CHUNK_CHARACTERS - 1) / CHUNK_CHARACTERS
                            || !hash.matches("[a-f0-9]{64}")) throw new SecurityException();
                    delta = new ReadLease(base.generation, length, chunks, hash, true, null);
                    delta.operations = true;
                }
            }
            if (delta == null) {
                if (base.cipherGeneration != base.generation) throw new SecurityException();
                return base;
            }
            merged = new PendingWrite(new File(database.getPath()).getParentFile(), base.generation);
            StateArchiveMerge.merge(base, delta, merged);
            ReadLease result = stagedLease(merged, base.generation);
            result.owned = merged;
            merged = null;
            base.close(); delta.close();
            return result;
        } catch (Exception error) {
            base.close(); if (delta != null) delta.close();
            throw error;
        } finally { if (merged != null) merged.close(); }
    }

    /** Replace only the operations capsule, preserving market ciphertext. */
    long commitOperations(long previous, PendingWrite staged) throws Exception {
        // Validate the small delta before the authoritative transaction.
        try (ReadLease delta = stagedLease(staged, previous)) { StateArchiveMerge.validateOperations(delta); }
        synchronized (staged) {
            database.beginTransaction();
            try (AutoCloseable transaction = database::endTransaction;
                    DataInputStream input = new DataInputStream(new FileInputStream(staged.file))) {
                if (currentGeneration() != previous) throw new IllegalStateException("state conflict");
                JSONObject base;
                try (Cursor row = database.rawQuery("SELECT payload FROM state WHERE id=1", null)) {
                    if (!row.moveToFirst()) throw new SecurityException();
                    String envelope = decrypt(row.getBlob(0));
                    if (!envelope.startsWith(FORMAT)) throw new SecurityException();
                    base = new JSONObject(envelope.substring(FORMAT.length()));
                }
                if ((long) base.getInt("length") + staged.length + 64 * 1024 > MAX_CHARACTERS)
                    throw new IllegalStateException("STATE_CAPACITY_EXCEEDED");
                base.put("cipher_generation", base.optLong("cipher_generation", previous));
                database.execSQL("DELETE FROM operations_chunks");
                MessageDigest hash = MessageDigest.getInstance("SHA-256"); int characters = 0;
                for (int index = 0; index < staged.chunks; index++) {
                    int size = input.readInt();
                    if (size < 28 || size > CHUNK_CHARACTERS * 4 + 28) throw new SecurityException();
                    byte[] bytes = new byte[size]; input.readFully(bytes);
                    String fragment = decryptChunk(bytes, staged.generation, index);
                    if (fragment.length() != Math.min(CHUNK_CHARACTERS, staged.length - characters)) throw new SecurityException();
                    hash.update(fragment.getBytes(StandardCharsets.UTF_8)); characters += fragment.length();
                    database.execSQL("INSERT INTO operations_chunks VALUES(?,?)", new Object[]{index, bytes});
                }
                if (input.read() != -1 || characters != staged.length || !hex(hash.digest()).equals(staged.hash)) throw new SecurityException();
                JSONObject info = new JSONObject().put("generation", staged.generation).put("length", staged.length)
                    .put("chunks", staged.chunks).put("sha256", staged.hash);
                database.execSQL("INSERT OR REPLACE INTO operations_state VALUES(1,?)", new Object[]{encrypt(info.toString())});
                database.execSQL("UPDATE state SET generation=?,payload=? WHERE id=1",
                    new Object[]{staged.generation, encrypt(FORMAT + base)});
                database.setTransactionSuccessful(); return staged.generation;
            }
        }
    }

    ReadLease stringLease(String value, long generation) throws Exception {
        if (value == null || value.length() > MAX_INLINE_CHARACTERS) throw new IllegalArgumentException();
        return new ReadLease(generation, value.length(),
            (value.length() + CHUNK_CHARACTERS - 1) / CHUNK_CHARACTERS, null, false, value);
    }

    ReadLease stagedLease(PendingWrite staged, long generation) throws Exception {
        synchronized (staged) {
            if (!staged.sealed || staged.disposed || staged.generation != generation + 1)
                throw new SecurityException();
            ReadLease lease = new ReadLease(generation, staged.length, staged.chunks,
                staged.hash, false, null);
            lease.input = new DataInputStream(new FileInputStream(staged.file));
            lease.cipherGeneration = staged.generation;
            return lease;
        }
    }

    /** Single-use ciphertext spool. Bridge callbacks never write authoritative DB tables. */
    static final class PendingWrite implements AutoCloseable {
        static final String PREFIX = "stockai-compute-transfer-";
        final File file;
        final long generation;
        int length, chunks;
        private final boolean unknownLength;
        private DataOutputStream output;
        private final MessageDigest digest = MessageDigest.getInstance("SHA-256");
        private int next, characters;
        private boolean sealed, disposed, tail;
        private String hash;

        PendingWrite(File directory, long previous, int length) throws Exception {
            this(directory, previous, length, false);
        }

        PendingWrite(File directory, long previous) throws Exception {
            this(directory, previous, 0, true);
        }

        private PendingWrite(File directory, long previous, int length, boolean unknown) throws Exception {
            if (previous < 0 || previous >= MAX_GENERATION || length < 0 || length > MAX_CHARACTERS)
                throw new IllegalArgumentException();
            this.generation = previous + 1; this.unknownLength = unknown;
            this.length = unknown ? -1 : length;
            this.chunks = unknown ? -1 : (length + CHUNK_CHARACTERS - 1) / CHUNK_CHARACTERS;
            cleanAbandonedTransfers(directory);
            file = File.createTempFile(PREFIX, ".chunks", directory.getCanonicalFile());
            try { output = new DataOutputStream(new FileOutputStream(file)); }
            catch (Exception error) { file.delete(); throw error; }
        }

        synchronized void append(int index, String fragment) throws Exception {
            if (disposed || sealed || index != next || fragment == null
                    || (unknownLength ? tail || fragment.isEmpty() || fragment.length() > CHUNK_CHARACTERS
                        || characters + fragment.length() > MAX_CHARACTERS
                        : index >= chunks || fragment.length() != Math.min(CHUNK_CHARACTERS, length - characters)))
                throw new SecurityException();
            byte[] bytes = encryptChunk(fragment, generation, index);
            output.writeInt(bytes.length); output.write(bytes);
            digest.update(fragment.getBytes(StandardCharsets.UTF_8));
            characters += fragment.length(); next++;
            tail = fragment.length() < CHUNK_CHARACTERS;
        }

        synchronized void seal() throws Exception {
            if (disposed || sealed || (!unknownLength && (characters != length || next != chunks)))
                throw new SecurityException();
            output.close(); output = null;
            if (unknownLength) { length = characters; chunks = next; }
            hash = hex(digest.digest()); sealed = true;
        }

        @Override public synchronized void close() {
            disposed = true;
            if (output != null) { try { output.close(); } catch (IOException ignored) { } output = null; }
            file.delete(); // Ciphertext only; the next process also removes abandoned spools.
        }
    }

    long commitTransfer(long previous, PendingWrite staged) throws Exception {
        synchronized (staged) {
            if (previous < 0 || previous >= MAX_GENERATION || staged.disposed || !staged.sealed
                    || staged.generation != previous + 1) throw new SecurityException();
            database.beginTransaction();
            try (AutoCloseable transaction = database::endTransaction;
                    DataInputStream input = new DataInputStream(new FileInputStream(staged.file))) {
                if (currentGeneration() != previous) throw new IllegalStateException("state conflict");
                database.execSQL("DELETE FROM state_chunks");
            database.execSQL("DELETE FROM operations_state");
            database.execSQL("DELETE FROM operations_chunks");
                MessageDigest hash = MessageDigest.getInstance("SHA-256"); int characters = 0;
                for (int index = 0; index < staged.chunks; index++) {
                    int size = input.readInt();
                    if (size < 28 || size > CHUNK_CHARACTERS * 4 + 28) throw new SecurityException();
                    byte[] bytes = new byte[size]; input.readFully(bytes);
                    String fragment = decryptChunk(bytes, staged.generation, index);
                    if (fragment.length() != Math.min(CHUNK_CHARACTERS, staged.length - characters))
                        throw new SecurityException();
                    hash.update(fragment.getBytes(StandardCharsets.UTF_8)); characters += fragment.length();
                    database.execSQL("INSERT INTO state_chunks(piece,payload) VALUES(?,?)", new Object[]{index, bytes});
                }
                if (input.read() != -1 || characters != staged.length
                        || !hex(hash.digest()).equals(staged.hash)) throw new SecurityException();
                JSONObject metadata = new JSONObject().put("length", staged.length)
                    .put("chunks", staged.chunks).put("sha256", staged.hash);
                database.execSQL("INSERT OR REPLACE INTO state(id,generation,payload) VALUES(1,?,?)",
                    new Object[]{staged.generation, encrypt(FORMAT + metadata)});
                database.setTransactionSuccessful(); return staged.generation;
            }
        }
    }

    private static boolean spoolsCleaned;
    static synchronized void cleanAbandonedTransfers(File directory) throws Exception {
        if (spoolsCleaned) return;
        File canonical = directory.getCanonicalFile();
        File[] files = canonical.listFiles();
        if (files == null) throw new IOException("STATE_TRANSFER_DIRECTORY_UNAVAILABLE");
        for (File file : files) {
            if (file.getName().startsWith(PendingWrite.PREFIX) && file.getName().endsWith(".chunks")
                    && canonical.equals(file.getCanonicalFile().getParentFile())) file.delete();
        }
        spoolsCleaned = true;
    }
}
