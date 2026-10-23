package jp.stockai.app;

import static org.junit.Assert.*;
import org.junit.Test;

public class MarketRequestPacingTest {
    private MarketRequestPacing pacing() {
        MarketRequestPacing p = new MarketRequestPacing(); p.credential("fixture-key-id"); return p;
    }
    @Test public void unknownCalendarAndEmptyTopixNeverGrantPaidRate() {
        MarketRequestPacing p = pacing(); assertEquals(0, p.delay(0)); p.started(0);
        p.response("/markets/calendar", 200, true, 0);
        p.response("/indices/bars/daily/topix", 200, false, 0);
        assertEquals(12_500, p.delay(0));
        assertEquals(0, p.delay(12_500));
    }
    @Test public void realTopixAccessUsesLessThanSixtyRequestsInSlidingMinute() {
        MarketRequestPacing p = pacing(); p.started(0);
        p.response("/indices/bars/daily/topix", 200, true, 0);
        assertEquals(1_100, p.delay(0));
        long now = 0;
        for (int i = 0; i < 60; i++) { now += p.delay(now); p.started(now); }
        assertTrue(now >= 60_000);
        // 1,000 successive waits: 1,100 seconds versus former 12,500 seconds.
        now = 0;
        MarketRequestPacing sample = pacing(); sample.started(0);
        sample.response("/indices/bars/daily/topix", 200, true, 0);
        for (int i = 0; i < 1000; i++) { now += sample.delay(now); sample.started(now); }
        assertEquals(1_100_000, now);
    }
    @Test public void keyChangeAndAuthenticationErrorsRevokeProof() {
        for (int status : new int[]{401, 403}) {
            MarketRequestPacing p = pacing(); p.started(0);
            p.response("/indices/bars/daily/topix", 200, true, 0);
            p.response("/equities/master", status, false, 1);
            assertEquals(12_499, p.delay(1));
        }
        MarketRequestPacing p = pacing(); p.started(0);
        p.response("/indices/bars/daily/topix", 200, true, 0);
        p.credential("different-key-id"); assertEquals(12_500, p.delay(0));
    }
    @Test public void rateLimitKeepsTwoMinuteCooldownEvenAcrossKeyChange() {
        MarketRequestPacing p = pacing(); p.started(0);
        p.response("/indices/bars/daily/topix", 200, true, 0);
        p.response("/equities/master", 429, false, 100);
        p.credential("different-key-id");
        assertEquals(120_000, p.delay(100)); assertEquals(1, p.delay(120_099));
        assertEquals(0, p.delay(120_100));
        p.started(120_100); assertEquals(12_500, p.delay(120_100));
    }
    @Test public void proofExpiresAndDoesNotSurviveNewProcess() {
        MarketRequestPacing p = pacing();
        p.response("/indices/bars/daily/topix", 200, true, 0);
        long tomorrow = 86_400_000; p.started(tomorrow);
        assertEquals(12_500, p.delay(tomorrow));
        MarketRequestPacing restarted = pacing(); restarted.started(0);
        assertEquals(12_500, restarted.delay(0));
    }
}
