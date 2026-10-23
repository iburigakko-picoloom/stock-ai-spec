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
}
