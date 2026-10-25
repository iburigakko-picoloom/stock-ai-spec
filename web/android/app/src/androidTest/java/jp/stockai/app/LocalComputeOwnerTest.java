package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import android.database.sqlite.SQLiteDatabase;
import android.net.Uri;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import com.getcapacitor.JSObject;
import java.io.File;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class LocalComputeOwnerTest {
    Context context;
    File file;
    LocalComputeOwner owner;

    @Before public void isolatedApplicationOwner() throws Exception {
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        file = File.createTempFile("stockai-compute-test-", ".sqlite3", context.getCacheDir());
        owner = LocalComputeOwner.get(context, file);
    }

    @After public void closeIsolatedOwner() throws Exception {
        if (owner != null) owner.closeForTest().get(30, TimeUnit.SECONDS);
        if (file != null) SQLiteDatabase.deleteDatabase(file);
    }

    static <T> T result(CompletableFuture<T> value) throws Exception { return value.get(300, TimeUnit.SECONDS); }

    @Test public void currentPortfolioReadBypassesColdPythonAndBusyCalculationQueue() throws Exception {
        String profile = "{\"schema_version\":\"manual-portfolio-v1\",\"holdings_status\":\"none\",\"investment_budget_yen\":\"1040000\",\"maximum_drawdown_percent\":10,\"accounts\":[],\"holdings\":[]}";
        JSONObject expected = result(owner.request("POST", "/api/v1/mobile/portfolio", profile)).getJSONObject("body");
        result(owner.closeForTest()); owner = LocalComputeOwner.get(context, file);
        java.lang.reflect.Field host = LocalComputeOwner.class.getDeclaredField("host"); host.setAccessible(true);
        assertNull(host.get(owner));
        long start = android.os.SystemClock.elapsedRealtime();
        JSObject actual = NativePortfolioReader.read(context, owner.state);
        long directMs = android.os.SystemClock.elapsedRealtime() - start;
        assertJsonEqual(expected, actual.getJSONObject("body"));
        assertNull("Personal read must not boot Python", host.get(owner));
        java.util.concurrent.CountDownLatch entered = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
        ownerQueue().execute(() -> { entered.countDown(); try { release.await(); } catch (InterruptedException e) { Thread.currentThread().interrupt(); } });
        try {
            assertTrue(entered.await(10, TimeUnit.SECONDS));
            assertJsonEqual(expected, NativePortfolioReader.read(context, owner.state).getJSONObject("body"));
        } finally { release.countDown(); }
        start = android.os.SystemClock.elapsedRealtime();
        assertJsonEqual(expected, result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body"));
        long coldMs = android.os.SystemClock.elapsedRealtime() - start;
        android.util.Log.i("StockAIPersonalBenchmark", "direct_ms=" + directMs + " cold_python_ms=" + coldMs);
        assertTrue("Direct read must complete within ten seconds", directMs < 10000);
        assertTrue("Direct read must beat cold Python", directMs < coldMs);
        JSObject full = result(owner.readState());
        owner.state.write(owner.state.currentGeneration(), full.getString("payload"));
        try (LocalStateStore.StartupLease lease = owner.state.openStartupLease()) { assertNull(lease.operations); }
        assertJsonEqual(expected, NativePortfolioReader.read(context, owner.state).getJSONObject("body"));
        File[] leftovers = context.getCacheDir().listFiles((dir, name) -> name.startsWith("personal-read-"));
        assertNotNull(leftovers); assertEquals(0, leftovers.length);
    }

    @Test public void directPersonalReadRejectsInvalidRecordAndRemovesTemporaryFiles() throws Exception {
        File database = File.createTempFile("invalid-personal-test-", ".sqlite3", context.getCacheDir());
        try {
            try (SQLiteDatabase db = SQLiteDatabase.openOrCreateDatabase(database, null)) {
                db.execSQL("CREATE TABLE manual_portfolio_imports (payload TEXT, content_hash TEXT, export_sha256 TEXT, revision_id TEXT, revision_sequence INTEGER, owner_scope_hash TEXT)");
                db.execSQL("INSERT INTO manual_portfolio_imports VALUES ('{}','invalid','invalid','invalid',1,'invalid')");
            }
            java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
            try (java.util.zip.ZipOutputStream zip = new java.util.zip.ZipOutputStream(bytes)) {
                zip.putNextEntry(new java.util.zip.ZipEntry("operations.sqlite3"));
                java.nio.file.Files.copy(database.toPath(), zip);
                zip.closeEntry();
            }
            owner.state.write(owner.state.currentGeneration(), android.util.Base64.encodeToString(bytes.toByteArray(), android.util.Base64.NO_WRAP));
            try { NativePortfolioReader.read(context, owner.state); fail("Invalid record accepted"); }
            catch (SecurityException expected) { assertEquals("PERSONAL_CONTENT_HASH", expected.getMessage()); }
            File[] leftovers = context.getCacheDir().listFiles((dir, name) -> name.startsWith("personal-read-"));
            assertNotNull(leftovers); assertEquals(0, leftovers.length);
        } finally { SQLiteDatabase.deleteDatabase(database); }
    }

    @Test public void currentBalancesMatchPythonWithoutStartingTheInterpreter() throws Exception {
        JSONObject fixture;
        try (java.io.InputStream input = InstrumentationRegistry.getInstrumentation().getContext().getAssets().open("account-editor-fixture.json")) {
            java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[8192]; int count;
            while ((count = input.read(buffer)) != -1) bytes.write(buffer, 0, count);
            fixture = new JSONObject(bytes.toString("UTF-8"));
        }
        assertTrue(fixture.getBoolean("synthetic_only"));
        owner.state.write(owner.state.currentGeneration(), fixture.getString("state"));
        long start = android.os.SystemClock.elapsedRealtime();
        assertJsonEqual(fixture.getJSONObject("expected"), NativePortfolioReader.read(context, owner.state, true).getJSONObject("body"));
        android.util.Log.i("StockAIPersonalBenchmark", "current_balances_ms=" + (android.os.SystemClock.elapsedRealtime() - start));
        java.lang.reflect.Field host = LocalComputeOwner.class.getDeclaredField("host"); host.setAccessible(true);
        assertNull(host.get(owner));
    }

    private static void assertJsonEqual(Object expected, Object actual) throws Exception {
        if (expected instanceof JSONObject) {
            JSONObject left = (JSONObject) expected, right = (JSONObject) actual;
            assertEquals(left.length(), right.length());
            java.util.Iterator<String> keys = left.keys();
            while (keys.hasNext()) { String key = keys.next(); assertJsonEqual(left.get(key), right.get(key)); }
        } else if (expected instanceof org.json.JSONArray) {
            org.json.JSONArray left = (org.json.JSONArray) expected, right = (org.json.JSONArray) actual;
            assertEquals(left.length(), right.length());
            for (int i = 0; i < left.length(); i++) assertJsonEqual(left.get(i), right.get(i));
        } else if (expected instanceof Number) { assertEquals(((Number) expected).doubleValue(), ((Number) actual).doubleValue(), 0); }
        else assertEquals(expected, actual);
    }

    @Test public void splitStartupSkipsCommitAndSavedDisplayBypassesBusyOwner() throws Exception {
        JSObject saved = result(owner.request("POST", "/api/v1/mobile/portfolio", emptyProfile()));
        JSObject home = result(owner.request("GET", "/api/v1/home", "null"));
        long generation = owner.state.currentGeneration();
        assertTrue(owner.readViews.read("/api/v1/home").getBoolean("readOnly"));
        assertEquals(home.getJSONObject("body").toString(), owner.readViews.read("/api/v1/home").getJSONObject("body").toString());
        try (LocalStateStore.StartupLease leases = owner.state.openStartupLease()) {
            assertNotNull("Personal save stays an independent operations overlay", leases.operations);
        }
        result(owner.closeForTest()); owner = LocalComputeOwner.get(context, file);
        assertTrue(owner.readViews.read("/api/v1/home").getBoolean("available"));
        assertEquals(saved.getJSONObject("body").toString(), result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
        assertEquals("Unchanged startup does not republish state", generation, owner.state.currentGeneration());
        java.util.concurrent.CountDownLatch entered = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
        ownerQueue().execute(() -> { entered.countDown(); try { release.await(); } catch (InterruptedException e) { Thread.currentThread().interrupt(); } });
        try {
            assertTrue(entered.await(10, TimeUnit.SECONDS));
            assertTrue(owner.readViews.read("/api/v1/home").getBoolean("available"));
            try { owner.readViews.read("/api/v1/today/review"); fail("Unsafe route cached"); }
            catch (IllegalArgumentException expected) { }
        } finally { release.countDown(); }
    }

    private java.util.concurrent.ExecutorService ownerQueue() throws Exception {
        java.lang.reflect.Field field = LocalComputeOwner.class.getDeclaredField("queue");
        field.setAccessible(true); return (java.util.concurrent.ExecutorService) field.get(owner);
    }

    @SuppressWarnings("unchecked")
    private <T> CompletableFuture<T> queuedOperation(LocalComputeOwner.Operation<T> operation) throws Exception {
        java.lang.reflect.Method method = LocalComputeOwner.class.getDeclaredMethod("submit", LocalComputeOwner.Operation.class);
        method.setAccessible(true); return (CompletableFuture<T>) method.invoke(owner, operation);
    }

    @Test public void cancelledQueuedWriteCannotChangeTheCommittedProfile() throws Exception {
        JSObject saved = result(owner.request("POST", "/api/v1/mobile/portfolio", emptyProfile()));
        long generation = owner.state.currentGeneration();
        java.util.concurrent.CountDownLatch entered = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
        ownerQueue().execute(() -> {
            entered.countDown();
            try { release.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
        });
        try {
            assertTrue(entered.await(10, TimeUnit.SECONDS));
            CompletableFuture<JSObject> cancelled = owner.request("POST", "/api/v1/mobile/portfolio", revisedProfile(saved).toString());
            assertTrue(cancelled.cancel(true));
            release.countDown();
            assertEquals(generation, result(owner.readState()).getLong("generation"));
            assertEquals(saved.getJSONObject("body").toString(), result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
        } finally { release.countDown(); }
    }

    @Test public void cancelledRunningOperationInterruptsOnlyItsOwnQueueTask() throws Exception {
        java.util.concurrent.CountDownLatch entered = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch interrupted = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
        CompletableFuture<Void> running = queuedOperation(() -> {
            entered.countDown();
            try { release.await(); } catch (InterruptedException error) { interrupted.countDown(); throw error; }
            return null;
        });
        try {
            assertTrue(entered.await(10, TimeUnit.SECONDS));
            CompletableFuture<Integer> neighbour = queuedOperation(() -> 17);
            assertTrue(running.cancel(true));
            assertTrue(interrupted.await(10, TimeUnit.SECONDS));
            assertEquals(Integer.valueOf(17), neighbour.get(10, TimeUnit.SECONDS));
            assertTrue(running.isCancelled());
        } finally { release.countDown(); }
    }

    @Test public void cancellationReleasesQueuedCapacityWithoutRunningCancelledOperations() throws Exception {
        java.util.concurrent.CountDownLatch entered = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.atomic.AtomicInteger calls = new java.util.concurrent.atomic.AtomicInteger();
        ownerQueue().execute(() -> {
            entered.countDown();
            try { release.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
        });
        try {
            assertTrue(entered.await(10, TimeUnit.SECONDS));
            java.util.List<CompletableFuture<Integer>> pending = new java.util.ArrayList<>();
            for (int index = 0; index < 64; index++) pending.add(queuedOperation(calls::incrementAndGet));
            try { queuedOperation(() -> 99).get(10, TimeUnit.SECONDS); fail("queue limit ignored"); }
            catch (java.util.concurrent.ExecutionException expected) { }
            for (CompletableFuture<Integer> request : pending) assertTrue(request.cancel(true));
            CompletableFuture<Integer> next = queuedOperation(() -> 23);
            release.countDown();
            assertEquals(Integer.valueOf(23), next.get(10, TimeUnit.SECONDS));
            assertEquals(0, calls.get());
        } finally { release.countDown(); }
    }

    @Test public void workerStopCallbackCancelsItsPendingCoreWriteAndPreservesOtherCallers() throws Exception {
        JSObject saved = result(owner.request("POST", "/api/v1/mobile/portfolio", emptyProfile()));
        long generation = owner.state.currentGeneration();
        java.util.concurrent.CountDownLatch entered = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.ExecutorService caller = java.util.concurrent.Executors.newSingleThreadExecutor();
        DailyWorker worker = androidx.work.testing.TestWorkerBuilder.from(context, DailyWorker.class, caller).build();
        java.lang.reflect.Method request = DailyWorker.class.getDeclaredMethod("coreRequest", LocalComputeOwner.class, String.class, String.class, String.class);
        request.setAccessible(true);
        java.lang.reflect.Field active = DailyWorker.class.getDeclaredField("activeCore"); active.setAccessible(true);
        ownerQueue().execute(() -> {
            entered.countDown();
            try { release.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
        });
        try {
            assertTrue(entered.await(10, TimeUnit.SECONDS));
            java.util.concurrent.Future<Object> waiting = caller.submit(() -> {
                try { return request.invoke(worker, owner, "POST", "/api/v1/mobile/portfolio", revisedProfile(saved).toString()); }
                catch (java.lang.reflect.InvocationTargetException error) { throw (Exception) error.getCause(); }
            });
            CompletableFuture<?> pending = null;
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
            while (pending == null && System.nanoTime() < deadline) {
                synchronized (worker) { pending = (CompletableFuture<?>) active.get(worker); }
                if (pending == null) Thread.sleep(10);
            }
            assertNotNull(pending);
            CompletableFuture<JSObject> neighbour = owner.readState();
            worker.onStopped();
            assertTrue(pending.isCancelled());
            try { waiting.get(10, TimeUnit.SECONDS); fail("stopped worker kept waiting"); }
            catch (java.util.concurrent.ExecutionException expected) {
                assertTrue(expected.getCause() instanceof java.util.concurrent.CancellationException);
            }
            release.countDown();
            assertEquals(generation, result(neighbour).getLong("generation"));
            assertEquals(saved.getJSONObject("body").toString(), result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
        } finally { release.countDown(); caller.shutdownNow(); }
    }

    static String emptyProfile() {
        return "{\"schema_version\":\"manual-portfolio-v1\",\"holdings_status\":\"none\",\"investment_budget_yen\":null,\"maximum_drawdown_percent\":null,\"accounts\":[],\"holdings\":[]}";
    }

    static org.json.JSONObject revisedProfile(JSObject previous) throws Exception {
        org.json.JSONObject profile = new org.json.JSONObject(emptyProfile()).put("investment_budget_yen", "1000000");
        return new org.json.JSONObject().put("expected_revision_id", previous.getJSONObject("body").getString("revision_id"))
            .put("portfolio", profile);
    }

    @Test public void portableBackupPreviewIsOpaqueAndRestoresTheOriginalProfileAfterRecreation() throws Exception {
        File backup = File.createTempFile("stockai-portable-test-", ".stockaib", context.getCacheDir());
        try {
            JSObject saved = result(owner.request("POST", "/api/v1/mobile/portfolio", emptyProfile()));
            result(owner.exportBackup("synthetic-backup-password", () -> new java.io.FileOutputStream(backup)));
            JSObject changed = result(owner.request("POST", "/api/v1/mobile/portfolio", revisedProfile(saved).toString()));
            assertEquals(200, changed.getInt("status"));
            long generation = owner.state.currentGeneration();
            JSObject preview = result(owner.previewBackup("synthetic-backup-password", () -> new java.io.FileInputStream(backup)));
            assertEquals(2, preview.length()); assertFalse(preview.has("payload"));
            assertTrue(preview.getInt("characters") > 0); assertEquals(generation, owner.state.currentGeneration());
            assertEquals(changed.getJSONObject("body").toString(), result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
            try { result(owner.restoreBackup("wrong-token")); fail("wrong preview accepted"); }
            catch (java.util.concurrent.ExecutionException expected) { }
            assertEquals(generation, owner.state.currentGeneration());
            result(owner.restoreBackup(preview.getString("token")));
            assertEquals(saved.getJSONObject("body").toString(), result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
            try { result(owner.restoreBackup(preview.getString("token"))); fail("consumed preview accepted"); }
            catch (java.util.concurrent.ExecutionException expected) { }
            result(owner.closeForTest()); owner = LocalComputeOwner.get(context, file);
            assertEquals(saved.getJSONObject("body").toString(), result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
        } finally { backup.delete(); }
    }

    @Test public void staleWrongPasswordAndInvalidSqliteBackupKeepTheCommittedProfile() throws Exception {
        File backup = File.createTempFile("stockai-portable-reject-", ".stockaib", context.getCacheDir());
        try {
            JSObject saved = result(owner.request("POST", "/api/v1/mobile/portfolio", emptyProfile()));
            result(owner.exportBackup("synthetic-backup-password", () -> new java.io.FileOutputStream(backup)));
            JSObject preview = result(owner.previewBackup("synthetic-backup-password", () -> new java.io.FileInputStream(backup)));
            JSObject changed = result(owner.request("POST", "/api/v1/mobile/portfolio", revisedProfile(saved).toString()));
            long generation = owner.state.currentGeneration();
            try { result(owner.restoreBackup(preview.getString("token"))); fail("stale preview accepted"); }
            catch (java.util.concurrent.ExecutionException expected) { }
            assertEquals(generation, owner.state.currentGeneration());
            try { result(owner.previewBackup("incorrect-long-password", () -> new java.io.FileInputStream(backup))); fail("wrong password accepted"); }
            catch (java.util.concurrent.ExecutionException expected) { }
            assertEquals(generation, owner.state.currentGeneration());
            byte[] invalid = BackupCrypto.encrypt("synthetic-backup-password",
                "{\"generation\":1,\"payload\":\"bm90LXNxbGl0ZQ==\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8));
            try (java.io.FileOutputStream output = new java.io.FileOutputStream(backup)) { output.write(invalid); }
            JSObject bad = result(owner.previewBackup("synthetic-backup-password", () -> new java.io.FileInputStream(backup)));
            try { result(owner.restoreBackup(bad.getString("token"))); fail("invalid SQLite accepted"); }
            catch (java.util.concurrent.ExecutionException expected) { }
            assertEquals(generation, owner.state.currentGeneration());
            assertEquals(changed.getJSONObject("body").toString(), result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
        } finally { backup.delete(); }
    }

    @Test public void apkOnlyHostRejectsForeignAssetsAndInvalidLocalRequests() throws Exception {
        ComputeHost host = new ComputeHost(context);
        for (String url : new String[]{"https://evil.example/compute.html", "http://compute.stockai.local/compute.html", "https://compute.stockai.local/../private", "https://compute.stockai.local/%2e%2e/private"}) {
            assertEquals(403, host.asset(Uri.parse(url)).getStatusCode());
        }
        for (String path : new String[]{"https://evil.example/api/v1/health", "/api/other", "/api/v1/a\nb", "/api/v1/health#fragment"}) {
            try { LocalComputeOwner.validateRequest("GET", path, "null"); fail("invalid request accepted"); }
            catch (IllegalArgumentException expected) { /* fixed local API only */ }
        }
        assertSame(owner, LocalComputeOwner.get(context, file));
    }

    @Test public void realOfflineInterpreterSerializesCallersAndRestoresAfterOwnerRecreation() throws Exception {
        System.out.println("StockAI test WebView=" + android.webkit.WebView.getCurrentWebViewPackage().versionName);
        assertEquals(200, result(owner.request("GET", "/api/v1/health", "null")).getInt("status"));
        long saveStarted = android.os.SystemClock.elapsedRealtime();
        CompletableFuture<JSObject> first = owner.request("POST", "/api/v1/mobile/portfolio", emptyProfile());
        // Independent callers use the same authoritative state. The second
        // initial revision must conflict, rather than overwriting the first.
        CompletableFuture<JSObject> competing = LocalComputeOwner.get(context, file)
            .request("POST", "/api/v1/mobile/portfolio", emptyProfile());
        JSObject saved = result(first);
        System.out.println("StockAI synthetic_empty_profile_save_ms=" + (android.os.SystemClock.elapsedRealtime() - saveStarted));
        assertEquals(200, saved.getInt("status"));
        assertEquals(409, result(competing).getInt("status"));
        String original = saved.getJSONObject("body").toString();
        String backup = result(owner.readState()).getString("payload");
        result(owner.closeForTest()); owner = LocalComputeOwner.get(context, file);
        assertEquals(original, result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
        long generation = result(owner.readState()).getLong("generation");
        try { result(owner.restore("not-a-valid-backup", null)); fail("bad restore accepted"); }
        catch (java.util.concurrent.ExecutionException expected) { /* keep original owner and durable state */ }
        assertEquals(generation, result(owner.readState()).getLong("generation"));
        assertEquals(original, result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
        result(owner.restore(backup, null));
        assertEquals(original, result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
        // Small profile saves now update the envelope after staging an operations delta.
        owner.state.database.execSQL("CREATE TRIGGER fail_compute_commit BEFORE UPDATE ON state BEGIN SELECT RAISE(ABORT,'synthetic disk failure'); END");
        org.json.JSONObject changed = new org.json.JSONObject().put("expected_revision_id", saved.getJSONObject("body").getString("revision_id"))
            .put("portfolio", new org.json.JSONObject(emptyProfile()));
        try { result(owner.request("POST", "/api/v1/mobile/portfolio", changed.toString())); fail("failed native commit acknowledged"); }
        catch (java.util.concurrent.ExecutionException expected) { /* discard the interpreter's uncommitted new revision */ }
        owner.state.database.execSQL("DROP TRIGGER fail_compute_commit");
        assertEquals(original, result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
        assertFalse(result(owner.request("GET", "/api/v1/health", "null")).getJSONObject("body").getBoolean("orderSubmissionAvailable"));
    }

    @Test public void headlessDailyPipelineCommitsActualCoreReceiptAndResumesAfterOwnerRecreation() throws Exception {
        String prior = java.time.LocalDate.now(DailyPipeline.JST).minusDays(1).toString();
        java.util.List<String> events = new java.util.ArrayList<>();
        DailyPipeline.Market fixture = new DailyPipeline.Market() {
            public org.json.JSONObject fetch(boolean membership, String day, java.util.function.BooleanSupplier stop) throws Exception {
                // Calendar-only synthetic closed days stay inside this isolated
                // test database. No key, account or adopted model is supplied.
                return new MarketDownload(owner.state.database, (endpoint, selected, cursor) -> {
                    if (!endpoint.equals("/markets/calendar")) throw new AssertionError("holiday fetched market rows");
                    events.add("remote:" + day);
                    org.json.JSONObject calendar = new org.json.JSONObject().put("Date", day).put("HolDiv", "0");
                    return new org.json.JSONObject().put("status", 200).put("received_at", java.time.Instant.now().toString())
                        .put("body", new org.json.JSONObject().put("data", new org.json.JSONArray().put(calendar)).put("pagination_key", ""));
                }, membership).fetch(day, 4, stop);
            }
            public void acknowledge(boolean membership, String day, String id) throws Exception {
                if (!membership) {
                    org.json.JSONObject saved = result(owner.request("GET", "/api/v1/mobile/market", "null")).getJSONObject("body");
                    assertTrue(saved.getJSONArray("completed_dates").toString().contains(day));
                    events.add("committed-before-ack:" + day);
                }
                new MarketDownload(owner.state.database, (e, d, c) -> { throw new AssertionError("ack made a request"); }, membership).acknowledge(day, id);
            }
        };
        DailyPipeline.Progress progress = new DailyPipeline.Progress() {
            public void state(String value, String day) { events.add("state:" + value); }
            public void notice(String key, String text) { events.add("notice:" + key); }
        };
        DailyPipeline.Core core = (method, path, body) -> result(owner.request(method, path, body));
        assertTrue(new DailyPipeline(core, fixture, progress, () -> false, java.time.Instant::now).tick(prior));
        assertTrue(events.contains("committed-before-ack:" + prior));
        int fetched = (int) events.stream().filter(e -> e.equals("remote:" + prior)).count();
        assertEquals(1, fetched);
        result(owner.closeForTest()); owner = LocalComputeOwner.get(context, file);
        new DailyPipeline(core, fixture, progress, () -> false, java.time.Instant::now).tick(prior);
        assertEquals(fetched, events.stream().filter(e -> e.equals("remote:" + prior)).count());
        assertFalse(events.contains("state:numerical_saved"));
        assertTrue(result(owner.request("GET", "/api/v1/mobile/market", "null")).getJSONObject("body")
            .getJSONArray("completed_dates").toString().contains(prior));
    }
}
