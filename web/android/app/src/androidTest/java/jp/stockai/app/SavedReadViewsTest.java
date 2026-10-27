package jp.stockai.app;

import static org.junit.Assert.*;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class SavedReadViewsTest {
    @Test public void deferredCopiesRespectClearsAndLatestResponseOrdering() throws Exception {
        File dir = new File(InstrumentationRegistry.getInstrumentation().getTargetContext().getCacheDir(), "deferred-views-" + System.nanoTime());
        List<Runnable> jobs = new ArrayList<>();
        SavedReadViews views = new SavedReadViews(dir, jobs::add);
        try {
            String old = new JSONObject().put("status", 200).put("body", new JSONObject().put("id", "old")).toString();
            String latest = new JSONObject().put("status", 200).put("body", new JSONObject().put("id", "latest")).toString();
            views.saveAsync("/api/v1/home", old, 1);
            assertFalse(views.read("/api/v1/home").getBoolean("available"));
            views.clear(); jobs.remove(0).run();
            assertFalse("A copy queued before a clear must never return", views.read("/api/v1/home").getBoolean("available"));
            views.saveAsync("/api/v1/home", old, 2);
            views.saveAsync("/api/v1/home", latest, 2);
            jobs.remove(0).run();
            assertFalse("Superseded results must not be published", views.read("/api/v1/home").getBoolean("available"));
            jobs.remove(0).run();
            assertEquals("latest", views.read("/api/v1/home").getJSONObject("body").getString("id"));
            views.saveAsync("/api/v1/home", "invalid", 3); jobs.remove(0).run();
            assertFalse("Copy failure invalidates the saved display", views.read("/api/v1/home").getBoolean("available"));
        } finally { views.clear(); dir.delete(); }
    }

    @Test public void fullQueueKeepsExistingHistoricalCopyAndCannotPublishOlderPendingCopy() throws Exception {
        File dir = new File(InstrumentationRegistry.getInstrumentation().getTargetContext().getCacheDir(), "rejected-views-" + System.nanoTime());
        List<Runnable> jobs = new ArrayList<>();
        Executor writer = command -> { if (!jobs.isEmpty()) throw new RejectedExecutionException(); jobs.add(command); };
        SavedReadViews views = new SavedReadViews(dir, writer);
        try {
            views.save("/api/v1/home", new JSONObject().put("status", 200).put("body", new JSONObject().put("id", "previous")), 1);
            views.saveAsync("/api/v1/home", new JSONObject().put("status", 200).put("body", new JSONObject().put("id", "pending")).toString(), 2);
            views.saveAsync("/api/v1/home", new JSONObject().put("status", 200).put("body", new JSONObject().put("id", "rejected")).toString(), 3);
            jobs.remove(0).run();
            assertEquals("previous", views.read("/api/v1/home").getJSONObject("body").getString("id"));
        } finally { views.clear(); dir.delete(); }
    }
    @Test public void displayReadDoesNotOpenDatabaseAndSharesInvalidation() throws Exception {
        File database = new File(InstrumentationRegistry.getInstrumentation().getTargetContext().getCacheDir(), "display-only-" + System.nanoTime());
        SavedReadViews views = SavedReadViews.forDatabase(database);
        try {
            views.save("/api/v1/home", new JSONObject().put("status", 200).put("body", new JSONObject().put("cash", 1040000)), 1);
            SavedReadViews reader = SavedReadViews.forDatabase(database);
            assertSame(views, reader);
            assertTrue(reader.read("/api/v1/home").getBoolean("available"));
            assertFalse(database.exists());
            views.save("/api/v1/mobile/portfolio", new JSONObject().put("status", 200)
                .put("body", new JSONObject().put("revision_id", "saved-fixture")), 2);
            assertEquals("saved-fixture", reader.read("/api/v1/mobile/portfolio")
                .getJSONObject("body").getString("revision_id"));
            views.save("/api/v1/mobile/ranking/20d", new JSONObject().put("status", 200)
                .put("body", new JSONObject().put("id", "saved-ranking")), 3);
            assertEquals("saved-ranking", reader.read("/api/v1/mobile/ranking/20d")
                .getJSONObject("body").getString("id"));
            assertTrue(SavedReadViews.allowed("/api/v1/mobile/ranking/5d"));
            assertFalse(SavedReadViews.allowed("/api/v1/mobile/ranking/20d/export"));
            reader.clear();
            assertFalse(views.read("/api/v1/home").getBoolean("available"));
            assertFalse(views.read("/api/v1/mobile/portfolio").getBoolean("available"));
        } finally { views.clear(); new File(database.getPath() + ".readviews").delete(); }
    }
    @Test public void encryptedHistoricalViewsRejectTamperingAndWrongPaths() throws Exception {
        File dir = new File(InstrumentationRegistry.getInstrumentation().getTargetContext().getCacheDir(), "read-view-test-" + System.nanoTime());
        SavedReadViews views = new SavedReadViews(dir);
        try {
            assertFalse(views.read("/api/v1/home").getBoolean("available"));
            views.save("/api/v1/home", new JSONObject().put("status", 200).put("body", new JSONObject().put("fixture", "private-fixture")), 9);
            assertTrue(new SavedReadViews(dir).read("/api/v1/home").getBoolean("readOnly"));
            File[] files = dir.listFiles(); assertNotNull(files); assertEquals(1, files.length);
            byte[] bytes = Files.readAllBytes(files[0].toPath());
            assertFalse(new String(bytes, java.nio.charset.StandardCharsets.UTF_8).contains("private-fixture"));
            bytes[bytes.length - 1] ^= 1; Files.write(files[0].toPath(), bytes);
            try { views.read("/api/v1/home"); fail("Corrupt display accepted"); } catch (javax.crypto.AEADBadTagException expected) { }
            try { views.read("/api/v1/home?other=1"); fail("Unknown path accepted"); } catch (IllegalArgumentException expected) { }
            views.clear(); assertFalse(views.read("/api/v1/home").getBoolean("available"));
        } finally { views.clear(); dir.delete(); }
    }

    @Test public void slowDecryptionDoesNotHoldLockAndClearInvalidatesItsResult() throws Exception {
        File dir = new File(InstrumentationRegistry.getInstrumentation().getTargetContext().getCacheDir(), "slow-read-" + System.nanoTime());
        java.util.concurrent.CountDownLatch entered = new java.util.concurrent.CountDownLatch(1), release = new java.util.concurrent.CountDownLatch(1);
        List<Runnable> jobs = new ArrayList<>();
        SavedReadViews views = new SavedReadViews(dir, jobs::add, bytes -> {
            entered.countDown();
            if (!release.await(10, java.util.concurrent.TimeUnit.SECONDS)) throw new IllegalStateException("TEST_TIMEOUT");
            return LocalStateStore.decrypt(bytes);
        });
        java.util.concurrent.ExecutorService reader = java.util.concurrent.Executors.newSingleThreadExecutor();
        java.util.concurrent.ExecutorService control = java.util.concurrent.Executors.newSingleThreadExecutor();
        try {
            views.save("/api/v1/home", new JSONObject().put("status", 200).put("body", new JSONObject().put("id", "before")), 1);
            java.util.concurrent.Future<com.getcapacitor.JSObject> pending = reader.submit(() -> views.read("/api/v1/home"));
            assertTrue(entered.await(10, java.util.concurrent.TimeUnit.SECONDS));
            java.util.concurrent.Future<?> clear = control.submit(() -> {
                views.saveAsync("/api/v1/today", "{}", 1);
                views.clear();
            });
            clear.get(2, java.util.concurrent.TimeUnit.SECONDS);
            release.countDown();
            assertFalse("Decrypted copy from before clear must not be returned", pending.get(10, java.util.concurrent.TimeUnit.SECONDS).getBoolean("available"));
            jobs.remove(0).run();
            assertFalse(views.read("/api/v1/today").getBoolean("available"));
        } finally {
            release.countDown(); reader.shutdownNow(); control.shutdownNow(); views.clear(); dir.delete();
        }
    }

    @Test public void replacementWhileDecryptingCannotPublishThePreviousView() throws Exception {
        File dir = new File(InstrumentationRegistry.getInstrumentation().getTargetContext().getCacheDir(), "replace-read-" + System.nanoTime());
        java.util.concurrent.CountDownLatch entered = new java.util.concurrent.CountDownLatch(1), release = new java.util.concurrent.CountDownLatch(1);
        List<Runnable> jobs = new ArrayList<>();
        SavedReadViews views = new SavedReadViews(dir, jobs::add, bytes -> {
            entered.countDown();
            if (!release.await(10, java.util.concurrent.TimeUnit.SECONDS)) throw new IllegalStateException("TEST_TIMEOUT");
            return LocalStateStore.decrypt(bytes);
        });
        java.util.concurrent.ExecutorService reader = java.util.concurrent.Executors.newSingleThreadExecutor();
        try {
            views.save("/api/v1/home", new JSONObject().put("status", 200).put("body", new JSONObject().put("id", "old")), 1);
            java.util.concurrent.Future<com.getcapacitor.JSObject> pending = reader.submit(() -> views.read("/api/v1/home"));
            assertTrue(entered.await(10, java.util.concurrent.TimeUnit.SECONDS));
            views.saveAsync("/api/v1/home", new JSONObject().put("status", 200).put("body", new JSONObject().put("id", "new")).toString(), 2);
            jobs.remove(0).run();
            release.countDown();
            assertFalse("An older decrypted view cannot overwrite the new one", pending.get(10, java.util.concurrent.TimeUnit.SECONDS).getBoolean("available"));
            assertEquals("new", views.read("/api/v1/home").getJSONObject("body").getString("id"));
        } finally {
            release.countDown(); reader.shutdownNow(); views.clear(); dir.delete();
        }
    }
}
