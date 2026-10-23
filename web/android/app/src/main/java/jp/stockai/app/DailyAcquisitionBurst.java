package jp.stockai.app;

import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;

/** Amortize OS dispatch between acquisition slices, without batching commits. */
final class DailyAcquisitionBurst {
    static final int MAX_SLICES = 16;
    static final long START_WINDOW_MS = 120_000;
    interface Slice { boolean run() throws Exception; }

    static boolean run(Slice slice, BooleanSupplier acquisition, BooleanSupplier stopped,
                       LongSupplier elapsedMillis) throws Exception {
        long started = elapsedMillis.getAsLong();
        for (int count = 1; ; count++) {
            if (stopped.getAsBoolean() || Thread.currentThread().isInterrupted()) throw new InterruptedException();
            boolean more = slice.run();
            if (stopped.getAsBoolean() || Thread.currentThread().isInterrupted()) throw new InterruptedException();
            if (!more || !acquisition.getAsBoolean() || count >= MAX_SLICES
                    || elapsedMillis.getAsLong() - started >= START_WINDOW_MS) return more;
        }
    }
}
