package jp.stockai.app;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import com.getcapacitor.JSObject;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class ManualAnalysisServiceTest {
    @Test public void serviceFinishesWithActivityBackgroundedAndScreenOff() throws Exception {
        android.content.Context context = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        LocalComputeOwner owner = LocalComputeOwner.get(context);
        java.lang.reflect.Field queue = LocalComputeOwner.class.getDeclaredField("queue"); queue.setAccessible(true);
        java.util.concurrent.CountDownLatch entered = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
        ((java.util.concurrent.ExecutorService) queue.get(owner)).execute(() -> {
            entered.countDown(); try { release.await(); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
        });
        assertTrue(entered.await(10, java.util.concurrent.TimeUnit.SECONDS));
        try (androidx.test.core.app.ActivityScenario<MainActivity> activity = androidx.test.core.app.ActivityScenario.launch(MainActivity.class)) {
            java.util.concurrent.CompletableFuture<JSObject> result = ManualAnalysisService.start(context, "{\"reference_only\":true}");
            assertSame(result, ManualAnalysisService.start(context, "{\"reference_only\":true}"));
            assertTrue(ManualAnalysisService.start(context, "{}").isCompletedExceptionally());
            long limit = android.os.SystemClock.elapsedRealtime() + 15000;
            while (!foreground(context) && android.os.SystemClock.elapsedRealtime() < limit) Thread.sleep(100);
            assertTrue("Analysis must be an admitted foreground service", foreground(context));
            activity.moveToState(androidx.lifecycle.Lifecycle.State.CREATED);
            shell("input keyevent KEYCODE_SLEEP");
            assertFalse(context.getSystemService(android.os.PowerManager.class).isInteractive());
            assertTrue("Calculation must retain a bounded partial wake lock", holdsWakeLock());
            release.countDown();
            JSObject response = result.get(180, java.util.concurrent.TimeUnit.SECONDS);
            assertEquals(200, response.getInt("status"));
            assertFalse(response.getJSONObject("body").has("manual_decision"));
            assertFalse(foreground(context));
            assertFalse(holdsWakeLock());
        } finally { release.countDown(); shell("input keyevent KEYCODE_WAKEUP"); }
    }

    private static boolean foreground(android.content.Context context) {
        return context.getSystemService(android.app.ActivityManager.class).getRunningServices(Integer.MAX_VALUE).stream()
            .anyMatch(value -> value.service.getClassName().equals(ManualAnalysisService.class.getName()) && value.foreground);
    }
    private static boolean holdsWakeLock() throws Exception {
        // dumpsys also retains an ACQ/REL history; only inspect currently held locks.
        return java.util.regex.Pattern.compile("(?m)^\\s*PARTIAL_WAKE_LOCK[^\\n]*StockAI:manual-analysis")
            .matcher(shell("dumpsys power")).find();
    }
    private static String shell(String command) throws Exception {
        try (android.os.ParcelFileDescriptor descriptor = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command);
                java.io.FileInputStream input = new java.io.FileInputStream(descriptor.getFileDescriptor())) {
            return new String(input.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        }
    }
    @Test public void bothStagesFinishWithoutAnyPageCallback() throws Exception {
        List<String> calls = new ArrayList<>(), phases = new ArrayList<>();
        JSObject result = ManualAnalysisService.run("{}", (path, body) -> {
            calls.add(path);
            return new JSObject().put("status", 200).put("body", new JSONObject().put("saved", path));
        }, phases::add);
        assertEquals(List.of("/api/v1/mobile/daily/generate", "/api/v1/mobile/decision/generate"), calls);
        assertEquals(List.of("calculating", "deciding"), phases);
        assertEquals("/api/v1/mobile/decision/generate", result.getJSONObject("body").getJSONObject("manual_decision").getString("saved"));
    }
    @Test public void referenceDoesNotGenerateTodaysSharesAndErrorsStopTheChain() throws Exception {
        List<String> calls = new ArrayList<>();
        ManualAnalysisService.run("{\"reference_only\":true}", (path, body) -> {
            calls.add(path); return new JSObject().put("status", 200).put("body", new JSONObject());
        }, phase -> {});
        assertEquals(1, calls.size()); calls.clear();
        JSObject result = ManualAnalysisService.run("{}", (path, body) -> {
            calls.add(path); return new JSObject().put("status", 422).put("body", new JSONObject());
        }, phase -> {});
        assertEquals(1, calls.size()); assertEquals(422, result.getInt("status"));
        assertTrue(ManualAnalysisService.handles("POST", "/api/v1/mobile/daily/generate"));
        assertFalse(ManualAnalysisService.handles("GET", "/api/v1/mobile/daily/generate"));
        assertFalse(ManualAnalysisService.handles("POST", "/api/v1/mobile/personal/current/confirm"));
    }
    @Test public void timedOutForecastContinuesOnlyWithNewDurableWorkAndBoundedRetries() throws Exception {
        long[] revision = {0}; int[] calls = {0};
        JSObject result = ManualAnalysisService.continueForecast((path, body) -> {
            calls[0]++; revision[0]++;
            if (calls[0] == 1) throw new java.util.concurrent.TimeoutException();
            if (calls[0] == 2) throw new IllegalStateException("COMPUTE_checkpoint_pause_ASSETMASK_15");
            return new JSObject().put("status", 200);
        }, () -> revision[0], "{}");
        assertEquals(200, result.getInt("status")); assertEquals(3, calls[0]);
        calls[0] = 0;
        try {
            ManualAnalysisService.continueForecast((path, body) -> {
                calls[0]++; throw new java.util.concurrent.TimeoutException();
            }, () -> revision[0], "{}"); fail("Repeated without progress");
        } catch (java.util.concurrent.TimeoutException expected) { assertEquals(1, calls[0]); }
        calls[0] = 0;
        try {
            ManualAnalysisService.continueForecast((path, body) -> {
                calls[0]++; revision[0]++; throw new java.util.concurrent.TimeoutException();
            }, () -> revision[0], "{}"); fail("Unlimited retries");
        } catch (java.util.concurrent.TimeoutException expected) { assertEquals(3, calls[0]); }
        assertFalse(ManualAnalysisService.canContinue(new IllegalStateException("COMPUTE_request_python")));
    }

}
