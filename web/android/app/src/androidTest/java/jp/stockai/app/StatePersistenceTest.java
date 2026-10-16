package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import android.database.sqlite.SQLiteDatabase;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import java.util.Arrays;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class StatePersistenceTest {
    StockAIPlugin plugin;
    File file;

    @Before public void openIsolatedDatabase() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        file = File.createTempFile("stockai-test-", ".sqlite3", context.getCacheDir());
        plugin = new StockAIPlugin() { @Override public Context getContext() { return context; } };
        plugin.db = SQLiteDatabase.openOrCreateDatabase(file, null);
        plugin.initializeStateTables();
    }

    @After public void closeIsolatedDatabase() {
        if (plugin != null) {
            plugin.db.close(); plugin.executor.shutdownNow(); plugin.networkExecutor.shutdownNow();
        }
        if (file != null) SQLiteDatabase.deleteDatabase(file);
    }

    String largeSyntheticPayload() {
        char[] text = new char[3 * 1024 * 1024 + 17]; Arrays.fill(text, 's'); return new String(text);
    }

    @Test public void payloadLargerThanCursorWindowSurvivesReopenAndRejectsStaleWrites() throws Exception {
        String payload = largeSyntheticPayload();
        assertEquals(1, plugin.writeStateData(0, payload));
        plugin.db.close(); plugin.db = SQLiteDatabase.openOrCreateDatabase(file, null);
        assertTrue(payload.equals(plugin.readStateData().getString("payload")));
        try { plugin.writeStateData(0, "stale"); fail("stale generation accepted"); }
        catch (IllegalStateException expected) { /* current generation remains durable */ }
        assertEquals(1, plugin.readStateData().getLong("generation"));
        assertTrue(payload.equals(plugin.readStateData().getString("payload")));
    }

    @Test public void interruptedMultiChunkWriteRollsBackWholeGeneration() throws Exception {
        plugin.writeStateData(0, "previous durable data");
        plugin.db.execSQL("CREATE TRIGGER fail_test_chunk BEFORE INSERT ON state_chunks WHEN NEW.piece=2 BEGIN SELECT RAISE(ABORT,'injected disk failure'); END");
        try { plugin.writeStateData(1, largeSyntheticPayload()); fail("injected failure ignored"); }
        catch (android.database.sqlite.SQLiteException expected) { /* transaction must roll back */ }
        assertEquals("previous durable data", plugin.readStateData().getString("payload"));
        assertEquals(1, plugin.readStateData().getLong("generation"));
    }

    @Test public void removedOrTamperedChunkIsNeverReturnedAsValidState() throws Exception {
        plugin.writeStateData(0, largeSyntheticPayload());
        plugin.db.execSQL("DELETE FROM state_chunks WHERE piece=1");
        try { plugin.readStateData(); fail("missing chunk accepted"); }
        catch (SecurityException expected) { /* fail closed */ }
        plugin.writeStateData(1, "new data");
        plugin.db.execSQL("UPDATE state_chunks SET payload=zeroblob(length(payload)) WHERE piece=0");
        try { plugin.readStateData(); fail("tampered ciphertext accepted"); }
        catch (javax.crypto.AEADBadTagException expected) { /* authenticated encryption */ }
    }

    @Test public void oldSingleEnvelopeReadsAndUpgradesWithoutChangingItsPayload() throws Exception {
        String payload = "synthetic legacy payload";
        plugin.db.execSQL("INSERT INTO state(id,generation,payload) VALUES(1,7,?)", new Object[]{LocalStateStore.encrypt(payload)});
        assertEquals(payload, plugin.readStateData().getString("payload"));
        assertEquals(8, plugin.writeStateData(7, payload));
        assertEquals(payload, plugin.readStateData().getString("payload"));
        assertEquals(8, plugin.readStateData().getLong("generation"));
    }

    @Test public void independentHandlesNeverMixEnvelopeAndChunksFromDifferentGenerations() throws Exception {
        SQLiteDatabase other = SQLiteDatabase.openOrCreateDatabase(file, null);
        LocalStateStore writer = new LocalStateStore(plugin.db), reader = new LocalStateStore(other);
        java.util.concurrent.ExecutorService threads = java.util.concurrent.Executors.newFixedThreadPool(2);
        try {
            java.util.function.IntFunction<String> payload = number -> {
                char[] text = new char[600000]; Arrays.fill(text, (char) ('0' + number)); return new String(text);
            };
            writer.write(0, payload.apply(1));
            java.util.concurrent.Future<?> writes = threads.submit(() -> {
                try { for (int index = 2; index <= 8; index++) writer.write(index - 1, payload.apply(index)); }
                catch (Exception error) { throw new RuntimeException(error); }
            });
            java.util.concurrent.Future<?> reads = threads.submit(() -> {
                try {
                    for (int index = 0; index < 12; index++) {
                        com.getcapacitor.JSObject saved = reader.read();
                        assertEquals(payload.apply((int) saved.getLong("generation")), saved.getString("payload"));
                    }
                } catch (Exception error) { throw new RuntimeException(error); }
            });
            writes.get(60, java.util.concurrent.TimeUnit.SECONDS); reads.get(60, java.util.concurrent.TimeUnit.SECONDS);
        } finally { threads.shutdownNow(); other.close(); }
    }
}
