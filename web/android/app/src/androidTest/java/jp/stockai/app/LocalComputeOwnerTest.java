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
        CompletableFuture<JSObject> first = owner.request("POST", "/api/v1/mobile/portfolio", emptyProfile());
        // Independent callers use the same authoritative state. The second
        // initial revision must conflict, rather than overwriting the first.
        CompletableFuture<JSObject> competing = LocalComputeOwner.get(context, file)
            .request("POST", "/api/v1/mobile/portfolio", emptyProfile());
        JSObject saved = result(first);
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
        owner.state.database.execSQL("CREATE TRIGGER fail_compute_commit BEFORE INSERT ON state BEGIN SELECT RAISE(ABORT,'synthetic disk failure'); END");
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
