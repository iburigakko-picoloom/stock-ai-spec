package jp.stockai.app;

import static org.junit.Assert.*;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.Build;
import android.util.AtomicFile;
import android.util.Base64;
import androidx.core.app.NotificationManagerCompat;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkInfo;
import androidx.work.WorkManager;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.Instant;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipInputStream;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Assume;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Controller-only disposable-emulator suite; included only in the test APK. */
@RunWith(AndroidJUnit4.class)
public class DailyLifecycleTest {
    Context context;
    LocalComputeOwner owner;
    File marker;
    String phase;

    @Before public void disposableEmulatorOnly() throws Exception {
        var args = InstrumentationRegistry.getArguments();
        Assume.assumeTrue("Run only through the isolated lifecycle controller",
            "fresh-emulator-only".equals(args.getString("stockai.lifecycle.confirm")));
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertEquals("jp.stockai.app.debug", context.getPackageName());
        assertTrue((context.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0);
        assertTrue(Build.HARDWARE.contains("ranchu") || Build.HARDWARE.contains("goldfish"));
        phase = args.getString("stockai.lifecycle.phase");
        assertTrue("process".equals(phase) || "reboot".equals(phase) || "force-stop".equals(phase));
        marker = new File(context.getFilesDir(), "lifecycle-proof.json");
        owner = LocalComputeOwner.get(context);
        assertTrue("Provider credentials must be absent", MarketClient.apiKey(context) == null);
        String account = new NativeSecrets(context).read("session-v2");
        assertTrue(account == null || new JSONObject(account).isNull("credentials"));
        assertFalse(NotificationManagerCompat.from(context).areNotificationsEnabled());
    }

    JSONObject api(String method, String path, JSONObject body) throws Exception {
        JSONObject result = owner.request(method, "/api/v1/" + path, body == null ? "null" : body.toString()).get(240, TimeUnit.SECONDS);
        assertEquals("Local API status: " + path, 200, result.getInt("status")); return result;
    }
    JSONObject readMarker() throws Exception { return new JSONObject(Files.readString(marker.toPath())); }
    void saveMarker(JSONObject value) throws Exception {
        AtomicFile atomic = new AtomicFile(marker);
        FileOutputStream output = atomic.startWrite();
        try { output.write(value.toString().getBytes(StandardCharsets.UTF_8)); atomic.finishWrite(output); }
        catch (Exception error) { atomic.failWrite(output); throw error; }
    }
    JSONObject calendar(String day, boolean closed, String next) throws Exception {
        return new JSONObject().put("status", 200).put("received_at", Instant.now().toString())
            .put("body", new JSONObject().put("data", new JSONArray().put(new JSONObject().put("Date", day)
                .put("HolDiv", closed ? "0" : "1"))).put("pagination_key", next));
    }
    MarketDownload closedDownload(boolean membership) {
        return new MarketDownload(owner.state.database, (endpoint, day, cursor) -> {
            assertEquals("/markets/calendar", endpoint); return calendar(day, true, "");
        }, membership);
    }
    long count(String query, String... values) {
        try (Cursor cursor = owner.state.database.rawQuery(query, values)) { assertTrue(cursor.moveToFirst()); return cursor.getLong(0); }
    }

    @Test public void prepare() throws Exception {
        JSONObject proof;
        DailyAutomation automation = new DailyAutomation(context, owner.state.database);
        if (phase.equals("process")) {
            assertFalse(marker.exists());
            assertTrue(api("GET", "mobile/portfolio", null).isNull("body"));
            assertEquals(0, api("GET", "mobile/market", null).getJSONObject("body").getJSONArray("completed_dates").length());
            assertEquals(0, api("GET", "mobile/models", null).getJSONObject("body").getInt("imported_bundle_count"));
            JSONObject profile = api("POST", "mobile/portfolio", new JSONObject(LocalComputeOwnerTest.emptyProfile())).getJSONObject("body");
            proof = new JSONObject().put("profile", profile).put("targets", new JSONArray());
            String partialDay = LocalDate.now(DailyPipeline.JST).minusDays(30).toString();
            MarketDownload partial = new MarketDownload(owner.state.database, (endpoint, day, cursor) -> {
                if (endpoint.equals("/markets/calendar")) return calendar(day, false, "");
                assertEquals("/equities/master", endpoint); assertNull(cursor);
                return new JSONObject().put("status", 200).put("received_at", Instant.now().toString())
                    .put("body", new JSONObject().put("data", new JSONArray()).put("pagination_key", "fixture-next-page"));
            });
            JSONObject pending = partial.fetch(partialDay, 2, () -> false);
            assertEquals(202, pending.getInt("status"));
            proof.put("partial_day", partialDay).put("partial_id", pending.getString("acquisitionId"));
            // A real Activity uses and destroys its UI bridge before the worker
            // later runs. The computation owner must remain application-owned.
            var instrumentation = InstrumentationRegistry.getInstrumentation();
            Activity activity = instrumentation.startActivitySync(new Intent(context, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
            instrumentation.runOnMainSync(activity::finish);
            for (int i = 0; i < 60 && !activity.isDestroyed(); i++) { instrumentation.waitForIdleSync(); Thread.sleep(50); }
            assertTrue(activity.isDestroyed()); proof.put("activity_destroyed", true);
        } else {
            proof = readMarker(); assertEquals("verified", proof.getString("stage"));
            assertFalse(automation.row().optBoolean("enabled"));
        }
        JSONArray targets = proof.getJSONArray("targets");
        String day = (targets.length() == 0 ? LocalDate.now(DailyPipeline.JST)
            : LocalDate.parse(targets.getJSONObject(targets.length() - 1).getString("date"))).minusDays(1).toString();
        JSONObject receipt = closedDownload(false).fetch(day);
        assertEquals(200, receipt.getInt("status"));
        targets.put(new JSONObject().put("date", day).put("id", receipt.getString("acquisitionId"))
            .put("received_at", receipt.getString("received_at")).put("pages", receipt.getJSONArray("source_pages")));
        // This is a synthetic closed session, in the test APK only. Preserve
        // actual receipts even when today's alpha cutoff has already passed.
        JSONObject member = closedDownload(true).fetch(LocalDate.now(DailyPipeline.JST).toString());
        api("POST", "mobile/market/membership", member);
        closedDownload(true).acknowledge(member.getString("date"), member.getString("acquisitionId"));
        if (automation.row().has("firstDay")) owner.state.database.execSQL("UPDATE daily_automation SET first_day=? WHERE id=1 AND enabled=0", new Object[]{day});
        automation.enable(day);
        WorkManager manager = WorkManager.getInstance(context);
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(DailyWorker.class).setConstraints(DailyAutomation.connected())
            .setInitialDelay(60, TimeUnit.SECONDS).build();
        PeriodicWorkRequest watch = new PeriodicWorkRequest.Builder(DailyWakeWorker.class, 15, TimeUnit.MINUTES)
            .setConstraints(DailyAutomation.connected()).setInitialDelay(60, TimeUnit.SECONDS).build();
        manager.enqueueUniquePeriodicWork(DailyAutomation.WATCH, ExistingPeriodicWorkPolicy.KEEP, watch).getResult().get(20, TimeUnit.SECONDS);
        manager.enqueueUniqueWork(DailyAutomation.PUMP, ExistingWorkPolicy.KEEP, request).getResult().get(20, TimeUnit.SECONDS);
        automation.wake(); // Duplicate caller must keep the same pending request.
        long pending = manager.getWorkInfosForUniqueWork(DailyAutomation.PUMP).get(20, TimeUnit.SECONDS).stream().filter(x -> !x.getState().isFinished()).count();
        assertEquals(1, pending);
        proof.put("phase", phase).put("stage", "prepared").put("pid", android.os.Process.myPid())
            .put("generation", owner.state.currentGeneration()).put("work_id", request.getId().toString())
            .put("watch_id", watch.getId().toString()).put("prepared_at", Instant.now().toString());
        saveMarker(proof);
    }

    @Test public void verify() throws Exception {
        JSONObject proof = readMarker(); assertEquals(phase, proof.getString("phase")); assertEquals("prepared", proof.getString("stage"));
        WorkManager manager = WorkManager.getInstance(context);
        WorkInfo result = null;
        for (int i = 0; i < 100; i++) {
            result = manager.getWorkInfoById(UUID.fromString(proof.getString("work_id"))).get(20, TimeUnit.SECONDS);
            if (result != null && result.getState().isFinished()) break;
            Thread.sleep(200);
        }
        assertNotNull(result); assertEquals(WorkInfo.State.SUCCEEDED, result.getState());
        assertFalse(manager.getWorkInfoById(UUID.fromString(proof.getString("watch_id"))).get(20, TimeUnit.SECONDS).getState().isFinished());
        DailyAutomation automation = new DailyAutomation(context, owner.state.database);
        automation.stop(); // Stop later test slices before reading the shared facts.
        assertTrue("Original personal revision changed", proof.getJSONObject("profile").toString()
            .equals(api("GET", "mobile/portfolio", null).getJSONObject("body").toString()));
        JSONArray acquisitions = api("GET", "mobile/market", null).getJSONObject("body").getJSONArray("committed_acquisitions");
        JSONArray targets = proof.getJSONArray("targets"); assertEquals(targets.length(), acquisitions.length());
        for (int i = 0; i < targets.length(); i++) {
            JSONObject target = targets.getJSONObject(i); boolean found = false;
            for (int n = 0; n < acquisitions.length(); n++) found |= target.getString("id").equals(acquisitions.getJSONObject(n).getString("acquisitionId"));
            assertTrue(found);
            assertEquals(0, count("SELECT COUNT(*) FROM market_download_pages WHERE id=?", target.getString("id")));
        }
        try (Cursor partial = owner.state.database.rawQuery("SELECT endpoint,cursor FROM market_downloads WHERE id=?", new String[]{proof.getString("partial_id")})) {
            assertTrue(partial.moveToFirst()); assertEquals(1, partial.getInt(0)); assertEquals("fixture-next-page", partial.getString(1));
        }
        assertEquals(2, count("SELECT COUNT(*) FROM market_download_pages WHERE id=?", proof.getString("partial_id")));
        verifyOriginalReceipts(proof);
        assertTrue(api("GET", "mobile/daily", null).isNull("body"));
        assertTrue(api("GET", "mobile/decision", null).isNull("body"));
        assertFalse(api("GET", "health", null).getJSONObject("body").getBoolean("orderSubmissionAvailable"));
        proof.put("stage", "verified").put("verified_pid", android.os.Process.myPid())
            .put("verified_generation", owner.state.currentGeneration()).put("verified_at", Instant.now().toString());
        saveMarker(proof);
    }

    void verifyOriginalReceipts(JSONObject proof) throws Exception {
        String payload = owner.readState().get(30, TimeUnit.SECONDS).getString("payload");
        File copy = File.createTempFile("lifecycle-mobile-", ".sqlite3", context.getCacheDir());
        try {
            boolean found = false;
            try (ZipInputStream archive = new ZipInputStream(new ByteArrayInputStream(Base64.decode(payload, Base64.NO_WRAP)))) {
                java.util.zip.ZipEntry entry;
                while ((entry = archive.getNextEntry()) != null) if (entry.getName().equals("mobile.sqlite3")) {
                    try (FileOutputStream output = new FileOutputStream(copy)) { output.write(StockAIPlugin.read(archive, 2 * 1024 * 1024)); }
                    found = true; break;
                }
            }
            assertTrue(found);
            try (SQLiteDatabase shared = SQLiteDatabase.openDatabase(copy.getAbsolutePath(), null, SQLiteDatabase.OPEN_READONLY)) {
                JSONArray targets = proof.getJSONArray("targets");
                for (int i = 0; i < targets.length(); i++) {
                    JSONObject target = targets.getJSONObject(i);
                    try (Cursor row = shared.rawQuery("SELECT received_at FROM market_days WHERE day=?", new String[]{target.getString("date")})) {
                        assertTrue(row.moveToFirst()); Instant original = Instant.parse(target.getString("received_at"));
                        Instant rounded = original.truncatedTo(ChronoUnit.MICROS).plusNanos(original.getNano() % 1000 == 0 ? 0 : 1000);
                        assertEquals(rounded, Instant.parse(row.getString(0)));
                    }
                    try (Cursor row = shared.rawQuery("SELECT source_pages FROM market_acquisitions WHERE id=?", new String[]{target.getString("id")})) {
                        assertTrue(row.moveToFirst()); JSONObject saved = new JSONArray(row.getString(0)).getJSONObject(0);
                        JSONObject original = target.getJSONArray("pages").getJSONObject(0);
                        assertEquals(original.getString("received_at"), saved.getString("received_at"));
                        assertEquals(original.getString("sha256"), saved.getString("sha256"));
                    }
                }
            }
        } finally { SQLiteDatabase.deleteDatabase(copy); }
    }
}
