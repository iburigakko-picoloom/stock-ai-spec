package jp.stockai.app;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Synthetic transport/core boundaries only; actual core/restore tests are separate. */
@RunWith(AndroidJUnit4.class)
public class DailyPipelineTest {
    final String today = "2026-01-06", prior = "2026-01-05";
    final List<String> events = new ArrayList<>();
    final AtomicBoolean stopped = new AtomicBoolean();
    boolean complete, partial, late, closed, failCommit, badDecision, forbid, failAck, stopAfterCommit;
    boolean planSaved, stopAfterForecast, rolloverAfterForecast, rolloverAfterDecision, rejectForeground;
    String decisionTime = "2026-01-06T11:30:00+09:00";
    JSONObject forecast;
    Instant now = Instant.parse("2026-01-06T02:31:00Z");

    JSONObject membership() throws Exception {
        return new JSONObject().put("date", today).put("acquisitionId", JSONObject.NULL)
            .put("latest_received_at", late ? JSONObject.NULL : "2026-01-06T01:45:00Z")
            .put("available_at_cutoff", !late).put("is_business_day", !closed);
    }
    JSONObject core(String method, String path, String body) throws Exception {
        events.add(method + " " + path);
        if (path.endsWith("/research/plan")) return new JSONObject().put("status", planSaved ? 200 : 422)
            .put("body", new JSONObject().put("day", today));
        JSONObject result;
        if (path.endsWith("/membership")) result = membership();
        else if (path.endsWith("/market")) result = new JSONObject().put("completed_dates", complete ? new JSONArray().put(prior) : new JSONArray())
            .put("committed_acquisitions", complete ? new JSONArray().put(new JSONObject().put("date", prior).put("acquisitionId", "fixture-acquisition")) : new JSONArray());
        else if (path.endsWith("/ingest")) {
            if (failCommit) throw new IllegalStateException("synthetic disk failure");
            complete = true; result = new JSONObject(); if (stopAfterCommit) stopped.set(true);
        } else if (path.endsWith("/daily")) return new JSONObject().put("status", 200).put("body", forecast == null ? JSONObject.NULL : forecast);
        else if (path.endsWith("/daily/generate")) {
            forecast = forecast("published", today + "T11:30:00+09:00"); result = forecast;
            if (stopAfterForecast) stopped.set(true);
            if (rolloverAfterForecast) now = now.plusSeconds(86400);
        } else if (path.endsWith("/decision/generate")) {
            result = new JSONObject().put("is_active", !badDecision)
                .put("scope", new JSONObject().put("as_of", decisionTime)).put("run_id", "fixture-result");
            planSaved = !badDecision;
            if (rolloverAfterDecision) now = now.plusSeconds(86400);
        }
        else throw new AssertionError(path);
        return new JSONObject().put("status", 200).put("body", result);
    }
    DailyPipeline pipeline() {
        return new DailyPipeline(this::core, new DailyPipeline.Market() {
            public JSONObject fetch(boolean membership, String day, java.util.function.BooleanSupplier stop) throws Exception {
                events.add("fetch:" + membership + ":" + day);
                if (forbid) return new JSONObject().put("status", 403);
                JSONObject result = new JSONObject().put("status", partial ? 202 : 200).put("date", day).put("acquisitionId", "fixture-acquisition");
                if (!partial) result.put("received_at", now.toString()).put("datasets", new JSONObject()).put("valuations", new JSONArray());
                return result;
            }
            public void acknowledge(boolean membership, String day, String id) throws Exception {
                events.add("ack:" + membership + ":" + day);
                if (failAck) throw new java.io.IOException("synthetic lost acknowledgment");
            }
        }, new DailyPipeline.Progress() {
            public void state(String value, String day) throws Exception {
                events.add("state:" + value);
                if (rejectForeground && (value.equals("calculating") || value.equals("deciding"))) throw new DailyWorker.ForegroundUnavailable();
            }
            public void notice(String key, String text) { events.add("notice:" + key); }
        }, stopped::get, () -> now);
    }

    JSONObject forecast(String phase, String asOf) throws Exception {
        return new JSONObject().put("phase", phase).put("run_id", "fixture-forecast")
            .put("scope", new JSONObject().put("as_of", asOf));
    }

