package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.Build;
import android.util.Log;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.getcapacitor.JSObject;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Assume;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Controller-only actual SQLite baseline. Never constructs a giant test input String. */
@RunWith(AndroidJUnit4.class)
public class FullHistoryCapacityTest {
    Context context;
    LocalComputeOwner owner;
    File database;
    long started;
    long characters;
    String expectedDigest;
    JSONObject portfolio;
    JSONObject portable;
    File portableFile;

    @Before public void disposableEmulatorOnly() throws Exception {
        var args = InstrumentationRegistry.getArguments();
        Assume.assumeTrue("Use the isolated full-history controller",
            "fresh-emulator-only".equals(args.getString("stockai.history.confirm")));
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertEquals("jp.stockai.app.debug", context.getPackageName());
        assertEquals(35, Build.VERSION.SDK_INT);
        assertTrue((context.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0);
        assertTrue(Build.HARDWARE.contains("ranchu") || Build.HARDWARE.contains("goldfish"));
        characters = Long.parseLong(args.getString("stockai.history.characters"));
        expectedDigest = args.getString("stockai.history.sha256");
        assertTrue(characters >= 90000000 && characters <= LocalStateStore.MAX_CHARACTERS);
        assertTrue(expectedDigest.matches("[a-f0-9]{64}"));
        database = File.createTempFile("stockai-full-history-", ".sqlite3", context.getCacheDir());
        owner = LocalComputeOwner.get(context, database);
        started = System.nanoTime();
    }

    void phase(String value) throws Exception {
        JSONObject evidence = new JSONObject().put("synthetic_only", true).put("phase", value)
            .put("characters", characters).put("max_java_heap_bytes", Runtime.getRuntime().maxMemory())
            .put("generation", owner.state.currentGeneration())
            .put("elapsed_seconds", (System.nanoTime() - started) / 1000000000.0);
        if (portfolio != null) evidence.put("portfolio", portfolio);
        if (portable != null) evidence.put("portable_backup", portable);
        try (FileOutputStream output = new FileOutputStream(new File(context.getFilesDir(), "native-history-proof.json"))) {
            output.write(evidence.toString().getBytes(StandardCharsets.UTF_8));
        }
        Log.i("StockAIHistoryCapacity", evidence.toString());
    }

    static <T> T result(CompletableFuture<T> value) throws Exception {
        return value.get(180, TimeUnit.SECONDS);
    }

    void seedEncryptedFixture() throws Exception {
        File input = new File(context.getFilesDir(), "native-history-input.b64");
        assertEquals(characters, input.length());
        Method encrypt = LocalStateStore.class.getDeclaredMethod("encryptChunk", String.class, long.class, int.class);
        encrypt.setAccessible(true);
        byte[] buffer = new byte[LocalStateStore.CHUNK_CHARACTERS];
        MessageDigest hash = MessageDigest.getInstance("SHA-256");
        long length = 0;
        int index = 0;
        SQLiteDatabase db = owner.state.database;
        assertEquals(0, owner.state.currentGeneration());
        db.beginTransaction();
        try (FileInputStream source = new FileInputStream(input)) {
            while (true) {
                int count = 0;
                while (count < buffer.length) {
                    int read = source.read(buffer, count, buffer.length - count);
                    if (read < 0) break;
                    count += read;
                }
                if (count == 0) break;
                length += count;
                assertTrue(length <= characters);
                hash.update(buffer, 0, count);
                String fragment = new String(buffer, 0, count, StandardCharsets.UTF_8);
                assertEquals(count, fragment.length());
                byte[] encrypted = (byte[]) encrypt.invoke(null, fragment, 1L, index);
                db.execSQL("INSERT INTO state_chunks(piece,payload) VALUES(?,?)", new Object[]{index++, encrypted});
            }
            assertEquals(characters, length);
            assertEquals(expectedDigest, LocalStateStore.hex(hash.digest()));
            JSONObject envelope = new JSONObject().put("length", length).put("chunks", index).put("sha256", expectedDigest);
            db.execSQL("INSERT INTO state(id,generation,payload) VALUES(1,1,?)",
                new Object[]{LocalStateStore.encrypt(LocalStateStore.FORMAT + envelope)});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    void exportEncryptedChunks() throws Exception {
        // Bounded test export avoids attributing a second giant test-only byte[] to the owner.
        Method decrypt = LocalStateStore.class.getDeclaredMethod("decryptChunk", byte[].class, long.class, int.class);
        decrypt.setAccessible(true);
        SQLiteDatabase db = owner.state.database;
        db.beginTransactionNonExclusive();
        try (FileOutputStream output = new FileOutputStream(new File(context.getFilesDir(), "native-history-export.b64"))) {
            long generation;
            JSONObject envelope;
            try (Cursor row = db.rawQuery("SELECT generation,payload FROM state WHERE id=1", null)) {
                assertTrue(row.moveToFirst());
                generation = row.getLong(0);
                String value = LocalStateStore.decrypt(row.getBlob(1));
                assertTrue(value.startsWith(LocalStateStore.FORMAT));
                envelope = new JSONObject(value.substring(LocalStateStore.FORMAT.length()));
            }
            MessageDigest hash = MessageDigest.getInstance("SHA-256");
            int index = 0;
            long length = 0;
            try (Cursor rows = db.rawQuery("SELECT piece,payload FROM state_chunks ORDER BY piece", null)) {
                while (rows.moveToNext()) {
                    assertEquals(index, rows.getInt(0));
                    String fragment = (String) decrypt.invoke(null, rows.getBlob(1), generation, index++);
                    byte[] bytes = fragment.getBytes(StandardCharsets.UTF_8);
                    assertEquals(fragment.length(), bytes.length);
                    hash.update(bytes); output.write(bytes); length += bytes.length;
                }
            }
            assertEquals(envelope.getLong("length"), length);
            assertEquals(envelope.getInt("chunks"), index);
            assertEquals(envelope.getString("sha256"), LocalStateStore.hex(hash.digest()));
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    @Test public void fullHistoryRestoresCommitsAndSurvivesOwnerRecreation() throws Exception {
        phase("seeding"); seedEncryptedFixture(); phase("seeded");
        phase("initializing-owner");
        JSObject health = result(owner.request("GET", "/api/v1/health", "null"));
        assertEquals(200, health.getInt("status"));
        assertFalse(health.getJSONObject("body").getBoolean("orderSubmissionAvailable"));
        phase("owner-initialized");
        JSObject market = result(owner.request("GET", "/api/v1/mobile/market", "null"));
        assertEquals(200, market.getInt("status"));
        String dates = market.getJSONObject("body").getJSONArray("completed_dates").toString();
        assertEquals(520, market.getJSONObject("body").getJSONArray("completed_dates").length());
        phase("committing-profile");
        JSObject saved = result(owner.request("POST", "/api/v1/mobile/portfolio", LocalComputeOwnerTest.emptyProfile()));
        assertEquals(200, saved.getInt("status"));
        portfolio = saved.getJSONObject("body"); phase("profile-committed");
        result(owner.closeForTest()); owner = LocalComputeOwner.get(context, database);
        phase("recreating-owner");
        assertEquals(portfolio.toString(), result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
        assertEquals(dates, result(owner.request("GET", "/api/v1/mobile/market", "null")).getJSONObject("body").getJSONArray("completed_dates").toString());
        phase("owner-recreated");
        portableFile = File.createTempFile("stockai-history-portable-", ".stockaib", context.getCacheDir());
        phase("exporting-portable-backup");
        result(owner.exportBackup("synthetic-history-password", () -> new FileOutputStream(portableFile)));
        portable = new JSONObject().put("format", "STOCKAIB1").put("envelope_bytes", portableFile.length());
        assertTrue(portableFile.length() > 90000000 && portableFile.length() <= BackupCrypto.MAX_ENVELOPE_BYTES);
        phase("portable-backup-exported");
        JSObject changed = result(owner.request("POST", "/api/v1/mobile/portfolio", LocalComputeOwnerTest.revisedProfile(saved).toString()));
        assertEquals(200, changed.getInt("status")); assertNotEquals(portfolio.toString(), changed.getJSONObject("body").toString());
        phase("preparing-portable-restore");
        long beforePreview = owner.state.currentGeneration();
        JSObject preview = result(owner.previewBackup("synthetic-history-password", () -> new FileInputStream(portableFile)));
        assertEquals(beforePreview, owner.state.currentGeneration());
        assertEquals(2, preview.length()); assertFalse(preview.has("payload"));
        portable.put("characters", preview.getInt("characters")).put("native_preview_payload_absent", true);
        phase("portable-preview-authenticated");
        result(owner.restoreBackup(preview.getString("token")));
        assertEquals(portfolio.toString(), result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
        portable.put("profile_recovered", true); phase("portable-backup-restored");
        result(owner.closeForTest()); owner = LocalComputeOwner.get(context, database);
        assertEquals(portfolio.toString(), result(owner.request("GET", "/api/v1/mobile/portfolio", "null")).getJSONObject("body").toString());
        assertEquals(dates, result(owner.request("GET", "/api/v1/mobile/market", "null")).getJSONObject("body").getJSONArray("completed_dates").toString());
        portable.put("status", "restored"); phase("restored-owner-recreated");
        exportEncryptedChunks(); phase("verified");
    }

    @After public void closeIsolatedOwner() throws Exception {
        if (owner != null) owner.closeForTest().get(15, TimeUnit.SECONDS);
        if (database != null) SQLiteDatabase.deleteDatabase(database);
        if (portableFile != null) portableFile.delete();
    }
}
