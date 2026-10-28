package jp.stockai.app;

import static org.junit.Assert.*;
import org.junit.Test;

public class DailyProgressNoticeTest {
    @Test public void acquisitionAndGapsKeepNoticeWithoutClaimingContinuousNetworkActivity() {
        assertTrue(DailyAutomation.progressText(true, "history").contains("待ち"));
        assertTrue(DailyAutomation.progressText(true, "membership").contains("待ち"));
        assertTrue(DailyAutomation.progressText(true, "history_wait").contains("再開待ち"));
        assertTrue(DailyAutomation.progressText(true, "retry").contains("再開待ち"));
        assertNotNull(DailyAutomation.progressText(true, "queued"));
        assertNotEquals(6102, DailyAutomation.PROGRESS_NOTIFICATION_ID);
    }

    @Test public void completionAndStopRemoveNoticeInsteadOfLeavingFalseProgress() {
        for (String state : new String[]{"closed", "waiting_cutoff", "calculating", "deciding",
                "numerical_saved", "consultation_ready", "inputs", "credentials", "paused", "idle"})
            assertNull(DailyAutomation.progressText(true, state));
        for (String state : new String[]{"history", "membership", "queued", "retry", "history_wait"})
            assertNull(DailyAutomation.progressText(false, state));
    }
}
