package jp.stockai.app;

import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.Reader;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;

/** Streaming reader/writer for the existing authenticated STOCKAIB1 JSON state. */
final class PortableBackup {
    static final int CHUNK_CHARACTERS = 256 * 1024;
    static final int MAX_PAYLOAD_CHARACTERS = 256 * 1024 * 1024;
    static final long MAX_GENERATION = 9007199254740991L;

    // Decrypted fragments are untrusted until read() returns after EOF/tag
    // validation. Production sinks must only write encrypted quarantine files.
    interface Sink { void append(int index, String fragment) throws Exception; }
    static final class Metadata {
        final long generation;
        final int characters;
        Metadata(long generation, int characters) { this.generation = generation; this.characters = characters; }
    }

    static boolean base64(int value) {
        return value >= 'A' && value <= 'Z' || value >= 'a' && value <= 'z'
            || value >= '0' && value <= '9' || value == '+' || value == '/' || value == '=';
    }

    static final class Writer implements AutoCloseable {
        private final OutputStream cipher;
        private final int length;
        private int written;
        private boolean finished, closed;

        Writer(String password, long generation, int length, OutputStream destination) throws Exception {
            if (length > MAX_PAYLOAD_CHARACTERS) throw new IllegalArgumentException("Backup exceeds restore limit");
            if (generation < 0 || generation > MAX_GENERATION || length < 0) throw new IllegalArgumentException();
            byte[] prefix = ("{\"generation\":" + generation + ",\"payload\":\"").getBytes(StandardCharsets.US_ASCII);
            cipher = BackupCrypto.encrypting(password, (long) prefix.length + length + 2, destination);
            this.length = length;
            cipher.write(prefix);
        }

        void append(String fragment) throws Exception {
            if (closed || finished || fragment == null || fragment.length() > CHUNK_CHARACTERS
                    || written + (long) fragment.length() > length) throw new SecurityException();
            for (int index = 0; index < fragment.length(); index++)
                if (!base64(fragment.charAt(index))) throw new SecurityException();
            cipher.write(fragment.getBytes(StandardCharsets.US_ASCII)); written += fragment.length();
        }

        // The caller authenticates its complete source before finishing JSON/tag.
        void finish() throws Exception {
            if (closed || finished || written != length) throw new SecurityException();
            cipher.write('"'); cipher.write('}'); closed = true; cipher.close(); finished = true;
        }

        @Override public void close() throws Exception {
            if (!closed) { closed = true; cipher.close(); }
        }
    }

    static Metadata read(String password, InputStream source, Sink sink) throws Exception {
        try (Reader reader = new InputStreamReader(BackupCrypto.decrypting(password, source),
                StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT))) {
            Cursor cursor = new Cursor(reader);
            cursor.expect('{'); boolean payload = false, generation = false;
            long savedGeneration = 0; int characters = 0;
            for (int field = 0; field < 2; field++) {
                if (field > 0) cursor.expect(',');
                String name = cursor.smallString(); cursor.expect(':');
                if (name.equals("generation") && !generation) {
                    savedGeneration = cursor.generation(); generation = true;
                } else if (name.equals("payload") && !payload) {
                    characters = cursor.payload(sink); payload = true;
                } else throw new SecurityException("Invalid backup fields");
            }
            cursor.expect('}');
            // Reading EOF also forces final GCM tag validation. A parsed object
            // or an early stream close alone is never an authenticated preview.
            if (cursor.token() != -1 || !payload || !generation) throw new SecurityException();
            return new Metadata(savedGeneration, characters);
        }
    }

    private static final class Cursor {
        private final Reader reader;
        private final char[] buffer = new char[8192];
        private int position, count, held = -2;
        Cursor(Reader reader) { this.reader = reader; }
        int read() throws Exception {
            if (held != -2) { int result = held; held = -2; return result; }
            if (count < 0) return -1;
            while (position == count) {
                count = reader.read(buffer); position = 0;
                if (count < 0) return -1;
            }
            return buffer[position++];
        }
        int token() throws Exception {
            int value;
            do { value = read(); } while (value == ' ' || value == '\n' || value == '\r' || value == '\t');
            return value;
        }
        void expect(int expected) throws Exception {
            if (token() != expected) throw new SecurityException("Invalid backup JSON");
        }
        int character() throws Exception {
            int value = read();
            if (value == '"') return -1;
            if (value < 32) throw new SecurityException("Invalid backup string");
            if (value == '\\') {
                value = read();
                if (value == 'u') {
                    value = 0;
                    for (int index = 0; index < 4; index++) {
                        int digit = read();
                        int hex = digit >= '0' && digit <= '9' ? digit - '0'
                            : digit >= 'a' && digit <= 'f' ? digit - 'a' + 10
                            : digit >= 'A' && digit <= 'F' ? digit - 'A' + 10 : -1;
                        if (hex < 0) throw new SecurityException();
                        value = value * 16 + hex;
                    }
                } else if (value != '"' && value != '\\' && value != '/') throw new SecurityException();
            }
            return value;
        }
        String smallString() throws Exception {
            expect('"'); StringBuilder name = new StringBuilder(); int value;
            while ((value = character()) != -1) {
                if (name.length() == 32) throw new SecurityException(); name.append((char) value);
            }
            return name.toString();
        }
        long generation() throws Exception {
            int value = token();
            if (value < '0' || value > '9') throw new SecurityException();
            boolean zero = value == '0'; long result = value - '0'; int digits = 1;
            while ((value = read()) >= '0' && value <= '9') {
                if (zero || ++digits > 16) throw new SecurityException();
                result = result * 10 + value - '0';
                if (result > MAX_GENERATION) throw new SecurityException();
            }
            held = value; return result;
        }
        int payload(Sink sink) throws Exception {
            expect('"'); StringBuilder fragment = new StringBuilder(CHUNK_CHARACTERS);
            int total = 0, piece = 0, value;
            while ((value = character()) != -1) {
                if (!base64(value) || ++total > MAX_PAYLOAD_CHARACTERS) throw new SecurityException();
                fragment.append((char) value);
                if (fragment.length() == CHUNK_CHARACTERS) {
                    sink.append(piece++, fragment.toString()); fragment.setLength(0);
                }
            }
            if (fragment.length() != 0) sink.append(piece, fragment.toString());
            return total;
        }
    }
}
