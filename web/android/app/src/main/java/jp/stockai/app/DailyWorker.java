package jp.stockai.app;

import android.content.Context;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import androidx.core.app.NotificationCompat;
import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import androidx.work.ForegroundInfo;
import com.getcapacitor.JSObject;
import java.time.Instant;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.json.JSONObject;

/** WorkManager persists requests across process loss/reboot; page receipts persist each slice. */
public final class DailyWorker extends Worker {
    private CompletableFuture<JSObject> activeCore;
    public DailyWorker(@NonNull Context context, @NonNull WorkerParameters parameters) { super(context, parameters); }

    private JSObject coreRequest(LocalComputeOwner owner, String method, String path, String body) throws Exception {
        CompletableFuture<JSObject> request;
        synchronized (this) {
            if (isStopped()) throw new InterruptedException();
            request = owner.request(method, path, body); activeCore = request;
        }
        try { return request.get(660, TimeUnit.SECONDS); }
        catch (InterruptedException | TimeoutException error) { request.cancel(true); throw error; }
        finally { synchronized (this) { if (activeCore == request) activeCore = null; } }
    }

    @Override public void onStopped() {
        super.onStopped();
        synchronized (this) { if (activeCore != null) activeCore.cancel(true); }
    }

    static final class ForegroundUnavailable extends Exception {
        final boolean acquisition;
        ForegroundUnavailable() { this(false); }
        ForegroundUnavailable(boolean acquisition) { this.acquisition = acquisition; }
    }

    static boolean requiresForeground(String phase) {
        return phase.equals("history") || phase.equals("membership")
            || phase.equals("calculating") || phase.equals("deciding");
    }

