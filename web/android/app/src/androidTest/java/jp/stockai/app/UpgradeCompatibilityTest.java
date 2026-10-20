package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import com.getcapacitor.JSObject;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.TreeSet;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Run only by the guarded controller, after a real APK replacement. */
@RunWith(AndroidJUnit4.class)
@android.annotation.TargetApi(35)
public class UpgradeCompatibilityTest {
    static void equalJson(Object expected, Object actual) throws Exception {
        if (expected == JSONObject.NULL) { assertSame(JSONObject.NULL, actual); return; }
        if (expected instanceof JSONObject) {
            assertTrue(actual instanceof JSONObject);
            JSONObject left = (JSONObject) expected, right = (JSONObject) actual;
            TreeSet<String> a = new TreeSet<>(), b = new TreeSet<>();
            left.keys().forEachRemaining(a::add); right.keys().forEachRemaining(b::add);
            assertEquals(a, b);
            for (String name : a) equalJson(left.get(name), right.get(name));
        } else if (expected instanceof JSONArray) {
            assertTrue(actual instanceof JSONArray);
            JSONArray left = (JSONArray) expected, right = (JSONArray) actual;
            assertEquals(left.length(), right.length());
            for (int index = 0; index < left.length(); index++) equalJson(left.get(index), right.get(index));
        } else if (expected instanceof Number) {
            assertTrue(actual instanceof Number);
            assertEquals(0, new java.math.BigDecimal(expected.toString()).compareTo(new java.math.BigDecimal(actual.toString())));
        } else assertEquals(expected, actual);
    }

    void check(String phase) throws Exception {
        long started = System.nanoTime();
        Context context = LegacyUpgradeSeedTest.guardedContext();
        JSONObject original = new JSONObject(new String(Files.readAllBytes(new File(context.getFilesDir(), "upgrade-proof.json").toPath()), StandardCharsets.UTF_8));
        JSONObject proof = LegacyUpgradeSeedTest.identity(context), fixture = LegacyUpgradeSeedTest.fixture();
        assertEquals(20000, proof.getLong("version_code"));
        assertEquals(original.getInt("uid"), proof.getInt("uid"));
        assertEquals(original.getString("signature_sha256"), proof.getString("signature_sha256"));
        assertEquals("verify".equals(phase) ? "legacy-seeded" : "verify", original.getString("phase"));
        StockAIPlugin plugin = new StockAIPlugin() { @Override public Context getContext() { return context; } };
        plugin.db = context.openOrCreateDatabase("stockai-device.sqlite3", 0, null);
        try {
            JSObject before = plugin.readStateData();
            assertEquals(original.getLong("generation"), before.getLong("generation"));
            assertEquals(original.getString("verify".equals(phase) ? "payload_sha256" : "export_sha256"),
                LegacyUpgradeSeedTest.sha(before.getString("payload")));
            assertTrue(LegacyUpgradeSeedTest.SYNTHETIC_KEY.equals(plugin.apiKey()));
        } finally {
            plugin.db.close(); plugin.executor.shutdownNow(); plugin.networkExecutor.shutdownNow();
        }
        LocalComputeOwner owner = LocalComputeOwner.get(context);
        try {
            JSObject profile = owner.request("GET", "/api/v1/mobile/portfolio", "null").get(300, TimeUnit.SECONDS);
            JSObject settings = owner.request("GET", "/api/v1/mobile/personal/settings", "null").get(300, TimeUnit.SECONDS);
            assertEquals(200, profile.getInt("status")); assertEquals(200, settings.getInt("status"));
            equalJson(fixture.getJSONObject("profile"), profile.getJSONObject("body"));
            equalJson(fixture.getJSONObject("settings"), settings.getJSONObject("body"));
            JSObject migrated = owner.readState().get(30, TimeUnit.SECONDS);
            assertEquals(original.getLong("generation") + 1, migrated.getLong("generation"));
            String payload = migrated.getString("payload");
            LegacyUpgradeSeedTest.save(context, "upgrade-export.b64", payload);
            proof.put("phase", phase).put("generation", migrated.getLong("generation"))
                .put("export_characters", payload.length()).put("export_sha256", LegacyUpgradeSeedTest.sha(payload))
                .put("synthetic_only", true).put("credential_retained", true)
                .put("elapsed_seconds", (System.nanoTime() - started) / 1_000_000_000.0);
            LegacyUpgradeSeedTest.save(context, "upgrade-proof.json", proof.toString());
        } finally { owner.closeForTest().get(30, TimeUnit.SECONDS); }
    }

    @Test public void verify() throws Exception { check("verify"); }
    @Test public void reopen() throws Exception { check("reopen"); }
}