    @Test public void boundedPartialPageNeverCommitsOrAcknowledges() throws Exception {
        partial = true;
        assertTrue(pipeline().tick(prior));
        assertTrue(events.contains("fetch:false:" + prior));
        assertFalse(complete);
        assertFalse(events.stream().anyMatch(e -> e.startsWith("ack:") || e.contains("generate")));
    }
    @Test public void ingestDurablyCommitsBeforeAcknowledgmentAndLostAckRecoversWithoutFetch() throws Exception {
        failAck = true;
        try { pipeline().tick(prior); fail("lost ack ignored"); } catch (java.io.IOException expected) { }
        assertTrue(events.indexOf("POST /api/v1/mobile/market/ingest") < events.indexOf("ack:false:" + prior));
        events.clear(); failAck = false;
        assertTrue(pipeline().tick(prior));
        assertTrue(events.contains("ack:false:" + prior));
        assertFalse(events.stream().anyMatch(e -> e.startsWith("fetch:")));
        assertTrue(events.contains("state:forecast_saved"));
        assertFalse(events.contains("POST /api/v1/mobile/decision/generate"));
    }
    @Test public void failedNativeCommitLeavesPagesUnacknowledged() throws Exception {
        failCommit = true;
        try { pipeline().tick(prior); fail("failed commit accepted"); } catch (IllegalStateException expected) { }
        assertFalse(events.stream().anyMatch(e -> e.startsWith("ack:")));
        assertFalse(complete);
    }
    @Test public void stopAfterDurableIngestLeavesAckForRecoveryAndDoesNotCalculate() throws Exception {
        stopAfterCommit = true;
        try { pipeline().tick(prior); fail("stop ignored"); } catch (InterruptedException expected) { }
        assertTrue(complete);
        assertFalse(events.stream().anyMatch(e -> e.startsWith("ack:") || e.contains("generate")));
    }
    @Test public void lateStartCannotAcquireOrBackdateCurrentMembership() throws Exception {
        complete = true; late = true;
        assertFalse(pipeline().tick(prior));
        assertTrue(events.contains("state:late"));
        assertFalse(events.stream().anyMatch(e -> e.startsWith("fetch:") || e.contains("generate")));
    }
    @Test public void holidayAndInactiveDecisionNeverClaimCompletion() throws Exception {
        complete = true; closed = true;
        assertFalse(pipeline().tick(prior));
        assertTrue(events.contains("state:closed"));
        assertFalse(events.stream().anyMatch(e -> e.contains("generate")));
        events.clear(); closed = false; badDecision = true;
        forecast = forecast("published", today + "T11:30:00+09:00");
        assertFalse(pipeline().tick(prior));
        assertTrue(events.contains("state:inputs"));
        assertFalse(events.contains("state:numerical_saved"));
    }
    @Test public void stopAndForbiddenPlanDoNotProceedToCalculation() throws Exception {
        stopped.set(true);
        try { pipeline().tick(prior); fail("stopped work ran"); } catch (InterruptedException expected) { }
        assertTrue(events.isEmpty());
        stopped.set(false); forbid = true;
        try { pipeline().tick(prior); fail("403 accepted"); }
        catch (DailyPipeline.ProviderFailure expected) { assertTrue(expected.credentials); }
        assertFalse(events.stream().anyMatch(e -> e.contains("generate") || e.contains("/ingest")));
    }
    @Test public void preCutoffOnlyWaitsAndNeverPublishesEarly() throws Exception {
        complete = true; now = Instant.parse("2026-01-06T02:20:00Z");
        assertFalse(pipeline().tick(prior));
        assertTrue(events.contains("state:waiting_cutoff"));
        assertFalse(events.stream().anyMatch(e -> e.contains("generate")));
    }

    @Test public void forecastSharesAndResearchPlanUseSeparateSlicesWithoutRecomputation() throws Exception {
        complete = true;
        assertTrue(pipeline().tick(prior));
        assertTrue(events.indexOf("state:calculating") < events.indexOf("POST /api/v1/mobile/daily/generate"));
        assertTrue(events.contains("state:forecast_saved"));
        assertFalse(events.stream().anyMatch(e -> e.contains("decision/generate") || e.contains("state:numerical_saved") || e.startsWith("notice:")));
        JSONObject committed = forecast;
        events.clear();
        assertTrue(pipeline().tick(prior));
        assertSame(committed, forecast);
        assertFalse(events.contains("POST /api/v1/mobile/daily/generate"));
        assertTrue(events.indexOf("state:deciding") < events.indexOf("POST /api/v1/mobile/decision/generate"));
        assertTrue(events.contains("state:numerical_saved"));
        assertTrue(events.contains("notice:" + today + ":fixture-result"));
        events.clear();
        assertFalse(pipeline().tick(prior));
        assertTrue(events.contains("state:numerical_saved"));
        assertFalse(events.stream().anyMatch(e -> e.startsWith("POST ") || e.startsWith("notice:")));
    }

