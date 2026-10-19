package jp.stockai.app;

import java.io.DataInputStream;
import java.io.FilterInputStream;
import java.io.FilterOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.SecretKeySpec;
import org.bouncycastle.crypto.engines.AESEngine;
import org.bouncycastle.crypto.modes.AEADBlockCipher;
import org.bouncycastle.crypto.modes.GCMBlockCipher;
import org.bouncycastle.crypto.params.AEADParameters;
import org.bouncycastle.crypto.params.KeyParameter;

final class BackupCrypto {
    static final byte[] MAGIC = "STOCKAIB1".getBytes(StandardCharsets.US_ASCII);
    static final int ITERATIONS = 210000;
    static final int MAX_INLINE_ENVELOPE_BYTES = 128 * 1024 * 1024;
    // ASCII state plus bounded JSON/header/tag overhead; not an allocation size.
    static final int MAX_ENVELOPE_BYTES = PortableBackup.MAX_PAYLOAD_CHARACTERS + 4096;
    static final int OVERHEAD_BYTES = MAGIC.length + 60; // salt32 + IV12 + GCM tag16
    static byte[] derive(String password, byte[] salt) throws Exception {
        if (password == null || password.length() < 12 || password.length() > 1024) throw new IllegalArgumentException("Password length");
        PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, ITERATIONS, 256);
        try { return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded(); }
        finally { spec.clearPassword(); }
    }
    static byte[] encrypt(String password, byte[] clear) throws Exception {
        if (clear == null || clear.length > MAX_INLINE_ENVELOPE_BYTES - OVERHEAD_BYTES)
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
        if (data.length < OVERHEAD_BYTES || data.length > MAX_INLINE_ENVELOPE_BYTES || !Arrays.equals(MAGIC, Arrays.copyOfRange(data, 0, MAGIC.length))) throw new SecurityException("Invalid backup envelope");
        byte[] salt = Arrays.copyOfRange(data, MAGIC.length, MAGIC.length + 32), iv = Arrays.copyOfRange(data, MAGIC.length + 32, MAGIC.length + 44);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, new SecretKeySpec(derive(password, salt), "AES"), new GCMParameterSpec(128, iv)); cipher.updateAAD(MAGIC);
        return cipher.doFinal(data, MAGIC.length + 44, data.length - MAGIC.length - 44);
    }

    private static AEADBlockCipher streamingCipher(boolean encrypt, String password,
            byte[] salt, byte[] iv) throws Exception {
        byte[] derived = derive(password, salt);
        try {
            AEADBlockCipher cipher = GCMBlockCipher.newInstance(AESEngine.newInstance());
            cipher.init(encrypt, new AEADParameters(new KeyParameter(derived), 128, iv, MAGIC));
            return cipher;
        } finally { Arrays.fill(derived, (byte) 0); }
    }

    /** Same STOCKAIB1 bytes, with bounded cipher buffers rather than whole arrays. */
    static OutputStream encrypting(String password, long clearBytes, OutputStream destination) throws Exception {
        if (clearBytes < 0 || clearBytes > MAX_ENVELOPE_BYTES - OVERHEAD_BYTES)
            throw new IllegalArgumentException("Backup exceeds restore limit");
        byte[] salt = new byte[32], iv = new byte[12];
        SecureRandom random = new SecureRandom(); random.nextBytes(salt); random.nextBytes(iv);
        AEADBlockCipher cipher = streamingCipher(true, password, salt, iv);
        OutputStream bounded = new LimitedOutput(destination);
        bounded.write(MAGIC); bounded.write(salt); bounded.write(iv);
        return new org.bouncycastle.crypto.io.CipherOutputStream(bounded, cipher);
    }

    /** Reading through EOF is mandatory: it verifies the final GCM tag. */
    static InputStream decrypting(String password, InputStream source) throws Exception {
        InputStream bounded = new LimitedInput(source);
        DataInputStream header = new DataInputStream(bounded);
        byte[] magic = new byte[MAGIC.length], salt = new byte[32], iv = new byte[12];
        header.readFully(magic);
        if (!Arrays.equals(MAGIC, magic)) throw new SecurityException("Invalid backup envelope");
        header.readFully(salt); header.readFully(iv);
        return new org.bouncycastle.crypto.io.CipherInputStream(bounded,
            streamingCipher(false, password, salt, iv), 64 * 1024);
    }

    private static final class LimitedInput extends FilterInputStream {
        private long count;
        LimitedInput(InputStream source) { super(source); }
        @Override public int read() throws IOException {
            int value = in.read();
            if (value >= 0 && ++count > MAX_ENVELOPE_BYTES) throw new IOException("Backup exceeds restore limit");
            return value;
        }
        @Override public int read(byte[] bytes, int offset, int length) throws IOException {
            if (length == 0) return 0;
            int result = in.read(bytes, offset, (int) Math.min(length, MAX_ENVELOPE_BYTES - count + 1));
            if (result > 0 && (count += result) > MAX_ENVELOPE_BYTES) throw new IOException("Backup exceeds restore limit");
            return result;
        }
    }

    private static final class LimitedOutput extends FilterOutputStream {
        private long count;
        LimitedOutput(OutputStream destination) { super(destination); }
        @Override public void write(int value) throws IOException {
            if (count == MAX_ENVELOPE_BYTES) throw new IOException("Backup exceeds restore limit");
            out.write(value); count++;
        }
        @Override public void write(byte[] bytes, int offset, int length) throws IOException {
            if (count + length > MAX_ENVELOPE_BYTES) throw new IOException("Backup exceeds restore limit");
            out.write(bytes, offset, length); count += length;
        }
    }
}
