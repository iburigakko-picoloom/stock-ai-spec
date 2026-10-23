package jp.stockai.app;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** Durable opt-in and status. Contains no balances, credentials or provider responses. */
final class DailyAutomation {
    static final String PUMP = "stockai-daily-pump-v1", WATCH = "stockai-daily-watch-v1";
    static final Object RUN_LOCK = new Object();
    private static final Object STATE_LOCK = new Object();
    static final int PROGRESS_NOTIFICATION_ID = 6103;
    final Context context;
    final SQLiteDatabase db;

    DailyAutomation(Context context, SQLiteDatabase db) {
        this.context = context.getApplicationContext(); this.db = db;
        db.execSQL("CREATE TABLE IF NOT EXISTS daily_automation(id INTEGER PRIMARY KEY CHECK(id=1),token TEXT NOT NULL,enabled INTEGER NOT NULL,first_day TEXT NOT NULL,state TEXT NOT NULL,day TEXT,updated_at TEXT NOT NULL,notice TEXT,failures INTEGER NOT NULL,failure_day TEXT,retry_at TEXT)");
    }

    JSONObject row() throws Exception {
        synchronized (STATE_LOCK) {
            try (Cursor row = db.rawQuery("SELECT token,enabled,first_day,state,day,updated_at,notice,failures,failure_day,retry_at FROM daily_automation WHERE id=1", null)) {
                if (!row.moveToFirst()) return new JSONObject().put("enabled", false).put("state", "idle");
                return new JSONObject().put("token", row.getString(0)).put("enabled", row.getInt(1) != 0)
                    .put("firstDay", row.getString(2)).put("state", row.getString(3))
                    .put("day", row.isNull(4) ? JSONObject.NULL : row.getString(4)).put("updatedAt", row.getString(5))
                    .put("notice", row.isNull(6) ? JSONObject.NULL : row.getString(6)).put("failures", row.getInt(7))
                    .put("failureDay", row.isNull(8) ? JSONObject.NULL : row.getString(8))
                    .put("retryAt", row.isNull(9) ? JSONObject.NULL : row.getString(9));
            }
        }
    }

    JSONObject status() throws Exception {
        refreshProgressNotice();
        JSONObject result = row();
        for (String name : new String[]{"token", "notice", "failures", "failureDay"}) result.remove(name);
        return result.put("notificationsEnabled", NotificationManagerCompat.from(context).areNotificationsEnabled());
    }

    boolean active(String token) throws Exception {
        JSONObject current = row();
        return current.optBoolean("enabled") && token.equals(current.optString("token"));
    }

    void enable(String firstDay) throws Exception {
        synchronized (STATE_LOCK) {
            JSONObject prior = row();
            if (prior.optBoolean("enabled") && !prior.optString("state").equals("credentials")) return;
            String first = prior.has("firstDay") ? prior.getString("firstDay") : firstDay;
            LocalDate.parse(first);
            db.execSQL("INSERT OR REPLACE INTO daily_automation VALUES(1,?,1,?,'queued',NULL,?,NULL,0,NULL,NULL)",
                new Object[]{UUID.randomUUID().toString(), first, Instant.now().toString()});
            refreshProgressNotice();
        }
    }

    void start() throws Exception {
        if (MarketClient.apiKey(context) == null) throw new IllegalStateException("API_KEY_REQUIRED");
        JSONObject old = row();
        if (!old.has("firstDay")) {
            JSONObject response = LocalComputeOwner.get(context).request("GET", "/api/v1/mobile/market/plan", "null").get(180, TimeUnit.SECONDS);
            if (response.getInt("status") != 200) throw new IllegalStateException();
            JSONObject plan = response.optJSONObject("body");
            enable(plan == null ? LocalDate.now(ZoneId.of("Asia/Tokyo")).minusDays(420).toString() : plan.getString("first_day"));
        } else enable(old.getString("firstDay"));
        WorkManager manager = WorkManager.getInstance(context);
        manager.enqueueUniquePeriodicWork(WATCH, ExistingPeriodicWorkPolicy.KEEP,
            new PeriodicWorkRequest.Builder(DailyWakeWorker.class, 15, TimeUnit.MINUTES).setConstraints(connected()).build()).getResult().get();
        wake();
    }

    static Constraints connected() { return new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build(); }

    void wake() throws Exception {
        refreshProgressNotice();
        if (row().optBoolean("enabled")) WorkManager.getInstance(context).enqueueUniqueWork(PUMP, ExistingWorkPolicy.KEEP,
            new OneTimeWorkRequest.Builder(DailyWorker.class).setConstraints(connected()).build()).getResult().get();
    }

    void continueAfterSlice() throws Exception {
        if (row().optBoolean("enabled")) WorkManager.getInstance(context).enqueueUniqueWork(PUMP, ExistingWorkPolicy.APPEND_OR_REPLACE,
            new OneTimeWorkRequest.Builder(DailyWorker.class).setConstraints(connected()).setInitialDelay(5, TimeUnit.SECONDS).build()).getResult().get();
    }

