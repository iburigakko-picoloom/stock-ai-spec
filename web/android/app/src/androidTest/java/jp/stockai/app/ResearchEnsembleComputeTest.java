package jp.stockai.app;

import static org.junit.Assert.*;

import android.app.ActivityManager;
import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.database.sqlite.SQLiteDatabase;
import android.os.Build;
import android.os.ParcelFileDescriptor;
import android.webkit.WebView;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.getcapacitor.JSObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Assume;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Opt-in synthetic PC/native-WASM parity. No private fixture is an APK asset. */
@RunWith(AndroidJUnit4.class)
public class ResearchEnsembleComputeTest {
    Context context;
    LocalComputeOwner owner;
    File database;
    File proofFile;
    JSONObject golden;
    JSONObject proof;
    long started;
    long deadline;
    long sampledJavaUsed;

    @Before public void disposableEmulatorAndPinnedExternalFixture() throws Exception {
        var args = InstrumentationRegistry.getArguments();
        Assume.assumeTrue("Use the isolated synthetic research ensemble controller",
            "fresh-emulator-only".equals(args.getString("stockai.ensemble.confirm")));
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertEquals("jp.stockai.app.debug", context.getPackageName());
        assertEquals(35, Build.VERSION.SDK_INT);
        assertTrue((context.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0);
        assertTrue(Build.HARDWARE.contains("ranchu") || Build.HARDWARE.contains("goldfish"));
        assertNull("Provider credentials must be absent", MarketClient.apiKey(context));
        String session = new NativeSecrets(context).read("session-v2");
        assertTrue(session == null || new JSONObject(session).isNull("credentials"));
        String digest = args.getString("stockai.ensemble.sha256");
        assertNotNull(digest);
        assertTrue(digest.matches("[0-9a-f]{64}"));
        String path = args.getString("stockai.ensemble.path");
        assertEquals("/data/local/tmp/stockai-research-ensemble-" + digest + ".json", path);
        byte[] input;
        // UiAutomation reads only this explicit shell-owned synthetic file.
        // No application/database path or arbitrary shell text is accepted.
        try (InputStream source = new ParcelFileDescriptor.AutoCloseInputStream(
                 InstrumentationRegistry.getInstrumentation().getUiAutomation()
                     .executeShellCommand("cat " + path));
             ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = source.read(buffer)) != -1) {
                assertTrue("Synthetic fixture exceeds 512 KiB", bytes.size() + count <= 512 * 1024);
                bytes.write(buffer, 0, count);
            }
            input = bytes.toByteArray();
        }
        assertEquals(digest, LocalStateStore.hex(MessageDigest.getInstance("SHA-256").digest(input)));
        golden = new JSONObject(new String(input, StandardCharsets.UTF_8));
        assertEquals("SYNTHETIC-research-ensemble-golden-v2", golden.getString("schema_version"));
        for (String key : new String[]{"synthetic_only", "no_market_data", "no_private_models"})
            assertTrue(golden.getBoolean(key));
        assertEquals(0, golden.getInt("fitted_models"));
        assertFalse(golden.getBoolean("owner_approval_created"));
        assertEquals(2, golden.getJSONArray("variants").length());
        assertEquals(600, ComputeHost.TIMEOUT_SECONDS);
        started = System.nanoTime();
        deadline = started + TimeUnit.SECONDS.toNanos(600);
        proofFile = new File(context.getFilesDir(), "research-ensemble-proof-" + digest + ".json");
        assertFalse("Preserve an existing experiment proof", proofFile.exists());
        proof = new JSONObject().put("schema_version", "synthetic-native-ensemble-proof-v1")
            .put("synthetic_only", true).put("actual_android_device", true)
            .put("xiaomi_verified", false).put("model_adopted", false)
            .put("fixture_sha256", digest).put("sdk", Build.VERSION.SDK_INT)
            .put("hardware", Build.HARDWARE).put("scope", "debug API35 emulator, synthetic models only")
            .put("variants", new JSONArray()).put("maximum_absolute_error", 0);
        try (InputStream source = context.getAssets().open("public/python/build-info.json")) {
            proof.put("source_commit", new JSONObject(new String(source.readAllBytes(),
                StandardCharsets.UTF_8)).getString("source_commit"));
        }
        var webview = WebView.getCurrentWebViewPackage();
        proof.put("webview_version", webview == null ? "unknown" : webview.versionName);
        phase("fixture_verified");
    }

    @After public void closeOnlyTheIsolatedOwner() throws Exception {
        if (owner != null) { owner.closeForTest().get(30, TimeUnit.SECONDS); owner = null; }
        if (database != null) { SQLiteDatabase.deleteDatabase(database); database = null; }
    }

    <T> T await(CompletableFuture<T> future) throws Exception {
        long remaining = deadline - System.nanoTime();
        assertTrue("Synthetic native test exceeded the unchanged 600 second budget", remaining > 0);
        return future.get(remaining, TimeUnit.NANOSECONDS);
    }

    void phase(String phase) throws Exception {
        Runtime runtime = Runtime.getRuntime();
        sampledJavaUsed = Math.max(sampledJavaUsed, runtime.totalMemory() - runtime.freeMemory());
        ActivityManager.MemoryInfo memory = new ActivityManager.MemoryInfo();
        context.getSystemService(ActivityManager.class).getMemoryInfo(memory);
        assertFalse("Stop before continuing under low-memory pressure", memory.lowMemory);
        proof.put("phase", phase).put("sampled_max_java_used_bytes", sampledJavaUsed)
            .put("available_memory_bytes", memory.availMem)
            .put("elapsed_seconds", (System.nanoTime() - started) / 1_000_000_000.0);
        try (FileOutputStream output = new FileOutputStream(proofFile)) {
            output.write(proof.toString().getBytes(StandardCharsets.UTF_8));
        }
    }

    JSObject request(String method, String path, Object body) throws Exception {
        JSObject reply = await(owner.request(method, path, body == null ? "null" : body.toString()));
        assertEquals(path, 200, reply.getInt("status"));
        return reply;
    }

    static Set<String> keys(JSONObject value) {
        Set<String> result = new HashSet<>();
        value.keys().forEachRemaining(result::add);
        return result;
    }

    static void same(String path, Object expected, Object actual) throws Exception {
        if (expected == JSONObject.NULL || expected == null) {
            assertTrue(path, actual == null || actual == JSONObject.NULL);
        } else if (expected instanceof JSONObject) {
            assertTrue(path, actual instanceof JSONObject);
            JSONObject left = (JSONObject) expected, right = (JSONObject) actual;
            assertEquals(path, keys(left), keys(right));
            for (String key : keys(left)) same(path + "." + key, left.get(key), right.get(key));
        } else if (expected instanceof JSONArray) {
            assertTrue(path, actual instanceof JSONArray);
            JSONArray left = (JSONArray) expected, right = (JSONArray) actual;
            assertEquals(path, left.length(), right.length());
            for (int i = 0; i < left.length(); i++) same(path + "[" + i + "]", left.get(i), right.get(i));
        } else if (expected instanceof Number) {
            assertTrue(path, actual instanceof Number);
            double left = ((Number) expected).doubleValue(), right = ((Number) actual).doubleValue();
            assertTrue(path, Double.isFinite(left) && Double.isFinite(right));
            assertEquals(path, left, right, 0.0);
        } else assertEquals(path, expected, actual);
    }

    JSONObject parityInput(JSONObject variant, JSONObject rows) throws Exception {
        return new JSONObject().put("content", variant.getString("content")).put("rows", rows)
            .put("rank_universes", golden.getJSONObject("rank_universes"));
    }

    @Test public void pcParityCompleteRanksAndEncryptedOwnerReload() throws Exception {
        JSONArray variants = golden.getJSONArray("variants");
        for (int number = 0; number < variants.length(); number++) {
            JSONObject variant = variants.getJSONObject(number);
            String name = variant.getString("name");
            assertTrue("rank_only".equals(name) || "return_and_rank".equals(name));
            database = File.createTempFile("stockai-ensemble-test-", ".sqlite3", context.getCacheDir());
            owner = LocalComputeOwner.get(context, database);
            JSObject home = request("GET", "/api/v1/home", null);
            JSObject model = request("GET", "/api/v1/mobile/models", null);
            assertEquals(0, model.getJSONObject("body").getInt("imported_bundle_count"));
            assertFalse(model.getJSONObject("body").getBoolean("model_adopted"));
            JSONObject input = parityInput(variant, golden.getJSONObject("rows"));
            JSObject calculated = request("POST", "/api/v1/mobile/models/bundle/parity", input);
            same(name + ".PC_outputs", variant.getJSONObject("expected"), calculated.get("body"));
            JSONObject reversed = new JSONObject(), partial = new JSONObject();
            for (String horizon : new String[]{"5", "20"}) {
                JSONArray rows = golden.getJSONObject("rows").getJSONArray(horizon);
                assertEquals(27, rows.length());
                JSONArray backwards = new JSONArray(), subset = new JSONArray();
                for (int i = rows.length() - 1; i >= 0; i--) backwards.put(rows.get(i));
                for (int i = 1; i < rows.length(); i++) subset.put(rows.get(i));
                reversed.put(horizon, backwards); partial.put(horizon, subset);
            }
            same(name + ".reordered", calculated, request("POST", "/api/v1/mobile/models/bundle/parity",
                parityInput(variant, reversed)));
            assertEquals(422, await(owner.request("POST", "/api/v1/mobile/models/bundle/parity",
                parityInput(variant, partial).toString())).getInt("status"));
            JSONObject snapshot = variant.getJSONObject("snapshot");
            assertEquals("research", snapshot.getString("mode"));
            assertTrue(snapshot.isNull("adoption_review_id"));
            JSONArray predictions = snapshot.getJSONArray("predictions");
            for (int i = 0; i < predictions.length(); i++) {
                JSONObject prediction = predictions.getJSONObject(i);
                for (String absent : new String[]{"downside_quantile", "large_loss_probability", "uncertainty"})
                    assertTrue(prediction.isNull(absent));
                if ("rank_only".equals(name)) {
                    assertTrue(prediction.isNull("expected_return_5d"));
                    assertTrue(prediction.isNull("expected_return_20d"));
                }
            }
            String text = snapshot.toString();
            JSObject preview = request("POST", "/api/v1/daily/import/preview",
                new JSONObject().put("json_text", text));
            assertFalse(preview.getJSONObject("body").getBoolean("writes_performed"));
            request("POST", "/api/v1/daily/import/confirm", new JSONObject().put("json_text", text)
                .put("confirmation_hash", preview.getJSONObject("body").getString("confirmation_hash")));
            JSObject latest = request("GET", "/api/v1/daily/latest", null);
            same(name + ".snapshot", snapshot, latest.getJSONObject("body").get("snapshot"));
            JSONArray research = latest.getJSONObject("body").getJSONArray("research_symbols");
            same(name + ".top20_and_holdings", variant.getJSONArray("research_symbols"), research);
            assertEquals(22, research.length());
            assertEquals("1000", research.getString(20)); assertEquals("1001", research.getString(21));
            JSObject ranking = request("GET", "/api/v1/ranking?rankType=overall&limit=50", null);
            JSONArray ranked = ranking.getJSONArray("body");
            assertEquals(27, ranked.length());
            for (int i = 0; i < ranked.length(); i++) {
                assertEquals(variant.getJSONArray("ranking_symbols").getString(i),
                    ranked.getJSONObject(i).getString("symbol"));
                assertEquals(27, ranked.getJSONObject(i).getInt("total_universe"));
                assertTrue(ranked.getJSONObject(i).isNull("portfolio_action"));
            }
            same(name + ".personal_unchanged", home, request("GET", "/api/v1/home", null));
            same(name + ".policy_unchanged", model, request("GET", "/api/v1/mobile/models", null));
            long generation = owner.state.currentGeneration();
            assertTrue(generation > 0);
            phase(name + "_saved");
            await(owner.closeForTest()); owner = LocalComputeOwner.get(context, database);
            same(name + ".restored_snapshot", latest, request("GET", "/api/v1/daily/latest", null));
            same(name + ".restored_ranking", ranking,
                request("GET", "/api/v1/ranking?rankType=overall&limit=50", null));
            same(name + ".restored_parity", calculated,
                request("POST", "/api/v1/mobile/models/bundle/parity", input));
            same(name + ".restored_personal", home, request("GET", "/api/v1/home", null));
            same(name + ".restored_policy", model, request("GET", "/api/v1/mobile/models", null));
            proof.getJSONArray("variants").put(new JSONObject().put("name", name)
                .put("basic_prediction_rows", 216).put("symbols_per_horizon", 27)
                .put("exact_pc_match", true).put("partial_population_rejected", true)
                .put("top20_plus_all_holdings", research).put("snapshot_restored_exactly", true)
                .put("optional_risk_null", true).put("model_policy_unchanged", true)
                .put("personal_state_unchanged", true).put("saved_generation", generation)
                .put("bundle_sha256", variant.getJSONObject("expected").getString("sha256")));
            phase(name + "_verified");
            await(owner.closeForTest()); owner = null;
            SQLiteDatabase.deleteDatabase(database); database = null;
        }
        phase("verified");
    }
}