    static ForegroundInfo foregroundInfo(Context context, String phase) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("stockai-compute", "データ取得・計算", NotificationManager.IMPORTANCE_LOW));
        Intent open = new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pending = PendingIntent.getActivity(context, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        android.app.Notification notice = new NotificationCompat.Builder(context, "stockai-compute")
            .setSmallIcon(R.drawable.ic_stat_stockai).setContentTitle("StockAI")
            .setContentText(phase.equals("history") || phase.equals("membership")
                ? "市場データを取得・保存しています。アプリから停止できます。"
                : "端末内のデータを計算・保存しています。アプリから停止できます。")
            .setContentIntent(pending).setOnlyAlertOnce(true).setOngoing(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).build();
        return android.os.Build.VERSION.SDK_INT >= 29
            ? new ForegroundInfo(6102, notice, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            : new ForegroundInfo(6102, notice);
    }

    void beginForeground(String phase) throws InterruptedException, ForegroundUnavailable {
        try { setForegroundAsync(foregroundInfo(getApplicationContext(), phase)).get(30, TimeUnit.SECONDS); }
        catch (InterruptedException error) { throw error; }
        catch (Exception error) { throw new ForegroundUnavailable(phase.equals("history") || phase.equals("membership")); }
    }

    @NonNull @Override public Result doWork() {
        synchronized (DailyAutomation.RUN_LOCK) {
            DailyAutomation journal = null; String token = null;
            try {
                Context context = getApplicationContext();
                LocalComputeOwner owner = LocalComputeOwner.get(context);
                journal = new DailyAutomation(context, owner.state.database);
                JSONObject state = journal.row();
                if (!state.optBoolean("enabled") || isStopped() || state.optString("state").equals("credentials")) return Result.success();
                if (!state.isNull("retryAt") && Instant.now().isBefore(Instant.parse(state.getString("retryAt")))) return Result.success();
                token = state.getString("token");
                final DailyAutomation durable = journal; final String session = token;
                java.util.function.BooleanSupplier stopped = () -> {
                    try { return isStopped() || !durable.active(session); }
                    catch (Exception ignored) { return true; }
                };
                MarketClient client = new MarketClient(context, owner.state.database);
                DailyPipeline pipeline = new DailyPipeline(
                    (method, path, body) -> coreRequest(owner, method, path, body),
                    new DailyPipeline.Market() {
                        public JSONObject fetch(boolean membership, String day, java.util.function.BooleanSupplier stop) throws Exception {
                            return client.download(membership).fetch(day, 4, stop);
                        }
                        public void acknowledge(boolean membership, String day, String id) throws Exception { client.download(membership).acknowledge(day, id); }
                    }, new DailyPipeline.Progress() {
                        public void state(String value, String day) throws Exception {
                            if (requiresForeground(value)) beginForeground(value);
                            durable.state(session, value, day);
                        }
                        public void notice(String key, String text) throws Exception { durable.notice(session, key, text); }
                    }, stopped, Instant::now);
                boolean more = pipeline.tick(state.getString("firstDay"));
                if (!more && !stopped.getAsBoolean() && durable.row().optString("state").equals("numerical_saved")) {
                    ChatGPTClient chatgpt = ChatGPTClient.get(context);
                    NativeSecrets secrets = new NativeSecrets(context);
                    DailyResearch research = new DailyResearch(
                        (method, path, body) -> coreRequest(owner, method, path, body),
                        new DailyResearch.Provider() {
                            public JSONObject selection() throws Exception { return chatgpt.researchSelection(); }
                            public JSONObject respond(String id, String request, String hash, String model, String effort) throws Exception {
                                return chatgpt.respond(id, request, hash, model, effort).get(340, TimeUnit.SECONDS);
                            }
                            public JSONObject recover(String id) throws Exception { return new ResearchJournal(context).recover(id); }
                            public void acknowledge(String id) throws Exception { new ResearchJournal(context).acknowledge(id); }
                        }, new DailyResearch.Journal() {
                            public JSONObject read(String day) throws Exception {
                                String saved = secrets.read("daily-research-" + day); return saved == null ? null : new JSONObject(saved);
                            }
                            public void write(String day, JSONObject value) throws Exception { secrets.write("daily-research-" + day, value.toString()); }
                        }, new DailyPipeline.Progress() {
                            public void state(String value, String day) throws Exception { durable.state(session, value, day); }
                            public void notice(String key, String text) throws Exception { durable.notice(session, key, text); }
                        }, stopped, Instant::now);
                    more = research.step();
                }
                if (more && !stopped.getAsBoolean()) journal.continueAfterSlice();
                return Result.success();
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt(); return Result.retry();
            } catch (Exception error) {
                try {
                    if (journal != null && token != null && !isStopped()) {
                        if (error instanceof ForegroundUnavailable) {
                            journal.failed(token, false, Instant.now());
                            journal.state(token, ((ForegroundUnavailable) error).acquisition ? "history_wait" : "compute_wait", java.time.LocalDate.now(DailyPipeline.JST).toString());
                            journal.notice(token, java.time.LocalDate.now(DailyPipeline.JST) + ":compute", "Androidでバックグラウンド処理を開始できません。アプリを開いて保存状態を確認してください。");
                        } else if (error instanceof DailyPipeline.CoreFailure) {
                            journal.state(token, "inputs", java.time.LocalDate.now(DailyPipeline.JST).toString());
                            journal.notice(token, java.time.LocalDate.now(DailyPipeline.JST) + ":inputs", "保存内容を確認できません。本人設定と取得情報を確認してください。");
                        } else {
                            journal.failed(token, error instanceof DailyPipeline.ProviderFailure && ((DailyPipeline.ProviderFailure) error).credentials, Instant.now());
                            journal.notice(token, java.time.LocalDate.now(DailyPipeline.JST) + ":network", "自動処理を中断しました。保存済みの続きから再開できます。");
                        }
                    }
                } catch (Exception ignored) { /* No credential or provider payload is logged. */ }
                return Result.success(); // Bounded persisted retry via the periodic wake-up.
            }
        }
    }
}
