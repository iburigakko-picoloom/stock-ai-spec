package jp.stockai.app;

import static org.junit.Assert.*;
import org.junit.Test;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

public class DailyAcquisitionBurstTest {
    @Test public void severalAcquisitionSlicesUseOneDispatchAndFinishWithoutAnotherJob() throws Exception {
        AtomicInteger count = new AtomicInteger();
        assertFalse(DailyAcquisitionBurst.run(() -> count.incrementAndGet() < 8, () -> true, () -> false, () -> 0));
        assertEquals(8, count.get());
    }
    @Test public void pageAndTimeBudgetsYieldToExistingScheduler() throws Exception {
        AtomicInteger count = new AtomicInteger();
        assertTrue(DailyAcquisitionBurst.run(() -> { count.incrementAndGet(); return true; }, () -> true, () -> false, () -> 0));
        assertEquals(16, count.get());
        count.set(0); AtomicLong clock = new AtomicLong();
        assertTrue(DailyAcquisitionBurst.run(() -> { count.incrementAndGet(); clock.addAndGet(60_000); return true; },
            () -> true, () -> false, clock::get));
        assertEquals(2, count.get());
    }
    @Test public void calculationOrUnclassifiedYieldNeverRunsAnotherSlice() throws Exception {
        AtomicInteger count = new AtomicInteger();
        assertTrue(DailyAcquisitionBurst.run(() -> { count.incrementAndGet(); return true; }, () -> false, () -> false, () -> 0));
        assertEquals(1, count.get());
    }
    @Test public void stopAfterCommitDoesNotStartNextSlice() throws Exception {
        AtomicInteger count = new AtomicInteger(); AtomicBoolean stopped = new AtomicBoolean();
        try {
            DailyAcquisitionBurst.run(() -> { count.incrementAndGet(); stopped.set(true); return true; }, () -> true, stopped::get, () -> 0);
            fail("stop ignored");
        } catch (InterruptedException expected) { assertEquals(1, count.get()); }
    }
    @Test public void failureStopsImmediatelyWithoutDiscardingPriorCommits() throws Exception {
        AtomicInteger committed = new AtomicInteger();
        try {
            DailyAcquisitionBurst.run(() -> { if (committed.get() == 3) throw new java.io.IOException("fixture"); committed.incrementAndGet(); return true; },
                () -> true, () -> false, () -> 0);
            fail("failure ignored");
        } catch (java.io.IOException expected) { assertEquals(3, committed.get()); }
    }
}
