package jp.stockai.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Credentials are deliberately separate from the portable application backup. */
final class NativeSecrets {
    private static final String ALIAS = "stockai-chatgpt-v1";
    private final SharedPreferences preferences;

    NativeSecrets(Context context) {
        preferences = context.getSharedPreferences("stockai-chatgpt-private", Context.MODE_PRIVATE);
    }

    private static synchronized SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            return generator.generateKey();
        }
        return (SecretKey) store.getKey(ALIAS, null);
    }

    synchronized String read(String name) throws Exception {
        String saved = preferences.getString(name, null);
        if (saved == null) return null;
        byte[] envelope = Base64.decode(saved, Base64.NO_WRAP);
        if (envelope.length < 29) throw new IOException("Invalid credential envelope");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, envelope, 0, 12));
        cipher.updateAAD(name.getBytes(StandardCharsets.UTF_8));
        return new String(cipher.doFinal(envelope, 12, envelope.length - 12), StandardCharsets.UTF_8);
    }

    synchronized void write(String name, String value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        cipher.updateAAD(name.getBytes(StandardCharsets.UTF_8));
        byte[] encrypted = cipher.doFinal(value.getBytes(StandardCharsets.UTF_8));
        byte[] envelope = new byte[12 + encrypted.length];
        System.arraycopy(cipher.getIV(), 0, envelope, 0, 12);
        System.arraycopy(encrypted, 0, envelope, 12, encrypted.length);
        if (!preferences.edit().putString(name, Base64.encodeToString(envelope, Base64.NO_WRAP)).commit())
            throw new IOException("Credential save failed");
    }

    synchronized void remove(String name) throws IOException {
        if (!preferences.edit().remove(name).commit()) throw new IOException("Credential removal failed");
    }
}
