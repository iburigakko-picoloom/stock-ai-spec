package jp.stockai.app;

import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import com.getcapacitor.JSObject;
import java.io.ByteArrayOutputStream;
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
}
