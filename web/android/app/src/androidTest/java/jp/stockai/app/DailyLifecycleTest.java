package jp.stockai.app;

import static org.junit.Assert.*;
import android.app.Activity;
import android.app.NotificationManager;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.Build;
import android.util.AtomicFile;
import android.util.Base64;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;
import java.util.UUID;
import java.util.List;
import java.util.concurrent.Future;
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
    Object owner, state;
    SQLiteDatabase database;
    ClassLoader applicationLoader;
    static final ZoneId JST = ZoneId.of("Asia/Tokyo");
    File marker;
    String phase;

    @Before public void disposableEmulatorOnly() throws Exception {
        var args = InstrumentationRegistry.getArguments();
        Assume.assumeTrue("Run only through the isolated lifecycle controller",
            "fresh-emulator-only".equals(args.getString("stockai.lifecycle.confirm")));
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertEquals("jp.stockai.app.debug", context.getPackageName());
        assertEquals(35, Build.VERSION.SDK_INT);
        assertTrue((context.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0);
        assertTrue(Build.HARDWARE.contains("ranchu") || Build.HARDWARE.contains("goldfish"));
        phase = args.getString("stockai.lifecycle.phase");
        assertTrue("process".equals(phase) || "reboot".equals(phase) || "force-stop".equals(phase));
        marker = new File(context.getFilesDir(), "lifecycle-proof.json");
        applicationLoader = context.getClassLoader();
        owner = call(type("LocalComputeOwner"), "get", context);
        state = field(owner, "state"); database = (SQLiteDatabase) field(state, "database");
        assertTrue("Provider credentials must be absent", call(type("MarketClient"), "apiKey", context) == null);
        String account = (String) call(construct(type("NativeSecrets"), context), "read", "session-v2");
        assertTrue(account == null || new JSONObject(account).isNull("credentials"));
        assertFalse(context.getSystemService(NotificationManager.class).areNotificationsEnabled());
    }

    // no-restart instrumentation has a different runtime package/class loader.
    // Resolve application internals (including WorkManager's singleton) through
    // its existing loader. This bridge exists only in the test APK; production
    // visibility, transport and scheduler remain unchanged.
    Class<?> type(String name) throws Exception { return applicationLoader.loadClass(name.contains(".") ? name : "jp.stockai.app." + name); }
    static boolean accepts(Class<?>[] parameters, Object[] arguments) {
        if (parameters.length != arguments.length) return false;
        for (int i = 0; i < parameters.length; i++) {
            Class<?> wanted = parameters[i]; Object argument = arguments[i];
            if (wanted == long.class) wanted = Long.class;
            if (wanted == int.class) wanted = Integer.class;
            if (wanted == boolean.class) wanted = Boolean.class;
            if (argument == null ? parameters[i].isPrimitive() : !wanted.isInstance(argument)) return false;
        }
        return true;
    }
    static Object call(Object target, String name, Object... arguments) throws Exception {
        Class<?> owner = target instanceof Class<?> ? (Class<?>) target : target.getClass();
        for (Class<?> current = owner; current != null; current = current.getSuperclass())
            for (var method : current.getDeclaredMethods()) if (method.getName().equals(name) && accepts(method.getParameterTypes(), arguments)) {
                method.setAccessible(true);
                try { return method.invoke(target instanceof Class<?> ? null : target, arguments); }
                catch (InvocationTargetException error) {
                    if (error.getCause() instanceof Exception) throw (Exception) error.getCause();
                    if (error.getCause() instanceof Error) throw (Error) error.getCause();
                    throw error;
                }
            }
        throw new NoSuchMethodException(owner.getName() + "." + name);
    }
    static Object construct(Class<?> type, Object... arguments) throws Exception {
        for (var constructor : type.getDeclaredConstructors()) if (accepts(constructor.getParameterTypes(), arguments)) {
            constructor.setAccessible(true); return constructor.newInstance(arguments);
        }
        throw new NoSuchMethodException(type.getName());
    }
    static Object field(Object target, String name) throws Exception {
        var member = (target instanceof Class<?> ? (Class<?>) target : target.getClass()).getDeclaredField(name);
        member.setAccessible(true); return member.get(target instanceof Class<?> ? null : target);
    }
    static Object await(Object future) throws Exception { return ((Future<?>) future).get(240, TimeUnit.SECONDS); }
    Object manager() throws Exception { return call(type("androidx.work.WorkManager"), "getInstance", context); }
    String workName(String name) throws Exception { return (String) field(type("DailyAutomation"), name); }
    Object keep(String name) throws Exception { return field(type("androidx.work." + name), "KEEP"); }
    Object automation() throws Exception { return construct(type("DailyAutomation"), context, database); }
    JSONObject automationRow(Object value) throws Exception { return (JSONObject) call(value, "row"); }

    static final String RESEARCH_BODY = "lifecycle fixture: must never be dispatched";
    static final String RESEARCH_MODEL = "fixture-model", RESEARCH_EFFORT = "high";
    static String researchDigest() throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte item : MessageDigest.getInstance("SHA-256").digest(RESEARCH_BODY.getBytes(StandardCharsets.UTF_8)))
            result.append(String.format(java.util.Locale.ROOT, "%02x", item & 0xff));
        return result.toString();
    }
    void prepareResearch(JSONObject proof) throws Exception {
        Object journal = construct(type("ResearchJournal"), context);
        JSONArray batches = proof.optJSONArray("research_batches");
        if (batches == null) { batches = new JSONArray(); proof.put("research_batches", batches); }
        JSONArray batch = new JSONArray();
        for (String state : new String[]{"running", "completed", "acknowledged"}) {
            String id = UUID.randomUUID().toString().replace("-", "");
            assertTrue(((JSONObject) call(journal, "begin", id, researchDigest(), RESEARCH_MODEL, RESEARCH_EFFORT)).getBoolean("dispatch"));
            if (!state.equals("running")) {
                call(journal, "complete", id, new JSONObject().put("id", "fixture-response-" + id).put("status", "completed"));
                call(journal, "release", id);
                if (state.equals("acknowledged")) call(journal, "acknowledge", id);
            }
            // Leave the running reservation active. Only actual process loss,
            // not a simulated release, may remove it before verification.
            batch.put(new JSONObject().put("id", id).put("initial_state", state)
                .put("receipt", call(journal, "current", id)));
        }
        batches.put(batch);
    }
    void verifyResearch(JSONObject proof) throws Exception {
        Object journal = construct(type("ResearchJournal"), context);
        Object client = call(type("ChatGPTClient"), "get", context);
        JSONArray batches = proof.getJSONArray("research_batches");
        int rejected = 0;
        for (int b = 0; b < batches.length(); b++) {
            JSONArray batch = batches.getJSONArray(b);
            for (int n = 0; n < batch.length(); n++) {
                JSONObject item = batch.getJSONObject(n), expected = new JSONObject(item.getJSONObject("receipt").toString());
                String id = item.getString("id");
                if (item.getString("initial_state").equals("running"))
                    expected.put("state", "interrupted").put("errorCode", "PROCESS_INTERRUPTED");
                // This deliberately invalid request body must never reach the
                // transport parser. No credentials or network fixture exists.
                for (int repeat = 0; repeat < 2; repeat++) {
                    JSONObject reused = (JSONObject) await(call(client, "respond", id, RESEARCH_BODY, researchDigest(), RESEARCH_MODEL, RESEARCH_EFFORT));
                    assertEquals(expected.toString(), reused.toString());
                }
                for (int changed = 0; changed < 3; changed++) {
                    try {
                        await(call(client, "respond", id, RESEARCH_BODY,
                            changed == 0 ? new String(new char[64]).replace('\0', 'b') : researchDigest(),
                            changed == 1 ? "changed-fixture-model" : RESEARCH_MODEL,
                            changed == 2 ? "low" : RESEARCH_EFFORT));
                        fail("Changed research request reused an accepted reservation");
                    } catch (java.util.concurrent.ExecutionException error) {
                        assertEquals("ATTEMPT_REQUEST_CHANGED", error.getCause().getMessage()); rejected++;
                    }
                }
                assertEquals(expected.toString(), ((JSONObject) call(journal, "current", id)).toString());
                if (expected.getString("state").equals("completed")) {
                    call(journal, "acknowledge", id);
                    JSONObject acknowledged = (JSONObject) await(call(client, "respond", id, RESEARCH_BODY, researchDigest(), RESEARCH_MODEL, RESEARCH_EFFORT));
                    assertEquals("acknowledged", acknowledged.getString("state")); assertFalse(acknowledged.has("response"));
                    item.put("receipt", acknowledged);
                } else if (expected.getString("state").equals("acknowledged")) assertFalse(expected.has("response"));
            }
        }
        assertEquals(9 * batches.length(), rejected);
        proof.put("research_recovery", new JSONObject().put("batches", batches.length())
            .put("interrupted_reservations", batches.length()).put("retained_tombstones", 2 * batches.length())
            .put("changed_request_rejections", rejected).put("credentials_absent", true));
    }

    interface Remote { JSONObject fetch(String endpoint, String day, String cursor) throws Exception; }
    Object download(boolean membership, Remote remote) throws Exception {
        Class<?> contract = type("MarketDownload$Remote");
        Object proxy = Proxy.newProxyInstance(applicationLoader, new Class<?>[]{contract}, (object, method, arguments) -> {
            if (method.getName().equals("fetch")) return remote.fetch((String) arguments[0], (String) arguments[1], (String) arguments[2]);
            throw new UnsupportedOperationException(method.getName());
        });
        return construct(type("MarketDownload"), database, proxy, membership);
    }

    JSONObject api(String method, String path, JSONObject body) throws Exception {
        JSONObject result = (JSONObject) await(call(owner, "request", method, "/api/v1/" + path, body == null ? "null" : body.toString()));
        assertEquals("Local API status: " + path, 200, result.getInt("status")); return result;
    }
    JSONObject readMarker() throws Exception {
        return new JSONObject(new String(Files.readAllBytes(marker.toPath()), StandardCharsets.UTF_8));
    }
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
    Object closedDownload(boolean membership) throws Exception {
        return download(membership, (endpoint, day, cursor) -> {
            assertEquals("/markets/calendar", endpoint); return calendar(day, true, "");
        });
    }
    long count(String query, String... values) {
        try (Cursor cursor = database.rawQuery(query, values)) { assertTrue(cursor.moveToFirst()); return cursor.getLong(0); }
    }

    @Test public void prepare() throws Exception {
        JSONObject proof;
        Object automation = automation();
        if (phase.equals("process")) {
            assertFalse(marker.exists());
            assertTrue(api("GET", "mobile/portfolio", null).isNull("body"));
            assertEquals(0, api("GET", "mobile/market", null).getJSONObject("body").getJSONArray("completed_dates").length());
            assertEquals(0, api("GET", "mobile/models", null).getJSONObject("body").getInt("imported_bundle_count"));
            JSONObject profile = api("POST", "mobile/portfolio", new JSONObject("{\"schema_version\":\"manual-portfolio-v1\",\"holdings_status\":\"none\",\"investment_budget_yen\":null,\"maximum_drawdown_percent\":null,\"accounts\":[],\"holdings\":[]}")).getJSONObject("body");
            proof = new JSONObject().put("profile", profile).put("targets", new JSONArray());
            String partialDay = LocalDate.now(JST).minusDays(30).toString();
            Object partial = download(false, (endpoint, day, cursor) -> {
                if (endpoint.equals("/markets/calendar")) return calendar(day, false, "");
                assertEquals("/equities/master", endpoint); assertNull(cursor);
                return new JSONObject().put("status", 200).put("received_at", Instant.now().toString())
                    .put("body", new JSONObject().put("data", new JSONArray()).put("pagination_key", "fixture-next-page"));
            });
            JSONObject pending = (JSONObject) call(partial, "fetch", partialDay, 2, (java.util.function.BooleanSupplier) () -> false);
            assertEquals(202, pending.getInt("status"));
            proof.put("partial_day", partialDay).put("partial_id", pending.getString("acquisitionId"));
            // A real Activity uses and destroys its UI bridge before the worker
            // later runs. The computation owner must remain application-owned.
            var instrumentation = InstrumentationRegistry.getInstrumentation();
            Activity activity = instrumentation.startActivitySync(new Intent().setClassName(context, "jp.stockai.app.MainActivity")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
            instrumentation.runOnMainSync(activity::finish);
            for (int i = 0; i < 60 && !activity.isDestroyed(); i++) { instrumentation.waitForIdleSync(); Thread.sleep(50); }
            assertTrue(activity.isDestroyed()); proof.put("activity_destroyed", true);
        } else {
            proof = readMarker(); assertEquals("verified", proof.getString("stage"));
            assertFalse(automationRow(automation).optBoolean("enabled"));
        }
        JSONArray targets = proof.getJSONArray("targets");
        String day = (targets.length() == 0 ? LocalDate.now(JST)
            : LocalDate.parse(targets.getJSONObject(targets.length() - 1).getString("date"))).minusDays(1).toString();
        JSONObject receipt = (JSONObject) call(closedDownload(false), "fetch", day);
        assertEquals(200, receipt.getInt("status"));
        targets.put(new JSONObject().put("date", day).put("id", receipt.getString("acquisitionId"))
            .put("received_at", receipt.getString("received_at")).put("pages", receipt.getJSONArray("source_pages")));
        // This is a synthetic closed session, in the test APK only. Preserve
        // actual receipts even when today's alpha cutoff has already passed.
        JSONObject member = (JSONObject) call(closedDownload(true), "fetch", LocalDate.now(JST).toString());
        api("POST", "mobile/market/membership", member);
        call(closedDownload(true), "acknowledge", member.getString("date"), member.getString("acquisitionId"));
        if (automationRow(automation).has("firstDay")) database.execSQL("UPDATE daily_automation SET first_day=? WHERE id=1 AND enabled=0", new Object[]{day});
        call(automation, "enable", day);
        Object manager = manager();
        Object constraints = call(type("DailyAutomation"), "connected");
        Object requestBuilder = construct(type("androidx.work.OneTimeWorkRequest$Builder"), type("DailyWorker"));
        call(requestBuilder, "setConstraints", constraints); call(requestBuilder, "setInitialDelay", 60L, TimeUnit.SECONDS);
        Object request = call(requestBuilder, "build");
        Object watchBuilder = construct(type("androidx.work.PeriodicWorkRequest$Builder"), type("DailyWakeWorker"), 15L, TimeUnit.MINUTES);
        call(watchBuilder, "setConstraints", constraints); call(watchBuilder, "setInitialDelay", 60L, TimeUnit.SECONDS);
        Object watch = call(watchBuilder, "build");
        await(call(call(manager, "enqueueUniquePeriodicWork", workName("WATCH"), keep("ExistingPeriodicWorkPolicy"), watch), "getResult"));
        await(call(call(manager, "enqueueUniqueWork", workName("PUMP"), keep("ExistingWorkPolicy"), request), "getResult"));
        call(automation, "wake"); // Duplicate caller must keep the same pending request.
        long pending = 0;
        for (Object info : (List<?>) await(call(manager, "getWorkInfosForUniqueWork", workName("PUMP"))))
            if (!(Boolean) call(call(info, "getState"), "isFinished")) pending++;
        assertEquals(1, pending);
        JobInfo systemJob = null;
        String namespace = "androidx.work.systemjobscheduler";
        JobScheduler scheduler = context.getSystemService(JobScheduler.class).forNamespace(namespace);
        for (int i = 0; i < 40 && systemJob == null; i++) {
            for (JobInfo candidate : scheduler.getAllPendingJobs())
                if (call(request, "getId").toString().equals(candidate.getExtras().getString("EXTRA_WORK_SPEC_ID"))) {
                    assertNull(systemJob); systemJob = candidate;
                }
            if (systemJob == null) Thread.sleep(100);
        }
        assertNotNull("Original WorkRequest must be registered with the OS", systemJob);
        proof.put("phase", phase).put("stage", "prepared").put("pid", android.os.Process.myPid())
            .put("generation", call(state, "currentGeneration")).put("work_id", call(request, "getId").toString())
            .put("system_job", new JSONObject().put("namespace", namespace).put("id", systemJob.getId()))
            .put("watch_id", call(watch, "getId").toString()).put("prepared_at", Instant.now().toString());
        prepareResearch(proof);
        saveMarker(proof);
    }

    @Test public void verify() throws Exception {
        JSONObject proof = readMarker(); assertEquals(phase, proof.getString("phase")); assertEquals("prepared", proof.getString("stage"));
        Object manager = manager();
        Object result = null;
        for (int i = 0; i < 100; i++) {
            result = await(call(manager, "getWorkInfoById", UUID.fromString(proof.getString("work_id"))));
            if (result != null && (Boolean) call(call(result, "getState"), "isFinished")) break;
            Thread.sleep(200);
        }
        assertNotNull(result); assertEquals("SUCCEEDED", call(result, "getState").toString());
        Object watch = await(call(manager, "getWorkInfoById", UUID.fromString(proof.getString("watch_id"))));
        assertFalse((Boolean) call(call(watch, "getState"), "isFinished"));
        call(automation(), "stop"); // Stop later test slices before reading the shared facts.
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
        try (Cursor partial = database.rawQuery("SELECT endpoint,cursor FROM market_downloads WHERE id=?", new String[]{proof.getString("partial_id")})) {
            assertTrue(partial.moveToFirst()); assertEquals(1, partial.getInt(0)); assertEquals("fixture-next-page", partial.getString(1));
        }
        assertEquals(2, count("SELECT COUNT(*) FROM market_download_pages WHERE id=?", proof.getString("partial_id")));
        verifyOriginalReceipts(proof);
        verifyResearch(proof);
        assertTrue(api("GET", "mobile/daily", null).isNull("body"));
        assertTrue(api("GET", "mobile/decision", null).isNull("body"));
        assertFalse(api("GET", "health", null).getJSONObject("body").getBoolean("orderSubmissionAvailable"));
        proof.put("stage", "verified").put("verified_pid", android.os.Process.myPid())
            .put("verified_generation", call(state, "currentGeneration")).put("verified_at", Instant.now().toString());
        saveMarker(proof);
    }

    void verifyOriginalReceipts(JSONObject proof) throws Exception {
        String payload = ((JSONObject) await(call(owner, "readState"))).getString("payload");
        File copy = File.createTempFile("lifecycle-mobile-", ".sqlite3", context.getCacheDir());
        try {
            boolean found = false;
            try (ZipInputStream archive = new ZipInputStream(new ByteArrayInputStream(Base64.decode(payload, Base64.NO_WRAP)))) {
                java.util.zip.ZipEntry entry;
                while ((entry = archive.getNextEntry()) != null) if (entry.getName().equals("mobile.sqlite3")) {
                    ByteArrayOutputStream bytes = new ByteArrayOutputStream(); byte[] buffer = new byte[8192]; int count;
                    while ((count = archive.read(buffer)) != -1) {
                        if (bytes.size() + count > 2 * 1024 * 1024) throw new java.io.IOException("Fixture archive exceeds limit");
                        bytes.write(buffer, 0, count);
                    }
                    try (FileOutputStream output = new FileOutputStream(copy)) { output.write(bytes.toByteArray()); }
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
