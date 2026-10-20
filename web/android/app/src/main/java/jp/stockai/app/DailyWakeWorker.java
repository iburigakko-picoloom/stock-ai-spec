package jp.stockai.app;

import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

public final class DailyWakeWorker extends Worker {
    public DailyWakeWorker(@NonNull Context context, @NonNull WorkerParameters parameters) { super(context, parameters); }
    @NonNull @Override public Result doWork() {
        try {
            new DailyAutomation(getApplicationContext(), LocalComputeOwner.get(getApplicationContext()).state.database).wake();
            return Result.success();
        } catch (Exception ignored) { return Result.retry(); }
    }
}
