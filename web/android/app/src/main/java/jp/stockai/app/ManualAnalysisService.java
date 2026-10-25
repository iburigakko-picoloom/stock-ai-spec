package jp.stockai.app;

import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import androidx.core.content.ContextCompat;
import com.getcapacitor.JSObject;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** A user-started analysis owns its notification and both saved stages, not the Activity. */
public final class ManualAnalysisService extends Service {
    private static final Object LOCK = new Object();
    private static Job active;
    private Job job;
    private PowerManager.WakeLock wake;
    private Thread thread;
    private volatile CompletableFuture<JSObject> core;
    private volatile LocalComputeOwner computeOwner;
    private JSObject savedResult;
    private Throwable savedError = new IllegalStateException("ANALYSIS_INTERRUPTED");
    private final Handler updates = new Handler(Looper.getMainLooper());
    private volatile String phase = "calculating";
    static boolean isRunning() { synchronized (LOCK) { return active != null; } }
    private final Runnable refresh = new Runnable() {
        public void run() {
            if (job == null || job.result.isDone()) return;
            try { foreground(phase); } catch (Exception ignored) { /* Computation owns error handling. */ }
            updates.postDelayed(this, 1000);
        }
    };

    static final class Job {
        final String id = UUID.randomUUID().toString();
        final String body;
        final CompletableFuture<JSObject> result = new CompletableFuture<>();
        Job(String body) { this.body = body; }
    }

    static boolean handles(String method, String path) {
        return "POST".equals(method) && "/api/v1/mobile/daily/generate".equals(path);
    }

    static CompletableFuture<JSObject> start(Context context, String body) {
        synchronized (LOCK) {
            if (active != null) {
                if (active.body.equals(body)) return active.result;
                CompletableFuture<JSObject> rejected = new CompletableFuture<>();
                rejected.completeExceptionally(new IllegalStateException("ANALYSIS_ALREADY_RUNNING"));
                return rejected;
            }
            Job next = new Job(body); active = next;
            new Handler(Looper.getMainLooper()).post(() -> {
                try {
                    ContextCompat.startForegroundService(context, new Intent(context, ManualAnalysisService.class).putExtra("job", next.id));
                } catch (Exception error) { finish(next, null, error); }
            });
            return next.result;
        }
    }

    private static void finish(Job expected, JSObject result, Throwable error) {
        synchronized (LOCK) {
            if (active == expected) active = null;
        }
        if (error == null) expected.result.complete(result);
        else expected.result.completeExceptionally(error);
    }

    interface Request { JSObject run(String path, String body) throws Exception; }
    interface Progress { void phase(String phase); }

    static JSObject run(String body, Request request, Progress progress) throws Exception {
        progress.phase("calculating");
        JSObject forecast = request.run("/api/v1/mobile/daily/generate", body);
        if (forecast.getInt("status") != 200 || new JSONObject(body).optBoolean("reference_only")) return forecast;
        progress.phase("deciding");
        JSObject decision = request.run("/api/v1/mobile/decision/generate", "{}");
        if (decision.getInt("status") != 200) return decision;
        // This is only a transport envelope; archived forecast bytes remain unchanged.
        forecast.getJSONObject("body").put("manual_decision", decision.getJSONObject("body"));
        return forecast;
    }

    static boolean canContinue(Throwable error) {
        for (Throwable cause = error; cause != null; cause = cause.getCause()) {
            if (cause instanceof java.util.concurrent.TimeoutException) return true;
            if (cause.getMessage() != null && cause.getMessage().contains("COMPUTE_checkpoint_pause")) return true;
        }
        return false;
    }
    interface Revision { long read() throws Exception; }
    static JSObject continueForecast(Request request, Revision revision, String body) throws Exception {
        for (int attempt = 0; ; attempt++) {
            long before = revision.read();
            try { return request.run("/api/v1/mobile/daily/generate", body); }
            catch (Exception error) {
                if (attempt >= 2 || !canContinue(error) || revision.read() <= before) throw error;
            }
        }
    }

    private void foreground(String phase) {
        this.phase = phase;
        int percent = -1;
        try {
            LocalComputeOwner owner = computeOwner;
            if (owner != null) {
                JSObject saved = owner.checkpoints.status(true);
                if (!phase.equals("deciding") && !saved.isNull("percent")) percent = saved.optInt("percent", -1);
            }
        } catch (Exception ignored) { /* Initial progress has no denominator yet. */ }
        androidx.work.ForegroundInfo info = DailyWorker.foregroundInfo(this, phase, percent);
        if (android.os.Build.VERSION.SDK_INT >= 29) startForeground(6104, info.getNotification(), info.getForegroundServiceType());
        else startForeground(6104, info.getNotification());
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        synchronized (LOCK) {
            if (active == null || intent == null || !active.id.equals(intent.getStringExtra("job"))) {
                stopSelf(startId); return START_NOT_STICKY;
            }
            if (thread != null) return START_NOT_STICKY;
            job = active;
        }
        try {
            foreground("calculating");
            wake = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "StockAI:manual-analysis");
            wake.acquire(TimeUnit.MINUTES.toMillis(23));
            thread = new Thread(() -> {
                JSObject result = null; Throwable failure = null;
                try {
                    LocalComputeOwner owner = LocalComputeOwner.get(this);
                    computeOwner = owner;
                    long deadline = android.os.SystemClock.elapsedRealtime() + TimeUnit.MINUTES.toMillis(20);
                    Request bounded = (path, body) -> {
                        long remaining = deadline - android.os.SystemClock.elapsedRealtime();
                        if (remaining <= 0) throw new java.util.concurrent.TimeoutException("ANALYSIS_TOTAL_BUDGET");
                        core = owner.request("POST", path, body);
                        try { return core.get(Math.min(TimeUnit.SECONDS.toMillis(660), remaining), TimeUnit.MILLISECONDS); }
                        finally { if (!core.isDone()) core.cancel(true); core = null; }
                    };
                    result = run(job.body, (path, body) -> handles("POST", path)
                        ? continueForecast(bounded, () -> owner.checkpoints.status(true).optLong("savedRevision"), body)
                        : bounded.run(path, body), this::foreground);
                } catch (Exception error) {
                    failure = error;
                    try { LocalComputeOwner.get(this).checkpoints.failed(error); } catch (Exception ignored) { }
                }
                final JSObject saved = result; final Throwable error = failure;
                new Handler(Looper.getMainLooper()).post(() -> {
                    savedResult = saved; savedError = error; stopSelf();
                });
            }, "stockai-manual-analysis");
            thread.start();
            updates.postDelayed(refresh, 1000);
        } catch (Exception error) { savedError = error; stopSelf(); }
        return START_NOT_STICKY;
    }

    private void release() {
        updates.removeCallbacks(refresh);
        if (wake != null && wake.isHeld()) wake.release();
        stopForeground(STOP_FOREGROUND_REMOVE);
    }

    @Override public void onTimeout(int startId, int fgsType) { stopSelf(); }
    @Override public void onDestroy() {
        CompletableFuture<JSObject> pending = core;
        if (pending != null) pending.cancel(true);
        if (thread != null) thread.interrupt();
        release();
        if (job != null && !job.result.isDone()) finish(job, savedResult, savedError);
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
