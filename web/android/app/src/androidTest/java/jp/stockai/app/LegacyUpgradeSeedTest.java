package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.util.Base64;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.getcapacitor.JSObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Uses only APIs which exist in the actual last-published source. */
@RunWith(AndroidJUnit4.class)
@android.annotation.TargetApi(35)
public class LegacyUpgradeSeedTest {
    static final String SYNTHETIC_KEY = "TEST_ONLY_UPGRADE_NO_PROVIDER_REQUEST";

    static Context guardedContext() {
        assertEquals("fresh-emulator-only", InstrumentationRegistry.getArguments().getString("stockai.upgrade.confirm"));
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertEquals("jp.stockai.app.debug", context.getPackageName());
        assertEquals(35, Build.VERSION.SDK_INT);
        assertTrue(Build.HARDWARE.contains("ranchu") || Build.HARDWARE.contains("goldfish"));
        return context;
    }

    static JSONObject fixture() throws Exception {
        try (InputStream input = InstrumentationRegistry.getInstrumentation().getContext().getAssets().open("legacy-upgrade.json");
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] block = new byte[16384]; int count;
            while ((count = input.read(block)) != -1) {
                output.write(block, 0, count); assertTrue(output.size() <= 2 * 1024 * 1024);
            }
            JSONObject result = new JSONObject(output.toString("UTF-8"));
            assertTrue(result.getBoolean("synthetic_only"));
            assertTrue(result.getBoolean("no_market_data")); assertEquals(0, result.getInt("models"));
            String payload = result.getString("payload");
            assertEquals(result.getInt("characters"), payload.length());
            assertTrue(payload.length() > 3 * 256 * 1024 && payload.length() < 4 * 1024 * 1024);
            assertEquals(result.getString("payload_sha256"), sha(payload));
            return result;
        }
    }

    static String sha(String value) throws Exception {
        return StockAIPlugin.hex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    }

    static JSONObject identity(Context context) throws Exception {
        PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), PackageManager.GET_SIGNING_CERTIFICATES);
        assertNotNull(info.signingInfo); assertEquals(1, info.signingInfo.getApkContentsSigners().length);
        return new JSONObject().put("version_code", info.getLongVersionCode()).put("uid", context.getApplicationInfo().uid)
            .put("signature_sha256", StockAIPlugin.hex(MessageDigest.getInstance("SHA-256").digest(info.signingInfo.getApkContentsSigners()[0].toByteArray())));
    }

    static void save(Context context, String name, String content) throws Exception {
        try (FileOutputStream output = new FileOutputStream(new File(context.getFilesDir(), name))) {
            output.write(content.getBytes(StandardCharsets.UTF_8)); output.getFD().sync();
        }
    }

    @Test public void seed() throws Exception {
        Context context = guardedContext();
        JSONObject proof = identity(context), fixture = fixture();
        assertEquals(10012, proof.getLong("version_code"));
        StockAIPlugin plugin = new StockAIPlugin() { @Override public Context getContext() { return context; } };
        plugin.db = context.openOrCreateDatabase("stockai-device.sqlite3", 0, null);
        try {
            plugin.initializeStateTables();
            assertEquals(0, plugin.readStateData().getLong("generation"));
            assertNull(plugin.apiKey());
            String payload = fixture.getString("payload");
            assertEquals(1, plugin.writeStateData(0, payload));
            assertTrue(context.getSharedPreferences("stockai-secrets", 0).edit().putString("jquants",
                Base64.encodeToString(plugin.encrypt(SYNTHETIC_KEY), Base64.NO_WRAP)).commit());
            assertTrue(SYNTHETIC_KEY.equals(plugin.apiKey()));
            try { plugin.writeStateData(0, "stale fixture write"); fail("stale write accepted"); }
            catch (IllegalStateException expected) { }
            JSObject saved = plugin.readStateData();
            assertEquals(fixture.getString("payload_sha256"), sha(saved.getString("payload")));
            proof.put("phase", "legacy-seeded").put("generation", saved.getLong("generation"))
                .put("payload_sha256", fixture.getString("payload_sha256")).put("characters", payload.length())
                .put("synthetic_only", true).put("credential_retained", true);
            save(context, "upgrade-proof.json", proof.toString());
        } finally {
            plugin.db.close(); plugin.executor.shutdownNow(); plugin.networkExecutor.shutdownNow();
        }
    }
}