    @Test public void stopAfterForecastCommitResumesAtSharesAndKeepsOriginalReceipt() throws Exception {
        complete = true; stopAfterForecast = true;
        try { pipeline().tick(prior); fail("stop ignored"); } catch (InterruptedException expected) { }
        assertNotNull(forecast);
        assertFalse(events.contains("state:forecast_saved"));
        JSONObject committed = forecast;
        events.clear(); stopped.set(false); stopAfterForecast = false;
        assertTrue(pipeline().tick(prior));
        assertSame(committed, forecast);
        assertTrue(events.contains("POST /api/v1/mobile/decision/generate"));
        assertFalse(events.contains("POST /api/v1/mobile/daily/generate"));
    }

    @Test public void oldBlockedAndWrongCutoffReceiptsNeverProceedDirectlyToShares() throws Exception {
        complete = true;
        for (JSONObject saved : new JSONObject[]{forecast("published", prior + "T11:30:00+09:00"),
                forecast("blocked", today + "T11:30:00+09:00"), forecast("published", today + "T11:29:59+09:00")}) {
            forecast = saved; events.clear();
            assertTrue(pipeline().tick(prior));
            assertTrue(events.contains("POST /api/v1/mobile/daily/generate"));
            assertFalse(events.contains("POST /api/v1/mobile/decision/generate"));
        }
    }

    @Test public void cashOnlyAndEquivalentUtcCutoffResumeWithoutNewForecast() throws Exception {
        complete = true; forecast = forecast("cash_only", "2026-01-06T02:30:00Z");
        assertTrue(pipeline().tick(prior));
        assertFalse(events.contains("POST /api/v1/mobile/daily/generate"));
        assertTrue(events.contains("state:numerical_saved"));
    }

    @Test public void malformedSavedCutoffFailsClosedWithoutAnotherForecast() throws Exception {
        complete = true; forecast = forecast("published", "invalid-time");
        try { pipeline().tick(prior); fail("corrupt scope accepted"); } catch (DailyPipeline.CoreFailure expected) { }
        assertFalse(events.stream().anyMatch(e -> e.startsWith("POST ")));
    }

    @Test public void wrongDecisionCutoffNeverClaimsNumericalCompletion() throws Exception {
        complete = true; forecast = forecast("published", today + "T11:30:00+09:00");
        decisionTime = today + "T11:29:59+09:00";
        assertFalse(pipeline().tick(prior));
        assertTrue(events.contains("state:inputs"));
        assertFalse(events.contains("state:numerical_saved"));
    }

    @Test public void midnightDuringEitherCommitDoesNotClaimCurrentDayCompletion() throws Exception {
        complete = true; rolloverAfterForecast = true;
        assertTrue(pipeline().tick(prior));
        assertFalse(events.stream().anyMatch(e -> e.equals("state:forecast_saved") || e.equals("state:numerical_saved") || e.startsWith("notice:")));
        now = Instant.parse("2026-01-06T14:59:00Z"); rolloverAfterForecast = false; rolloverAfterDecision = true;
        events.clear();
        assertTrue(pipeline().tick(prior));
        assertFalse(events.stream().anyMatch(e -> e.equals("state:numerical_saved") || e.startsWith("notice:")));
    }

    @Test public void refusedForegroundDoesNotEnterEitherLongComputation() throws Exception {
        complete = true; rejectForeground = true;
        try { pipeline().tick(prior); fail("foreground refusal ignored"); } catch (DailyWorker.ForegroundUnavailable expected) { }
        assertFalse(events.stream().anyMatch(e -> e.startsWith("POST ")));
        events.clear(); forecast = forecast("published", today + "T11:30:00+09:00");
        try { pipeline().tick(prior); fail("foreground refusal ignored"); } catch (DailyWorker.ForegroundUnavailable expected) { }
        assertFalse(events.stream().anyMatch(e -> e.startsWith("POST ")));
    }
}
