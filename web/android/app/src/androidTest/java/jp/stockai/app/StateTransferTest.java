package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import android.database.sqlite.SQLiteDatabase;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.io.RandomAccessFile;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class StateTransferTest {
    Context context;
    File file;
    LocalStateStore store;

    @Before public void isolatedState() throws Exception {
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        file = File.createTempFile("stockai-transfer-test-", ".sqlite3", context.getCacheDir());
        store = new LocalStateStore(SQLiteDatabase.openOrCreateDatabase(file, null));
    }

    @After public void closeIsolatedState() {
        if (store != null) store.database.close();
        if (file != null) SQLiteDatabase.deleteDatabase(file);
    }

    interface Attempt { void run() throws Exception; }
    static void rejected(Attempt attempt) throws Exception {
        try { attempt.run(); fail("invalid transfer accepted"); }
        catch (Exception expected) { /* assertion failures are not swallowed */ }
    }

    LocalStateStore.PendingWrite stage(long previous, String value) throws Exception {
        LocalStateStore.PendingWrite staged = new LocalStateStore.PendingWrite(context.getCacheDir(), previous, value.length());
        try {
            for (int offset = 0, index = 0; offset < value.length(); offset += LocalStateStore.CHUNK_CHARACTERS, index++)
                staged.append(index, value.substring(offset, Math.min(offset + LocalStateStore.CHUNK_CHARACTERS, value.length())));
            staged.seal(); return staged;
        } catch (Exception error) { staged.close(); throw error; }
    }

    String readLease() throws Exception {
        try (LocalStateStore.ReadLease lease = store.openReadLease()) {
            StringBuilder value = new StringBuilder();
            for (int index = 0; index < lease.chunks; index++) {
                String fragment = lease.next(index);
                assertTrue(fragment.length() <= LocalStateStore.CHUNK_CHARACTERS); value.append(fragment);
            }
            lease.finish(); assertTrue(lease.finished()); return value.toString();
        }
    }

    private String capsule(java.util.Map<String, String> values) throws Exception {
        java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
        try (java.util.zip.ZipOutputStream zip = new java.util.zip.ZipOutputStream(bytes)) {
            for (java.util.Map.Entry<String, String> value : values.entrySet()) {
                zip.putNextEntry(new java.util.zip.ZipEntry(value.getKey()));
                zip.write(value.getValue().getBytes(StandardCharsets.UTF_8)); zip.closeEntry();
            }
        }
        return android.util.Base64.encodeToString(bytes.toByteArray(), android.util.Base64.NO_WRAP);
    }

    private java.util.Map<String, String> capsuleValues(String encoded) throws Exception {
        java.util.Map<String, String> values = new java.util.HashMap<>();
        try (java.util.zip.ZipInputStream zip = new java.util.zip.ZipInputStream(new java.io.ByteArrayInputStream(
                android.util.Base64.decode(encoded, android.util.Base64.NO_WRAP)))) {
            java.util.zip.ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                values.put(entry.getName(), new String(zip.readAllBytes(), StandardCharsets.UTF_8));
            }
        }
        return values;
    }

    private String baseCipherHash() throws Exception {
        MessageDigest hash = MessageDigest.getInstance("SHA-256");
        try (android.database.Cursor rows = store.database.rawQuery("SELECT payload FROM state_chunks ORDER BY piece", null)) {
            while (rows.moveToNext()) hash.update(rows.getBlob(0));
        }
        return LocalStateStore.hex(hash.digest());
    }

    @Test public void ledgerDeltaPreservesMarketCiphertextAndRestoresLatestOperations() throws Exception {
        store.write(0, capsule(java.util.Map.of("operations.sqlite3", "old", "mobile.sqlite3", "market")));
        String originalCipher = baseCipherHash();
        for (int index = 1; index <= 2; index++) {
            try (LocalStateStore.PendingWrite delta = stage(index, capsule(java.util.Map.of("operations.sqlite3", "ledger" + index)))) {
                assertEquals(index + 1, store.commitOperations(index, delta));
            }
            assertEquals(originalCipher, baseCipherHash());
        }
        store.database.close();
        store = new LocalStateStore(SQLiteDatabase.openOrCreateDatabase(file, null));
        assertEquals(java.util.Map.of("operations.sqlite3", "ledger2", "mobile.sqlite3", "market"), capsuleValues(readLease()));
        String backup = store.read().getString("payload");
        try (LocalStateStore.PendingWrite full = stage(3, backup)) { store.commitTransfer(3, full); }
        assertEquals(capsuleValues(backup), capsuleValues(readLease()));
        try (android.database.Cursor rows = store.database.rawQuery("SELECT COUNT(*) FROM operations_chunks", null)) {
            rows.moveToFirst(); assertEquals(0, rows.getInt(0));
        }
    }

    @Test public void invalidOrInterruptedDeltaLeavesCommittedStateIntact() throws Exception {
        String initial = capsule(java.util.Map.of("operations.sqlite3", "old", "mobile.sqlite3", "market"));
        store.write(0, initial);
        try (LocalStateStore.PendingWrite invalid = stage(1, capsule(java.util.Map.of("mobile.sqlite3", "replacement")))) {
            rejected(() -> store.commitOperations(1, invalid));
        }
        try (LocalStateStore.PendingWrite interrupted = new LocalStateStore.PendingWrite(context.getCacheDir(), 1, 4)) {
            interrupted.append(0, "AAAA");
            rejected(() -> store.commitOperations(1, interrupted));
        }
        assertEquals(1, store.currentGeneration()); assertEquals(initial, readLease());
        assertTrue(LocalComputeOwner.operationsOnly("POST", "/api/v1/mobile/personal/initial/confirm"));
        assertFalse(LocalComputeOwner.operationsOnly("POST", "/api/v1/mobile/market/ingest"));
        assertFalse(LocalComputeOwner.operationsOnly("GET", "/api/v1/mobile/personal/settings"));
    }

    @Test public void failedDeltaReplacementRollsBackPreviousDeltaAndRejectsStaleGeneration() throws Exception {
        store.write(0, capsule(java.util.Map.of("operations.sqlite3", "old", "mobile.sqlite3", "market")));
        try (LocalStateStore.PendingWrite first = stage(1, capsule(java.util.Map.of("operations.sqlite3", "first")))) {
            store.commitOperations(1, first);
        }
        store.database.execSQL("CREATE TRIGGER fail_delta BEFORE UPDATE ON state BEGIN SELECT RAISE(ABORT,'synthetic failure'); END");
        try (LocalStateStore.PendingWrite next = stage(2, capsule(java.util.Map.of("operations.sqlite3", "next")))) {
            rejected(() -> store.commitOperations(2, next));
        }
        assertEquals(2, store.currentGeneration());
        assertEquals("first", capsuleValues(readLease()).get("operations.sqlite3"));
        store.database.execSQL("DROP TRIGGER fail_delta");
        try (LocalStateStore.PendingWrite stale = stage(1, capsule(java.util.Map.of("operations.sqlite3", "stale")))) {
            rejected(() -> store.commitOperations(1, stale));
        }
        assertEquals("first", capsuleValues(readLease()).get("operations.sqlite3"));
        store.database.execSQL("UPDATE operations_chunks SET payload=? WHERE piece=0", new Object[]{new byte[28]});
        rejected(() -> readLease());
    }

    @Test public void multiChunkUnicodeRoundTripUsesExistingFormatAndDeletesSpool() throws Exception {
        String value = "あ".repeat(LocalStateStore.CHUNK_CHARACTERS) + "b".repeat(LocalStateStore.CHUNK_CHARACTERS) + "終";
        File spool;
        try (LocalStateStore.PendingWrite staged = stage(0, value)) {
            spool = staged.file;
            assertTrue(spool.exists()); assertEquals(0, store.currentGeneration());
            assertEquals(1, store.commitTransfer(0, staged));
            assertEquals(value, readLease());
            assertEquals(value, store.read().getString("payload"));
            rejected(() -> store.commitTransfer(0, staged));
        }
        assertFalse(spool.exists());
    }

    @Test public void inlineLegacyAndEmptyStateRemainReadable() throws Exception {
        assertEquals("", readLease());
        store.database.execSQL("INSERT INTO state VALUES(1,4,?)", new Object[]{LocalStateStore.encrypt("legacy あ")});
        assertEquals("legacy あ", readLease());
        try (LocalStateStore.PendingWrite staged = stage(4, "")) {
            assertEquals(5, store.commitTransfer(4, staged));
        }
        assertEquals("", readLease()); assertEquals("", store.read().getString("payload"));
    }

    @Test public void unknownLengthQuarantineIsBoundedSealedAndReadWithoutChangingState() throws Exception {
        store.write(0, "original");
        String first = "A".repeat(LocalStateStore.CHUNK_CHARACTERS);
        try (LocalStateStore.PendingWrite staged = new LocalStateStore.PendingWrite(context.getCacheDir(), 1)) {
            rejected(() -> staged.append(0, ""));
            rejected(() -> store.stagedLease(staged, 1));
            staged.append(0, first); staged.append(1, "QQ==");
            rejected(() -> staged.append(2, "extra"));
            staged.seal(); assertEquals(first.length() + 4, staged.length); assertEquals(2, staged.chunks);
            try (LocalStateStore.ReadLease source = store.stagedLease(staged, 1)) {
                assertEquals(first, source.next(0)); assertEquals("QQ==", source.next(1)); source.finish();
            }
            assertEquals("original", readLease()); assertEquals(1, store.currentGeneration());
        }
    }

    @Test public void quarantineCiphertextTruncationTamperingAndTrailingBytesAreRejected() throws Exception {
        store.write(0, "original");
        for (int mode = 0; mode < 3; mode++) {
            try (LocalStateStore.PendingWrite staged = stage(1, "A".repeat(LocalStateStore.CHUNK_CHARACTERS + 4))) {
                try (RandomAccessFile bytes = new RandomAccessFile(staged.file, "rw")) {
                    if (mode == 0) bytes.setLength(bytes.length() - 1);
                    else if (mode == 1) { bytes.seek(bytes.length()); bytes.write(0); }
                    else { bytes.seek(bytes.length() - 1); int last = bytes.read(); bytes.seek(bytes.length() - 1); bytes.write(last ^ 1); }
                }
                try (LocalStateStore.ReadLease source = store.stagedLease(staged, 1)) {
                    rejected(() -> { for (int index = 0; index < source.chunks; index++) source.next(index); source.finish(); });
                }
                assertEquals("original", readLease()); assertEquals(1, store.currentGeneration());
            }
        }
    }

    @Test public void partialDuplicateWrongOrderAndClosedTransfersNeverCommit() throws Exception {
        store.write(0, "original");
        File spool;
        try (LocalStateStore.PendingWrite staged = new LocalStateStore.PendingWrite(context.getCacheDir(), 1, LocalStateStore.CHUNK_CHARACTERS + 1)) {
            spool = staged.file;
            rejected(() -> staged.append(1, "x"));
            rejected(() -> staged.append(0, "short"));
            rejected(staged::seal);
            rejected(() -> store.commitTransfer(1, staged));
            staged.append(0, "x".repeat(LocalStateStore.CHUNK_CHARACTERS));
            rejected(() -> staged.append(0, "x".repeat(LocalStateStore.CHUNK_CHARACTERS)));
            rejected(staged::seal);
        }
        assertFalse(spool.exists()); assertEquals(1, store.currentGeneration()); assertEquals("original", readLease());
        LocalStateStore.PendingWrite closed = stage(1, "discard"); closed.close();
        rejected(() -> store.commitTransfer(1, closed));
        assertEquals("original", readLease());
    }

    @Test public void competingGenerationRejectsStagedWriteAndStaleReader() throws Exception {
        store.write(0, "original");
        try (LocalStateStore.PendingWrite staged = stage(1, "stale"); LocalStateStore.ReadLease reader = store.openReadLease()) {
            store.write(1, "newer");
            rejected(() -> store.commitTransfer(1, staged));
            rejected(() -> reader.next(0));
            assertEquals("newer", readLease()); assertEquals(2, store.currentGeneration());
        }
    }

    @Test public void truncatedExtraAndTamperedCiphertextRollBackWholeTransaction() throws Exception {
        store.write(0, "original");
        String value = "x".repeat(LocalStateStore.CHUNK_CHARACTERS + 17);
        for (int mode = 0; mode < 3; mode++) {
            try (LocalStateStore.PendingWrite staged = stage(1, value)) {
                try (RandomAccessFile bytes = new RandomAccessFile(staged.file, "rw")) {
                    if (mode == 0) bytes.setLength(bytes.length() - 1);
                    else if (mode == 1) { bytes.seek(bytes.length()); bytes.write(0); }
                    else { bytes.seek(bytes.length() - 1); int last = bytes.read(); bytes.seek(bytes.length() - 1); bytes.write(last ^ 1); }
                }
                rejected(() -> store.commitTransfer(1, staged));
                assertEquals(1, store.currentGeneration()); assertEquals("original", readLease());
            }
        }
    }

    @Test public void databaseInsertFailureRollsBackChunksAndEnvelope() throws Exception {
        store.write(0, "original");
        store.database.execSQL("CREATE TRIGGER fail_transfer BEFORE INSERT ON state BEGIN SELECT RAISE(ABORT,'synthetic failure'); END");
        try (LocalStateStore.PendingWrite staged = stage(1, "replacement")) {
            rejected(() -> store.commitTransfer(1, staged));
        }
        assertEquals(1, store.currentGeneration()); assertEquals("original", readLease());
    }

    void seedFragments(String[] fragments, String hash) throws Exception {
        Method encrypt = LocalStateStore.class.getDeclaredMethod("encryptChunk", String.class, long.class, int.class);
        encrypt.setAccessible(true); int length = 0;
        for (int index = 0; index < fragments.length; index++) {
            length += fragments[index].length();
            store.database.execSQL("INSERT INTO state_chunks VALUES(?,?)", new Object[]{index, encrypt.invoke(null, fragments[index], 1L, index)});
        }
        JSONObject metadata = new JSONObject().put("length", length).put("chunks", fragments.length).put("sha256", hash);
        store.database.execSQL("INSERT INTO state VALUES(1,1,?)", new Object[]{LocalStateStore.encrypt(LocalStateStore.FORMAT + metadata)});
    }

    @Test public void validVariableLengthLegacyChunksKeepTheirByteOrder() throws Exception {
        String[] fragments = {"a".repeat(LocalStateStore.CHUNK_CHARACTERS - 7), "b".repeat(30)};
        String value = String.join("", fragments);
        seedFragments(fragments, LocalStateStore.hex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))));
        assertEquals(value, store.read().getString("payload")); assertEquals(value, readLease());
    }

    @Test public void fullHashAndUnexpectedTrailingDatabaseChunkAreRejected() throws Exception {
        seedFragments(new String[]{"original"}, "0".repeat(64));
        try (LocalStateStore.ReadLease reader = store.openReadLease()) {
            assertEquals("original", reader.next(0)); rejected(reader::finish);
        }
        store.write(1, "valid");
        store.database.execSQL("INSERT INTO state_chunks VALUES(1,?)", new Object[]{new byte[28]});
        try (LocalStateStore.ReadLease reader = store.openReadLease()) {
            assertEquals("valid", reader.next(0)); rejected(reader::finish);
        }
    }
}
