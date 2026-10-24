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

    @Test public void acquisitionUsesPrivateOngoingForegroundNotice() {
        for (String phase : new String[]{"history", "membership", "calculating", "deciding"})
            assertTrue(DailyWorker.requiresForeground(phase));
        for (String phase : new String[]{"waiting_cutoff", "closed", "forecast_saved", "inputs"})
            assertFalse(DailyWorker.requiresForeground(phase));
        for (String phase : new String[]{"history", "membership"}) {
            android.app.Notification notice = DailyWorker.foregroundInfo(context, phase).getNotification();
            assertEquals("データを取得・保存中",
                notice.extras.getString(android.app.Notification.EXTRA_TEXT));
            assertEquals(android.app.Notification.VISIBILITY_PRIVATE, notice.visibility);
            assertTrue((notice.flags & android.app.Notification.FLAG_ONGOING_EVENT) != 0);
        }
    }

    @Test public void historyProgressIsOngoingAndDurableAcrossSlicesAndReopen() throws Exception {
        journal.enable("2026-01-05"); String token = journal.row().getString("token");
        journal.state(token, "history", "2026-01-05");
        android.app.Notification notice = DailyAutomation.progressNotification(context,
            DailyAutomation.progressText(true, "history"), "2026-01-05");
        assertTrue((notice.flags & android.app.Notification.FLAG_ONGOING_EVENT) != 0);
        assertEquals(0, notice.flags & android.app.Notification.FLAG_AUTO_CANCEL);
        assertTrue((notice.flags & android.app.Notification.FLAG_ONLY_ALERT_ONCE) != 0);
        assertEquals(android.app.Notification.VISIBILITY_PRIVATE, notice.visibility);
        assertTrue(notice.extras.getCharSequence(android.app.Notification.EXTRA_BIG_TEXT).toString().contains("2026-01-05"));
        assertEquals("stockai-history-progress", notice.getChannelId());
        // There is no Activity or next Worker here: persisted progress survives
        // the handoff. Denied notification permission cannot damage the journal.
        db.close(); db = SQLiteDatabase.openOrCreateDatabase(file, null);
        journal = new DailyAutomation(context, db); journal.refreshProgressNotice();
        assertEquals("history", journal.status().getString("state"));
        journal.state(token, "waiting_cutoff", "2026-01-06");
        assertNull(DailyAutomation.progressText(true, journal.status().getString("state")));
        db.execSQL("UPDATE daily_automation SET enabled=0,token='stopped',state='paused' WHERE id=1");
        journal.state(token, "history", "2026-01-06");
        assertEquals("paused", journal.status().getString("state"));
        assertNull(DailyAutomation.progressText(false, "history"));
    }

    @Test public void longCalculationNoticeAndMergedManifestDeclareDataSyncWithoutPrivateData() throws Exception {
        androidx.work.ForegroundInfo info = DailyWorker.foregroundInfo(context, "calculating");
        assertEquals(6102, info.getNotificationId());
        android.app.Notification notice = info.getNotification();
        assertEquals(android.app.Notification.VISIBILITY_PRIVATE, notice.visibility);
        assertTrue((notice.flags & android.app.Notification.FLAG_ONGOING_EVENT) != 0);
        assertEquals("StockAI", notice.extras.getString(android.app.Notification.EXTRA_TITLE));
        assertEquals("予測を計算・保存中",
            notice.extras.getString(android.app.Notification.EXTRA_TEXT));
        assertTrue(notice.extras.getBoolean(android.app.Notification.EXTRA_PROGRESS_INDETERMINATE));
        android.app.Notification deciding = DailyWorker.foregroundInfo(context, "deciding").getNotification();
        assertEquals("株数を判定・保存中", deciding.extras.getString(android.app.Notification.EXTRA_TEXT));
        assertTrue(deciding.extras.getBoolean(android.app.Notification.EXTRA_PROGRESS_INDETERMINATE));
        if (android.os.Build.VERSION.SDK_INT >= 29) {
            assertEquals(android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC, info.getForegroundServiceType());
            android.content.pm.ServiceInfo service = context.getPackageManager().getServiceInfo(
                new android.content.ComponentName(context, "androidx.work.impl.foreground.SystemForegroundService"), 0);
            assertEquals(android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC, service.getForegroundServiceType());
        }
        android.content.pm.PackageInfo installed = context.getPackageManager().getPackageInfo(context.getPackageName(),
            android.content.pm.PackageManager.GET_PERMISSIONS);
        java.util.List<String> permissions = java.util.Arrays.asList(installed.requestedPermissions);
        assertTrue(permissions.contains("android.permission.FOREGROUND_SERVICE"));
        assertTrue(permissions.contains("android.permission.FOREGROUND_SERVICE_DATA_SYNC"));
        // This verifies construction/declarations only. Actual OS admission and
        // Android 16 quota behavior still require separate device acceptance.
    }
}
