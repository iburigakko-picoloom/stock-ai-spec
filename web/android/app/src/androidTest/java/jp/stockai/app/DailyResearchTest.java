package jp.stockai.app;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.IOException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Synthetic boundaries exercise dispatch/receipt ordering; shared Python validates real response schemas. */
@RunWith(AndroidJUnit4.class)
public class DailyResearchTest {
    final String day = "2026-01-06";
    String snapshot = "fixture-snapshot", effort = "high";
    JSONObject batch;
    final Map<String, Integer> phases = new HashMap<>();
    final Map<String, String> current = new HashMap<>();
    final Map<String, JSONObject> executions = new HashMap<>();
    final List<String> events = new ArrayList<>();
    boolean stopped, failCommit, failAck, limit, invalidFirst, restored;
    JSONArray symbols = new JSONArray().put("1000").put("7203");

    JSONObject view(String symbol) throws Exception {
        int phase = phases.getOrDefault(symbol, 0);
        JSONArray attempts = new JSONArray();
        for (int i = 0; i < phase; i++) attempts.put(new JSONObject().put("attempt_id", symbol + "-" + i).put("status", "completed"));
        return new JSONObject().put("run", new JSONObject().put("run_id", symbol)
            .put("context", new JSONObject().put("symbol", symbol))).put("attempts", attempts)
            .put("record", phase == 2 && !restored ? new JSONObject().put("fixture", true) : JSONObject.NULL);
    }
    JSONObject api(String method, String path, String body) throws Exception {
        events.add(method + ":" + path);
        JSONObject result;
        if (path.endsWith("/mobile/research/plan")) result = new JSONObject().put("day", day).put("snapshot_id", snapshot).put("symbols", symbols);
        else if (method.equals("GET")) result = new JSONObject().put("runs", new JSONArray().put(view("1000")).put(view("7203")));
        else if (path.endsWith("/start")) {
            String[] parts = path.split("/"); result = view(parts[parts.length - 2]);
        } else if (path.endsWith("/claim")) {
            String[] parts = path.split("/"); String symbol = parts[parts.length - 2];
            int phase = phases.getOrDefault(symbol, 0);
            result = view(symbol);
            if (phase == 2) result.put("state", "completed");
            else if (current.getOrDefault(symbol, "").equals("blocked")) result.put("state", "blocked");
            else {
                String id = symbol + "-" + phase;
                result.put("state", current.containsKey(symbol) ? "running" : "ready")
                    .put("attempt", new JSONObject().put("attempt_id", id))
                    .put("request_json", phase == 0 ? "{\"company\":\"" + symbol + "\"}" : "{\"forecast\":1}")
                    .put("request_sha256", "fixture-digest");
                current.put(symbol, id);
            }
        } else if (path.endsWith("/receipt")) {
            if (failCommit) throw new IOException("synthetic native commit failure");
            String[] parts = path.split("/"); String id = parts[parts.length - 2], symbol = id.substring(0, 4);
            if (limit || (invalidFirst && symbol.equals("1000"))) {
                current.put(symbol, "blocked");
                result = view(symbol).put("attempts", new JSONArray().put(new JSONObject().put("attempt_id", id)
                    .put("status", "failed").put("error_code", limit ? "HTTP_429" : "INVALID_RESEARCH_RESPONSE")));
            } else {
                phases.put(symbol, phases.getOrDefault(symbol, 0) + 1); current.remove(symbol); result = view(symbol);
            }
        } else throw new AssertionError(path);
        return new JSONObject().put("status", 200).put("body", result);
    }
    DailyResearch driver() {
        return new DailyResearch(this::api, new DailyResearch.Provider() {
            public JSONObject selection() throws Exception { return new JSONObject().put("model", "fixture-model").put("effort", effort).put("account_key", "fixture-account"); }
            public JSONObject respond(String id, String request, String hash, String model, String depth) throws Exception {
                events.add("send:" + id + ":" + request);
                JSONObject receipt = new JSONObject().put("attemptId", id).put("requestSha256", hash)
                    .put("state", limit ? "failed" : "completed").put("errorCode", "HTTP_429")
                    .put("response", new JSONObject().put("fixture", true))
                    .put("startedAt", "2026-01-06T03:00:00Z").put("completedAt", "2026-01-06T03:01:00Z");
                executions.put(id, receipt); return receipt;
            }
            public JSONObject recover(String id) throws Exception { events.add("recover:" + id); return executions.get(id); }
            public void acknowledge(String id) throws Exception { events.add("ack:" + id); if (failAck) throw new IOException("lost ack"); }
        }, new DailyResearch.Journal() {
            public JSONObject read(String selected) throws Exception { return batch == null ? null : new JSONObject(batch.toString()); }
            public void write(String selected, JSONObject value) throws Exception { batch = new JSONObject(value.toString()); }
        }, new DailyPipeline.Progress() {
            public void state(String state, String date) { events.add("state:" + state); }
            public void notice(String key, String text) { events.add("notice:" + key); }
        }, () -> stopped, () -> Instant.parse("2026-01-06T03:00:00Z"));
    }

