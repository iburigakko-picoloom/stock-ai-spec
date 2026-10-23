package jp.stockai.app;

import static org.junit.Assert.*;
import org.junit.Test;

public class DailyForegroundPolicyTest {
    @Test public void acquisitionAndCalculationRequireForegroundButIdleDoesNot() {
        for (String phase : new String[]{"history", "membership", "calculating", "deciding"})
            assertTrue(DailyWorker.requiresForeground(phase));
        for (String phase : new String[]{"waiting_cutoff", "closed", "inputs", "forecast_saved"})
            assertFalse(DailyWorker.requiresForeground(phase));
    }

    @Test public void acquisitionRefusalIsDifferentFromCalculationRefusal() {
        assertTrue(new DailyWorker.ForegroundUnavailable(true).acquisition);
        assertFalse(new DailyWorker.ForegroundUnavailable().acquisition);
    }

    @Test public void deniedAcquisitionFallsBackButLongCalculationDoesNot() throws Exception {
        for (String phase : new String[]{"history", "membership"}) {
            assertFalse(DailyWorker.tryForeground(phase, ignored -> { throw new DailyWorker.ForegroundUnavailable(true); }));
            assertTrue(DailyWorker.tryForeground(phase, ignored -> { }));
        }
        for (String phase : new String[]{"calculating", "deciding"}) {
            try {
                DailyWorker.tryForeground(phase, ignored -> { throw new DailyWorker.ForegroundUnavailable(); });
                fail("long computation admission bypassed");
            } catch (DailyWorker.ForegroundUnavailable expected) { }
        }
    }

    @Test public void interruptedAcquisitionNeverFallsBack() throws Exception {
        try {
            DailyWorker.tryForeground("history", ignored -> { throw new InterruptedException(); });
            fail("interruption swallowed");
        } catch (InterruptedException expected) { }
    }
}
