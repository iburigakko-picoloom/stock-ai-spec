package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import android.database.sqlite.SQLiteDatabase;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.work.Configuration;
import androidx.work.WorkManager;
import androidx.work.testing.WorkManagerTestInitHelper;
import java.io.File;
import java.time.Instant;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class DailyAutomationTest {
    Context context;
    File file;
    SQLiteDatabase db;
    DailyAutomation journal;
    @Before public void open() throws Exception {
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        file = File.createTempFile("daily-fixture-", ".sqlite3", context.getCacheDir());
        db = SQLiteDatabase.openOrCreateDatabase(file, null);
        journal = new DailyAutomation(context, db);
    }
    @After public void close() { if (db != null) db.close(); if (file != null) SQLiteDatabase.deleteDatabase(file); }

    @Test public void duplicateEnableAndReopenPreserveSessionAndStopInvalidatesOldWorker() throws Exception {
        journal.enable("2026-01-05"); String token = journal.row().getString("token");
        journal.enable("2026-01-06");
        assertEquals(token, journal.row().getString("token"));
        assertEquals("2026-01-05", journal.status().getString("firstDay"));
        db.close(); db = SQLiteDatabase.openOrCreateDatabase(file, null); journal = new DailyAutomation(context, db);
        assertTrue(journal.active(token));
        db.execSQL("UPDATE daily_automation SET enabled=0,token='stopped',state='paused' WHERE id=1");
        journal.state(token, "numerical_saved", "2026-01-06");
        assertFalse(journal.active(token));
        assertEquals("paused", journal.status().getString("state"));
        assertFalse(journal.status().has("token"));
    }
    @Test public void transientFailuresAreBoundedAndDeniedNotificationKeepsSavedResult() throws Exception {
        journal.enable("2026-01-05"); String token = journal.row().getString("token");
        Instant failed = Instant.parse("2026-01-06T02:31:00Z");
        for (int i = 0; i < 3; i++) journal.failed(token, false, failed);
        assertEquals(3, journal.row().getInt("failures"));
        assertEquals("2026-01-06T15:00:00Z", journal.status().getString("retryAt"));
        // Freshly installed target-36 app has no notification grant. This path
        // must not throw or change the durable calculation status.
        assertFalse(journal.status().getBoolean("notificationsEnabled"));
        journal.state(token, "numerical_saved", "2026-01-06");
        journal.notice(token, "fixture-complete", "fixture only");
        assertEquals("numerical_saved", journal.status().getString("state"));
        assertTrue(journal.row().isNull("notice"));
        journal.failed(token, true, failed.plusSeconds(86400));
        assertEquals("credentials", journal.status().getString("state"));
        assertEquals(1, journal.row().getInt("failures"));
    }
    @Test public void uniqueNetworkWorkDoesNotDuplicateAndCancellationPersists() throws Exception {
        WorkManagerTestInitHelper.initializeTestWorkManager(context, new Configuration.Builder().build());
        journal.enable("2026-01-05");
        journal.wake(); journal.wake();
        WorkManager manager = WorkManager.getInstance(context);
        assertEquals(1, manager.getWorkInfosForUniqueWork(DailyAutomation.PUMP).get().size());
        assertEquals(androidx.work.NetworkType.CONNECTED, DailyAutomation.connected().getRequiredNetworkType());
        String token = journal.row().getString("token");
        journal.stop();
        assertFalse(journal.active(token));
        assertTrue(manager.getWorkInfosForUniqueWork(DailyAutomation.PUMP).get().get(0).getState().isFinished());
        journal.wake();
        assertEquals(1, manager.getWorkInfosForUniqueWork(DailyAutomation.PUMP).get().size());
    }
}
