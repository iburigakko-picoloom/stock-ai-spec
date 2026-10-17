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
    static final int MAX_CHARACTERS = 128 * 1024 * 1024;
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
        // Envelope and chunks must come from one snapshot even with another DB handle.
        database.beginTransactionNonExclusive();
        try {
            JSObject result = new JSObject().put("generation", 0).put("payload", "");
            try (Cursor cursor = database.rawQuery("SELECT generation,payload FROM state WHERE id=1", null)) {
                if (cursor.moveToFirst()) {
                    long generation = cursor.getLong(0);
                    if (generation < 0 || generation > MAX_GENERATION) throw new SecurityException();
                    String envelope = decrypt(cursor.getBlob(1)), payload = envelope;
                    if (envelope.startsWith(FORMAT)) {
                        JSONObject metadata = new JSONObject(envelope.substring(FORMAT.length()));
                        int length = metadata.getInt("length"), count = metadata.getInt("chunks");
                        if (length < 0 || length > MAX_CHARACTERS || count != (length + CHUNK_CHARACTERS - 1) / CHUNK_CHARACTERS) throw new SecurityException();
                        StringBuilder content = new StringBuilder(length);
                        MessageDigest digest = MessageDigest.getInstance("SHA-256"); int index = 0;
                        try (Cursor chunks = database.rawQuery("SELECT piece,payload FROM state_chunks ORDER BY piece", null)) {
                            while (chunks.moveToNext()) {
                                if (chunks.getInt(0) != index || index >= count) throw new SecurityException();
                                String fragment = decryptChunk(chunks.getBlob(1), generation, index++);
                                if (fragment.length() > CHUNK_CHARACTERS) throw new SecurityException();
                                digest.update(fragment.getBytes(StandardCharsets.UTF_8)); content.append(fragment);
                            }
                        }
                        if (index != count || content.length() != length || !hex(digest.digest()).equals(metadata.getString("sha256"))) throw new SecurityException();
                        payload = content.toString();
                    }
                    result.put("generation", generation).put("payload", payload);
                }
            }
            database.setTransactionSuccessful(); return result;
        } finally { database.endTransaction(); }
    }

    long write(long generation, String payload) throws Exception {
        if (generation < 0 || generation >= MAX_GENERATION || payload == null || payload.length() > MAX_CHARACTERS) throw new IllegalArgumentException();
        database.beginTransaction();
        try {
            long current = 0;
            try (Cursor cursor = database.rawQuery("SELECT generation FROM state WHERE id=1", null)) {
                if (cursor.moveToFirst()) current = cursor.getLong(0);
            }
            if (current != generation) throw new IllegalStateException("state conflict");
            database.execSQL("DELETE FROM state_chunks");
            MessageDigest digest = MessageDigest.getInstance("SHA-256"); int index = 0;
            for (int offset = 0; offset < payload.length(); offset += CHUNK_CHARACTERS) {
                String fragment = payload.substring(offset, Math.min(offset + CHUNK_CHARACTERS, payload.length()));
                digest.update(fragment.getBytes(StandardCharsets.UTF_8));
                database.execSQL("INSERT INTO state_chunks(piece,payload) VALUES(?,?)", new Object[]{index, encryptChunk(fragment, current + 1, index++)});
            }
            JSONObject metadata = new JSONObject().put("length", payload.length()).put("chunks", index).put("sha256", hex(digest.digest()));
            database.execSQL("INSERT OR REPLACE INTO state(id,generation,payload) VALUES(1,?,?)", new Object[]{current + 1, encrypt(FORMAT + metadata)});
            database.setTransactionSuccessful(); return current + 1;
        } finally { database.endTransaction(); }
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
        private final MessageDigest digest = MessageDigest.getInstance("SHA-256");
        private int next, characters;
        private boolean closed, finished;

        ReadLease(long generation, int length, int chunks, String expectedHash,
                boolean chunked, String legacy) throws Exception {
            this.generation = generation; this.length = length; this.chunks = chunks;
            this.expectedHash = expectedHash; this.chunked = chunked; this.legacy = legacy;
        }

        synchronized String next(int index) throws Exception {
            if (closed || finished || index != next || index >= chunks) throw new SecurityException();
            String fragment;
            if (chunked) {
                // One statement binds the ciphertext to the current envelope generation.
                try (Cursor row = database.rawQuery(
                        "SELECT c.payload FROM state s JOIN state_chunks c ON c.piece=? "
                            + "WHERE s.id=1 AND s.generation=?",
                        new String[]{String.valueOf(index), String.valueOf(generation)})) {
                    if (!row.moveToFirst()) throw new IllegalStateException("STATE_CONFLICT");
                    fragment = decryptChunk(row.getBlob(0), generation, index);
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
                try (Cursor rows = database.rawQuery("SELECT COUNT(*) FROM state_chunks", null)) {
                    rows.moveToFirst(); if (rows.getInt(0) != chunks) throw new SecurityException();
                }
            }
            if (expectedHash != null && !hex(digest.digest()).equals(expectedHash)) throw new SecurityException();
            finished = true; legacy = null;
        }

        synchronized boolean finished() { return finished && !closed; }
        @Override public synchronized void close() { closed = true; legacy = null; }
    }

    ReadLease openReadLease() throws Exception {
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
                    } else {
                        if (envelope.length() > MAX_CHARACTERS) throw new SecurityException();
                        result = new ReadLease(generation, envelope.length(),
                            (envelope.length() + CHUNK_CHARACTERS - 1) / CHUNK_CHARACTERS,
                            null, false, envelope);
                    }
                }
            }
            database.setTransactionSuccessful(); return result;
        } finally { database.endTransaction(); }
    }

    ReadLease stringLease(String value, long generation) throws Exception {
        if (value == null || value.length() > MAX_CHARACTERS) throw new IllegalArgumentException();
        return new ReadLease(generation, value.length(),
            (value.length() + CHUNK_CHARACTERS - 1) / CHUNK_CHARACTERS, null, false, value);
    }

    /** Single-use ciphertext spool. Bridge callbacks never write authoritative DB tables. */
    static final class PendingWrite implements AutoCloseable {
        static final String PREFIX = "stockai-compute-transfer-";
        final File file;
        final long generation;
        final int length, chunks;
        private DataOutputStream output;
        private final MessageDigest digest = MessageDigest.getInstance("SHA-256");
        private int next, characters;
        private boolean sealed, disposed;
        private String hash;

        PendingWrite(File directory, long previous, int length) throws Exception {
            if (previous < 0 || previous >= MAX_GENERATION || length < 0 || length > MAX_CHARACTERS)
                throw new IllegalArgumentException();
            this.generation = previous + 1; this.length = length;
            this.chunks = (length + CHUNK_CHARACTERS - 1) / CHUNK_CHARACTERS;
            cleanAbandonedTransfers(directory);
            file = File.createTempFile(PREFIX, ".chunks", directory.getCanonicalFile());
            try { output = new DataOutputStream(new FileOutputStream(file)); }
            catch (Exception error) { file.delete(); throw error; }
        }

        synchronized void append(int index, String fragment) throws Exception {
            if (disposed || sealed || index != next || index >= chunks || fragment == null
                    || fragment.length() != Math.min(CHUNK_CHARACTERS, length - characters))
                throw new SecurityException();
            byte[] bytes = encryptChunk(fragment, generation, index);
            output.writeInt(bytes.length); output.write(bytes);
            digest.update(fragment.getBytes(StandardCharsets.UTF_8));
            characters += fragment.length(); next++;
        }

        synchronized void seal() throws Exception {
            if (disposed || sealed || characters != length || next != chunks) throw new SecurityException();
            output.close(); output = null;
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
            try (DataInputStream input = new DataInputStream(new FileInputStream(staged.file))) {
                if (currentGeneration() != previous) throw new IllegalStateException("state conflict");
                database.execSQL("DELETE FROM state_chunks");
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
            } finally { database.endTransaction(); }
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
