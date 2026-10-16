package jp.stockai.app;

import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import java.time.Instant;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** WorkManager persists requests across process loss/reboot; page receipts persist each slice. */
public final class DailyWorker extends Worker {
    public DailyWorker(@NonNull Context context, @NonNull WorkerParameters parameters) { super(context, parameters); }

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
                    (method, path, body) -> owner.request(method, path, body).get(660, TimeUnit.SECONDS),
                    new DailyPipeline.Market() {
                        public JSONObject fetch(boolean membership, String day, java.util.function.BooleanSupplier stop) throws Exception {
                            return client.download(membership).fetch(day, 4, stop);
                        }
                        public void acknowledge(boolean membership, String day, String id) throws Exception { client.download(membership).acknowledge(day, id); }
                    }, new DailyPipeline.Progress() {
                        public void state(String value, String day) throws Exception { durable.state(session, value, day); }
                        public void notice(String key, String text) throws Exception { durable.notice(session, key, text); }
                    }, stopped, Instant::now);
                boolean more = pipeline.tick(state.getString("firstDay"));
                if (more && !stopped.getAsBoolean()) journal.continueAfterSlice();
                return Result.success();
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt(); return Result.retry();
            } catch (Exception error) {
                try {
                    if (journal != null && token != null && !isStopped()) {
                        if (error instanceof DailyPipeline.CoreFailure) {
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
