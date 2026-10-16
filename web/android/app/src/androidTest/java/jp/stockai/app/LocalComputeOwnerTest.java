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
}
