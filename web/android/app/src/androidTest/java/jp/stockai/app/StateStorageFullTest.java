package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import android.database.DatabaseUtils;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteFullException;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Real SQLite quota failures in a small isolated DB, not whole-device disk filling. */
@RunWith(AndroidJUnit4.class)
public class StateStorageFullTest {
    Context context;
    File file;
    LocalStateStore store;

    @Before public void isolatedDatabase() throws Exception {
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        file = File.createTempFile("stockai-full-test-", ".sqlite3", context.getCacheDir());
        reopen();
    }

    void reopen() {
        if (store != null) store.database.close();
        store = new LocalStateStore(SQLiteDatabase.openOrCreateDatabase(file, null));
    }

    @After public void closeIsolatedDatabase() {
        if (store != null) store.database.close();
        if (file != null) SQLiteDatabase.deleteDatabase(file);
    }

    LocalStateStore.PendingWrite staged(String value) throws Exception {
        LocalStateStore.PendingWrite pending = new LocalStateStore.PendingWrite(
            context.getCacheDir(), 1, value.length());
        try {
            for (int offset = 0, index = 0; offset < value.length();
                    offset += LocalStateStore.CHUNK_CHARACTERS, index++) {
                pending.append(index, value.substring(offset,
                    Math.min(offset + LocalStateStore.CHUNK_CHARACTERS, value.length())));
            }
            pending.seal();
            return pending;
        } catch (Exception error) {
            pending.close();
            throw error;
        }
    }

    void assertDurable(long generation, String payload) throws Exception {
        assertFalse(store.database.inTransaction());
        assertEquals(generation, store.currentGeneration());
        assertEquals(payload, store.read().getString("payload"));
        assertEquals("ok", DatabaseUtils.stringForQuery(
            store.database, "PRAGMA integrity_check", null));
        try (LocalStateStore.ReadLease lease = store.openReadLease()) {
            StringBuilder read = new StringBuilder();
            for (int index = 0; index < lease.chunks; index++) read.append(lease.next(index));
            lease.finish();
            assertEquals(payload, read.toString());
        }
    }

    void quotaFailureThenRecovery(boolean transfer) throws Exception {
        // Multi-byte UTF-8 and multiple encrypted chunks must both survive.
        String original = "あ".repeat(LocalStateStore.CHUNK_CHARACTERS) + "終";
        assertEquals(1, store.write(0, original));
        long maximum = store.database.getMaximumSize();
        long pages = DatabaseUtils.longForQuery(store.database, "PRAGMA page_count", null);
        long pageSize = store.database.getPageSize();
        long extraPages = (LocalStateStore.CHUNK_CHARACTERS + pageSize - 1) / pageSize;
        long quota = store.database.setMaximumSize((pages + extraPages) * pageSize);
        assertTrue(quota >= pages * pageSize);
        assertTrue("Keep this test's DB below 2 MiB", quota < 2L * 1024 * 1024);
        // Some chunks fit before the larger write exceeds max_page_count.
        String replacement = "N".repeat(12 * LocalStateStore.CHUNK_CHARACTERS + 37);
        assertTrue(replacement.length() > quota);
        File spool = null;
        try {
            if (transfer) {
                try (LocalStateStore.PendingWrite pending = staged(replacement)) {
                    spool = pending.file;
                    store.commitTransfer(1, pending);
                }
            } else {
                store.write(1, replacement);
            }
            fail("A write beyond the isolated SQLite quota succeeded");
        } catch (SQLiteFullException expected) {
            // Require the actual driver error, not an arbitrary injected failure.
        }
        if (transfer) {
            assertNotNull(spool);
            assertFalse("Failed staging file retained", spool.exists());
        }
        assertDurable(1, original);
        reopen();
        assertDurable(1, original);
        assertTrue(store.database.setMaximumSize(maximum) >= maximum);
        assertEquals(2, store.write(1, "TEST_ONLY_RECOVERED_終"));
        try {
            store.write(1, "TEST_ONLY_STALE");
            fail("A failed write advanced the generation or allowed stale replacement");
        } catch (IllegalStateException expected) {
            assertEquals("state conflict", expected.getMessage());
        }
        reopen();
        assertDurable(2, "TEST_ONLY_RECOVERED_終");
    }

    @Test public void directWriteFullPreservesOldChunksAndCanRecover() throws Exception {
        quotaFailureThenRecovery(false);
    }

    @Test public void stagedWriteFullRemovesSpoolPreservesOldChunksAndCanRecover() throws Exception {
        quotaFailureThenRecovery(true);
    }
}
