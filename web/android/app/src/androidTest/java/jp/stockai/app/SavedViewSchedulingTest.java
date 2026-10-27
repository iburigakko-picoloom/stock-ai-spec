package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import android.content.ContextWrapper;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.getcapacitor.JSObject;
import com.getcapacitor.PluginCall;
import java.io.File;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class SavedViewSchedulingTest {
    @Test public void savedViewReadsDoNotBlockOtherWorkAndClearPreventsPendingRead() throws Exception {
        Context base = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(base.getPackageName().endsWith(".debug"));
        File database = new File(base.getCacheDir(), "preview-scheduling-" + System.nanoTime());
        Context context = new ContextWrapper(base) {
            @Override public File getDatabasePath(String name) { return database; }
        };
        StockAIPlugin plugin = new StockAIPlugin() { @Override public Context getContext() { return context; } };
        SavedReadViews views = SavedReadViews.forDatabase(database);
        CountDownLatch release = new CountDownLatch(1), entered = new CountDownLatch(1);
        try {
            views.save("/api/v1/home", new JSONObject().put("status", 200).put("body", new JSONObject().put("test", "saved")), 1);
            plugin.executor.execute(() -> { entered.countDown(); try { release.await(); } catch (InterruptedException ex) { Thread.currentThread().interrupt(); } });
            assertTrue(entered.await(10, TimeUnit.SECONDS));
            CountDownLatch answered = new CountDownLatch(1);
            AtomicReference<JSObject> result = new AtomicReference<>();
            PluginCall call = new PluginCall(null, "StockAI", "test", "readSavedView", new JSObject().put("path", "/api/v1/home")) {
                @Override public void resolve(JSObject value) { result.set(value); answered.countDown(); }
                @Override public void reject(String message, String code) { answered.countDown(); }
            };
            plugin.readSavedView(call);
            assertTrue("Preview must not wait behind unrelated background work", answered.await(10, TimeUnit.SECONDS));
            assertTrue(result.get().getBoolean("available"));
            assertEquals("saved", result.get().getJSONObject("body").getString("test"));
            release.countDown();

            CountDownLatch invalidated = new CountDownLatch(1), backgroundDone = new CountDownLatch(1);
            AtomicReference<JSObject> afterClear = new AtomicReference<>();
            PluginCall pending = new PluginCall(null, "StockAI", "test2", "readSavedView", new JSObject().put("path", "/api/v1/home")) {
                @Override public void resolve(JSObject value) { afterClear.set(value); invalidated.countDown(); }
                @Override public void reject(String message, String code) { invalidated.countDown(); }
            };
            synchronized (views) {
                plugin.readSavedView(pending);
                plugin.executor.execute(backgroundDone::countDown);
                assertTrue("Blocked preview must not hold background queue", backgroundDone.await(10, TimeUnit.SECONDS));
                views.clear();
            }
            assertTrue(invalidated.await(10, TimeUnit.SECONDS));
            assertFalse("A pending preview cannot recover a cleared copy", afterClear.get().getBoolean("available"));
        } finally {
            release.countDown(); views.clear();
            plugin.executor.shutdownNow(); plugin.displayExecutor.shutdownNow(); plugin.networkExecutor.shutdownNow(); plugin.savedViewExecutor.shutdownNow();
            new File(database.getPath() + ".readviews").delete();
        }
    }
}