    void stop() throws Exception {
        synchronized (STATE_LOCK) {
            db.execSQL("UPDATE daily_automation SET enabled=0,token=?,state='paused',updated_at=? WHERE id=1",
                new Object[]{UUID.randomUUID().toString(), Instant.now().toString()});
            refreshProgressNotice();
        }
        WorkManager manager = WorkManager.getInstance(context);
        manager.cancelUniqueWork(WATCH).getResult().get(); manager.cancelUniqueWork(PUMP).getResult().get();
    }

    void state(String token, String state, String day) throws Exception {
        synchronized (STATE_LOCK) {
            db.execSQL("UPDATE daily_automation SET state=?,day=?,updated_at=? WHERE id=1 AND enabled=1 AND token=?",
                new Object[]{state, day, Instant.now().toString(), token});
            refreshProgressNotice();
        }
    }

    void failed(String token, boolean credential, Instant now) throws Exception {
        synchronized (STATE_LOCK) {
            JSONObject current = row();
            if (!active(token)) return;
            String day = now.atZone(ZoneId.of("Asia/Tokyo")).toLocalDate().toString();
            int count = day.equals(current.optString("failureDay")) ? current.optInt("failures") + 1 : 1;
            Instant retry = count >= 3 ? now.atZone(ZoneId.of("Asia/Tokyo")).toLocalDate().plusDays(1).atStartOfDay(ZoneId.of("Asia/Tokyo")).toInstant() : now.plusSeconds(900L * count);
            db.execSQL("UPDATE daily_automation SET state=?,day=?,updated_at=?,failures=?,failure_day=?,retry_at=? WHERE id=1 AND enabled=1 AND token=?",
                new Object[]{credential ? "credentials" : "retry", day, now.toString(), count, day, retry.toString(), token});
            refreshProgressNotice();
        }
    }

    // Separate from WorkManager's foreground ID: that notification is removed
    // after each bounded day/page slice. This reflects durable work, not proof
    // that a network request is executing while Android postpones the next job.
    static String progressText(boolean enabled, String state) {
        if (!enabled) return null;
        switch (state) {
            case "queued": return "自動更新の開始待ち";
            case "history": return "履歴の取得・保存中／次の取得待ち";
            case "membership": return "銘柄一覧の取得・保存中／次の処理待ち";
            case "history_wait": return "履歴取得の再開待ち・Androidの実行待ち";
            case "retry": return "自動更新の再開待ち・通信状態などを確認してください";
            default: return null;
        }
    }

    static android.app.Notification progressNotification(Context context, String text, String day) {
        Intent open = new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pending = PendingIntent.getActivity(context, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String detail = day == null || day.isEmpty() ? text : text + "\n対象日：" + day;
        return new NotificationCompat.Builder(context, "stockai-history-progress")
            .setSmallIcon(R.drawable.ic_stat_stockai).setContentTitle("株AI・データ取得")
            .setContentText(text).setStyle(new NotificationCompat.BigTextStyle().bigText(detail))
            .setContentIntent(pending).setOnlyAlertOnce(true).setOngoing(true).setAutoCancel(false).setShowWhen(false)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).build();
    }

    void refreshProgressNotice() throws Exception {
        synchronized (STATE_LOCK) {
            JSONObject current = row();
            String text = progressText(current.optBoolean("enabled"), current.optString("state"));
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            if (text == null) { manager.cancel(PROGRESS_NOTIFICATION_ID); return; }
            manager.createNotificationChannel(new NotificationChannel("stockai-history-progress", "履歴取得の進捗", NotificationManager.IMPORTANCE_LOW));
            if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) return;
            if (android.os.Build.VERSION.SDK_INT >= 33 && androidx.core.content.ContextCompat.checkSelfPermission(context,
                    android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) return;
            try {
                boolean acquiring = current.optString("state").equals("history") || current.optString("state").equals("membership");
                manager.notify(PROGRESS_NOTIFICATION_ID, progressNotification(context, text,
                    acquiring && !current.isNull("day") ? current.optString("day") : null));
            } catch (SecurityException ignored) { /* Notification denial must not interrupt acquisition. */ }
        }
    }

    void notice(String token, String key, String text) throws Exception {
        synchronized (STATE_LOCK) {
            JSONObject current = row();
            if (!active(token) || key.equals(current.optString("notice"))) return;
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            manager.createNotificationChannel(new NotificationChannel("stockai-daily", "毎日の計算", NotificationManager.IMPORTANCE_DEFAULT));
            if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) return;
            if (android.os.Build.VERSION.SDK_INT >= 33 && androidx.core.content.ContextCompat.checkSelfPermission(context,
                    android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) return;
            Intent open = new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
            PendingIntent pending = PendingIntent.getActivity(context, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            try {
                NotificationManagerCompat.from(context).notify(6101, new NotificationCompat.Builder(context, "stockai-daily")
                    .setSmallIcon(R.drawable.ic_stat_stockai).setContentTitle("StockAI").setContentText(text)
                    .setContentIntent(pending).setAutoCancel(true).setVisibility(NotificationCompat.VISIBILITY_PRIVATE).build());
                db.execSQL("UPDATE daily_automation SET notice=? WHERE id=1 AND token=? AND enabled=1", new Object[]{key, token});
            } catch (SecurityException ignored) { /* Permission denial leaves the saved result intact. */ }
        }
    }
}
