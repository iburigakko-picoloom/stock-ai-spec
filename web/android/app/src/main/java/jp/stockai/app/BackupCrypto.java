package jp.stockai.app;

import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.SecretKeySpec;

final class BackupCrypto {
    static final byte[] MAGIC = "STOCKAIB1".getBytes(StandardCharsets.US_ASCII);
    static final int ITERATIONS = 210000;
    static final int MAX_ENVELOPE_BYTES = 128 * 1024 * 1024;
    static final int OVERHEAD_BYTES = MAGIC.length + 60; // salt32 + IV12 + GCM tag16
    static byte[] derive(String password, byte[] salt) throws Exception {
        if (password == null || password.length() < 12 || password.length() > 1024) throw new IllegalArgumentException("Password length");
        PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, ITERATIONS, 256);
        try { return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded(); }
        finally { spec.clearPassword(); }
    }
    static byte[] encrypt(String password, byte[] clear) throws Exception {
        if (clear == null || clear.length > MAX_ENVELOPE_BYTES - OVERHEAD_BYTES)
            throw new IllegalArgumentException("Backup exceeds restore limit");
        byte[] salt = new byte[32], iv = new byte[12]; SecureRandom random = new SecureRandom(); random.nextBytes(salt); random.nextBytes(iv);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(derive(password, salt), "AES"), new GCMParameterSpec(128, iv));
        cipher.updateAAD(MAGIC);
        byte[] encrypted = cipher.doFinal(clear), output = new byte[MAGIC.length + 44 + encrypted.length];
        System.arraycopy(MAGIC, 0, output, 0, MAGIC.length);
        System.arraycopy(salt, 0, output, MAGIC.length, 32);
        System.arraycopy(iv, 0, output, MAGIC.length + 32, 12);
        System.arraycopy(encrypted, 0, output, MAGIC.length + 44, encrypted.length);
        return output;
    }
    static byte[] decrypt(String password, byte[] data) throws Exception {
        if (data.length < OVERHEAD_BYTES || data.length > MAX_ENVELOPE_BYTES || !Arrays.equals(MAGIC, Arrays.copyOfRange(data, 0, MAGIC.length))) throw new SecurityException("Invalid backup envelope");
        byte[] salt = Arrays.copyOfRange(data, MAGIC.length, MAGIC.length + 32), iv = Arrays.copyOfRange(data, MAGIC.length + 32, MAGIC.length + 44);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, new SecretKeySpec(derive(password, salt), "AES"), new GCMParameterSpec(128, iv)); cipher.updateAAD(MAGIC);
        return cipher.doFinal(data, MAGIC.length + 44, data.length - MAGIC.length - 44);
    }
}