    @Test public void phasesCommitInOrderAndWholeScopeIncludesHeldSymbolWithoutDuplicateSends() throws Exception {
        for (int i = 0; i < 4; i++) assertTrue(driver().step());
        assertFalse(driver().step()); assertFalse(driver().step());
        List<String> sends = new ArrayList<>();
        for (String event : events) if (event.startsWith("send:")) sends.add(event);
        assertEquals(4, sends.size());
        assertEquals("send:1000-0:{\"company\":\"1000\"}", sends.get(0));
        assertEquals("send:1000-1:{\"forecast\":1}", sends.get(1));
        assertTrue(sends.get(2).contains("7203-0"));
        assertTrue(events.indexOf("POST:/api/v1/research/1000-0/receipt") < events.indexOf(sends.get(1)));
        assertTrue(events.contains("state:research_complete"));
    }
    @Test public void rejectedCommitRecoversNativeResponseWithoutAnotherProviderRequest() throws Exception {
        failCommit = true;
        try { driver().step(); fail("failed commit accepted"); } catch (IOException expected) { }
        assertFalse(events.contains("ack:1000-0"));
        failCommit = false; assertTrue(driver().step());
        assertTrue(events.contains("recover:1000-0"));
        assertEquals(1, events.stream().filter(e -> e.startsWith("send:")).count());
        assertTrue(events.contains("ack:1000-0"));
    }
    @Test public void lostAckDoesNotRepeatInferenceOrBlockTheNextPhase() throws Exception {
        failAck = true; assertTrue(driver().step());
        failAck = false; assertTrue(driver().step());
        assertEquals(2, events.stream().filter(e -> e.startsWith("send:")).count());
        assertEquals(2, events.stream().filter(e -> e.equals("ack:1000-0")).count());
    }
    @Test public void recoveredResponseWithAnotherRequestHashIsNeverCommittedOrAcknowledged() throws Exception {
        failCommit = true;
        try { driver().step(); fail("failed commit accepted"); } catch (IOException expected) { }
        failCommit = false; executions.get("1000-0").put("requestSha256", "another-request");
        events.clear();
        try { driver().step(); fail("foreign response accepted"); }
        catch (IOException expected) { assertEquals("ATTEMPT_REQUEST_CHANGED", expected.getMessage()); }
        assertFalse(events.stream().anyMatch(e -> e.endsWith("/receipt") || e.startsWith("ack:") || e.startsWith("send:")));
    }
    @Test public void selectionChangeAndRestoredMissingRecordCannotClaimCompletion() throws Exception {
        assertTrue(driver().step()); effort = "max";
        assertFalse(driver().step()); assertEquals(1, events.stream().filter(e -> e.startsWith("send:")).count());
        effort = "high"; assertTrue(driver().step()); restored = true;
        assertFalse(driver().step());
        assertFalse(events.contains("state:research_complete"));
    }
    @Test public void usageLimitStopsWithoutAutomaticallyRetryingTheFailedAttempt() throws Exception {
        limit = true; assertFalse(driver().step()); assertFalse(driver().step());
        assertEquals(1, events.stream().filter(e -> e.startsWith("send:")).count());
        assertTrue(events.contains("state:research_attention"));
    }
    @Test public void invalidOneCompanyStillResearchesTheOtherAndShowsPartialCompletion() throws Exception {
        invalidFirst = true;
        assertTrue(driver().step()); assertTrue(driver().step()); assertTrue(driver().step());
        assertFalse(driver().step());
        assertEquals(3, events.stream().filter(e -> e.startsWith("send:")).count());
        assertTrue(events.contains("state:research_attention"));
        assertFalse(events.contains("state:research_complete"));
    }
    @Test public void stopAndEmptyScopeNeverSendProviderRequests() throws Exception {
        stopped = true;
        try { driver().step(); fail("stop ignored"); } catch (InterruptedException expected) { }
        assertTrue(events.isEmpty()); stopped = false; symbols = new JSONArray();
        assertFalse(driver().step());
        assertEquals(0, events.stream().filter(e -> e.startsWith("send:")).count());
    }
}
