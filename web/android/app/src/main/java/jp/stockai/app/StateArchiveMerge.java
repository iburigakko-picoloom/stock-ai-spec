package jp.stockai.app;

import android.util.Base64;
import android.util.Base64InputStream;
import android.util.Base64OutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/** Compose split durable snapshots only at restore/export, using bounded buffers. */
final class StateArchiveMerge {
    private static final long MAX_ENTRY = 256L * 1024 * 1024;

    private static final class LeaseInput extends InputStream {
        final LocalStateStore.ReadLease lease;
        byte[] bytes = new byte[0];
        int offset, index;
        boolean finished;
        LeaseInput(LocalStateStore.ReadLease lease) { this.lease = lease; }
        @Override public int read() throws IOException {
            byte[] one = new byte[1];
            return read(one, 0, 1) < 0 ? -1 : one[0] & 255;
        }
        @Override public int read(byte[] target, int start, int length) throws IOException {
            if (length == 0) return 0;
            try {
                if (offset == bytes.length) {
                    if (index == lease.chunks) {
                        if (!finished) { lease.finish(); finished = true; }
                        return -1;
                    }
                    bytes = lease.next(index++).getBytes(StandardCharsets.US_ASCII); offset = 0;
                }
                int count = Math.min(length, bytes.length - offset);
                System.arraycopy(bytes, offset, target, start, count); offset += count; return count;
            } catch (Exception error) { throw new IOException("STATE_READ_FAILED", error); }
        }
        void finish() throws IOException { byte[] buffer = new byte[8192]; while (read(buffer) != -1) { } }
    }

    private static final class PendingOutput extends OutputStream {
        final LocalStateStore.PendingWrite staged;
        final byte[] buffer = new byte[LocalStateStore.CHUNK_CHARACTERS];
        int used, index;
        boolean closed;
        PendingOutput(LocalStateStore.PendingWrite staged) { this.staged = staged; }
        private void flushChunk() throws IOException {
            if (used == 0) return;
            try { staged.append(index++, new String(buffer, 0, used, StandardCharsets.US_ASCII)); used = 0; }
            catch (Exception error) { throw new IOException("STATE_WRITE_FAILED", error); }
        }
        @Override public void write(int value) throws IOException { write(new byte[]{(byte) value}, 0, 1); }
        @Override public void write(byte[] bytes, int start, int length) throws IOException {
            if (closed) throw new IOException();
            while (length > 0) {
                int count = Math.min(length, buffer.length - used);
                System.arraycopy(bytes, start, buffer, used, count);
                used += count; start += count; length -= count;
                if (used == buffer.length) flushChunk();
            }
        }
        @Override public void close() throws IOException {
            if (closed) return;
            closed = true; flushChunk();
            try { staged.seal(); } catch (Exception error) { throw new IOException("STATE_SEAL_FAILED", error); }
        }
    }

    private static void copy(LocalStateStore.ReadLease lease, ZipOutputStream output, boolean delta) throws Exception {
        LeaseInput raw = new LeaseInput(lease);
        Set<String> names = new HashSet<>();
        try (ZipInputStream zip = new ZipInputStream(new Base64InputStream(raw, Base64.NO_WRAP))) {
            ZipEntry entry;
            byte[] buffer = new byte[64 * 1024];
            while ((entry = zip.getNextEntry()) != null) {
                String name = entry.getName();
                if (entry.isDirectory() || !names.add(name)
                        || !(name.equals("operations.sqlite3") || (!delta && name.equals("mobile.sqlite3"))))
                    throw new SecurityException("UNEXPECTED_STATE_ENTRY");
                boolean emit = output != null && (delta || name.equals("mobile.sqlite3"));
                if (emit) output.putNextEntry(new ZipEntry(name));
                long count = 0; int read;
                while ((read = zip.read(buffer)) != -1) {
                    count += read;
                    if (count > MAX_ENTRY) throw new SecurityException("STATE_ENTRY_TOO_LARGE");
                    if (emit) output.write(buffer, 0, read);
                }
                zip.closeEntry();
                if (emit) output.closeEntry();
            }
            if (!names.equals(delta ? Set.of("operations.sqlite3") : Set.of("operations.sqlite3", "mobile.sqlite3")))
                throw new SecurityException("INCOMPLETE_STATE_ARCHIVE");
        }
        raw.finish();
    }

    static void validateOperations(LocalStateStore.ReadLease lease) throws Exception { copy(lease, null, true); }

    static void merge(LocalStateStore.ReadLease base, LocalStateStore.ReadLease operations,
            LocalStateStore.PendingWrite target) throws Exception {
        try (ZipOutputStream output = new ZipOutputStream(new Base64OutputStream(new PendingOutput(target), Base64.NO_WRAP))) {
            copy(base, output, false);
            copy(operations, output, true);
        }
    }
}
