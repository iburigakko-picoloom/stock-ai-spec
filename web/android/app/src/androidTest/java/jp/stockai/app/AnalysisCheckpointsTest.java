package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import android.database.sqlite.SQLiteDatabase;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class AnalysisCheckpointsTest {
    @Test public void mainThreadStatusNeverWaitsForWriterAndBlockedReasonSurvivesReopen() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        File file = File.createTempFile("checkpoint-main-", ".sqlite", context.getCacheDir());
        try {
            try (SQLiteDatabase db = SQLiteDatabase.openOrCreateDatabase(file, null)) {
                AnalysisCheckpoints saved = new AnalysisCheckpoints(db);
                saved.begin(context, 1, "{}"); saved.write(unit("inputs", "AAAA", 43));
                java.util.concurrent.CountDownLatch held = new java.util.concurrent.CountDownLatch(1);
                java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
                java.util.concurrent.CompletableFuture<Void> writer = java.util.concurrent.CompletableFuture.runAsync(() -> {
                    synchronized (saved) {
                        db.beginTransaction();
                        try { held.countDown(); release.await(); }
                        catch (InterruptedException error) { Thread.currentThread().interrupt(); }
                        finally { db.endTransaction(); }
                    }
                });
                try {
                    assertTrue(held.await(5, java.util.concurrent.TimeUnit.SECONDS));
                    java.util.concurrent.CompletableFuture<Integer> displayed = new java.util.concurrent.CompletableFuture<>();
                    new android.os.Handler(android.os.Looper.getMainLooper()).post(() -> {
                        try { displayed.complete(saved.status(true).getInt("percent")); }
                        catch (Exception error) { displayed.completeExceptionally(error); }
                    });
                    assertEquals(Integer.valueOf(43), displayed.get(1, java.util.concurrent.TimeUnit.SECONDS));
                } finally { release.countDown(); writer.get(5, java.util.concurrent.TimeUnit.SECONDS); }
                saved.finish("blocked", new JSONObject().put("blocking_reasons", new org.json.JSONArray().put("ENSEMBLE_RANK_POPULATION_INCOMPLETE")));
            }
            try (SQLiteDatabase db = SQLiteDatabase.openOrCreateDatabase(file, null)) {
                AnalysisCheckpoints saved = new AnalysisCheckpoints(db);
                assertEquals("blocked", saved.status(false).getString("state"));
                assertEquals("ENSEMBLE_RANK_POPULATION_INCOMPLETE", saved.status(false).getJSONArray("blockingReasons").getString(0));
            }
        } finally { SQLiteDatabase.deleteDatabase(file); }
    }

    @Test public void mainThreadHostCloseNeverWaitsForTransferLock() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        ComputeHost host = new ComputeHost(context);
        java.lang.reflect.Field field = ComputeHost.class.getDeclaredField("transferLock"); field.setAccessible(true);
        Object lock = field.get(host);
        java.util.concurrent.CompletableFuture<Void> closed = new java.util.concurrent.CompletableFuture<>();
        synchronized (lock) {
            new android.os.Handler(android.os.Looper.getMainLooper()).post(() -> {
                host.close(); closed.complete(null);
            });
            closed.get(1, java.util.concurrent.TimeUnit.SECONDS);
        }
        host.close();
    }

    static JSONObject unit(String key, String data, int done) throws Exception {
        return new JSONObject().put("key", key).put("data", data == null ? JSONObject.NULL : data)
            .put("done", done).put("total", 100).put("phase", "features");
    }
    @Test public void encryptedChunksSurviveReopenAndInvalidateChangedInputGeneration() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        File file = File.createTempFile("checkpoint-fixture-", ".sqlite", context.getCacheDir());
        String data = "ABCD".repeat(AnalysisCheckpoints.CHUNK / 2 + 7);
        try {
            try (SQLiteDatabase db = SQLiteDatabase.openOrCreateDatabase(file, null)) {
                AnalysisCheckpoints saved = new AnalysisCheckpoints(db);
                saved.begin(context, 5, "{}");
                saved.write(unit("source-" + "a".repeat(64), "AAAA", 10));
                saved.write(unit("inputs", data, 43));
                assertEquals(43, saved.status(false).getInt("percent"));
                assertEquals("interrupted", saved.status(false).getString("state"));
                saved.failed(new java.util.concurrent.ExecutionException(new java.util.concurrent.TimeoutException()));
                try { saved.write(unit("inputs", "AAAA", 101)); fail("Invalid progress accepted"); }
                catch (SecurityException expected) { }
            }
            try (SQLiteDatabase db = SQLiteDatabase.openOrCreateDatabase(file, null)) {
                AnalysisCheckpoints reopened = new AnalysisCheckpoints(db);
                assertEquals("timeout", reopened.status(false).getString("failure"));
                assertEquals(2, reopened.status(false).getLong("savedRevision"));
                JSONObject recovered = new JSONObject(reopened.begin(context, 5, "{}")).getJSONObject("records");
                assertEquals("", reopened.status(true).getString("failure"));
                assertTrue(recovered.isNull("inputs"));
                assertEquals(data, reopened.read("inputs"));
                assertEquals(1, recovered.length());
                reopened.committed(5, 6);
                reopened.begin(context, 6, "{}");
                assertEquals(data, reopened.read("inputs"));
                reopened.finish("complete"); assertEquals(100, reopened.status(false).getInt("percent"));
                assertEquals(0, new JSONObject(reopened.begin(context, 7, "{}")).getJSONObject("records").length());
                assertEquals(0, reopened.status(true).getInt("savedUnits"));
                assertEquals(2, reopened.status(true).getLong("savedRevision"));
            }
        } finally { SQLiteDatabase.deleteDatabase(file); }
    }
    @Test public void swappedAuthenticatedChunksCannotBecomeAnotherCompletedUnit() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        File file = File.createTempFile("checkpoint-corrupt-", ".sqlite", context.getCacheDir());
        try (SQLiteDatabase db = SQLiteDatabase.openOrCreateDatabase(file, null)) {
            AnalysisCheckpoints journal = new AnalysisCheckpoints(db);
            journal.begin(context, 1, "{}"); journal.write(unit("inputs", "ABCD", 1));
            db.execSQL("UPDATE analysis_checkpoint_chunks SET name=?", new Object[]{"features-" + "a".repeat(64)});
            try { journal.read("features-" + "a".repeat(64)); fail("Reassigned chunk accepted"); }
            catch (SecurityException expected) { }
        } finally { SQLiteDatabase.deleteDatabase(file); }
    }
    @Test public void dedicatedWorkerReadsOneCheckpointOfflineWithActiveRequestFence() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        File file = File.createTempFile("checkpoint-worker-", ".sqlite", context.getCacheDir());
        ComputeHost host = new ComputeHost(context);
        try (SQLiteDatabase db = SQLiteDatabase.openOrCreateDatabase(file, null)) {
            AnalysisCheckpoints journal = new AnalysisCheckpoints(db);
            journal.begin(context, 1, "{}");
            String data = "ABCD".repeat(70000);
            journal.write(unit("inputs", data, 43));
            host.checkpoints = journal;
            host.start();
            java.util.concurrent.CompletableFuture<JSONObject> response = new java.util.concurrent.CompletableFuture<>();
            java.lang.reflect.Field pending = ComputeHost.class.getDeclaredField("pending"); pending.setAccessible(true); pending.set(host, response);
            java.lang.reflect.Field identity = ComputeHost.class.getDeclaredField("requestId"); identity.setAccessible(true); identity.set(host, 1L);
            java.lang.reflect.Field view = ComputeHost.class.getDeclaredField("view"); view.setAccessible(true);
            android.webkit.WebView browser = (android.webkit.WebView) view.get(host);
            String worker = "const read=id=>{const x=new XMLHttpRequest();x.open('GET','" + ComputeHost.ORIGIN
                + "/analysis-checkpoint/'+id+'/inputs',false);x.send();return {status:x.status,value:x.responseText};};"
                + "self.postMessage({wrong:read(2).status,valid:read(1)});";
            String script = "const w=new Worker(URL.createObjectURL(new Blob([" + JSONObject.quote(worker)
                + "],{type:'text/javascript'})));w.onmessage=e=>{StockAICompute.complete('1',JSON.stringify({id:1,state:null,result:e.data}));w.terminate();};";
            new android.os.Handler(android.os.Looper.getMainLooper()).post(() -> browser.evaluateJavascript(script, null));
            JSONObject result = response.get(30, java.util.concurrent.TimeUnit.SECONDS).getJSONObject("result");
            assertEquals(403, result.getInt("wrong"));
            assertEquals(200, result.getJSONObject("valid").getInt("status"));
            assertEquals(data, result.getJSONObject("valid").getString("value"));
            assertEquals(403, host.asset(android.net.Uri.parse(ComputeHost.ORIGIN + "/analysis-checkpoint/1/inputs")).getStatusCode());
        } finally { host.close(); SQLiteDatabase.deleteDatabase(file); }
    }

}
