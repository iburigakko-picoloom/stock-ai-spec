package jp.stockai.app;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class EveningPipelineTest {
    final String today = "2026-01-06", prior = "2026-01-05";
    final List<String> events = new ArrayList<>();
    Instant now = Instant.parse("2026-01-06T08:00:00Z");
    boolean todayAcquired = true, holiday = false, blocked = false;
    JSONObject reference;

    JSONObject core(String method, String path, String body) throws Exception {
        events.add(method + " " + path);
        Object value;
        if (path.endsWith("/market/membership")) value = new JSONObject().put("date", today)
            .put("acquisitionId", JSONObject.NULL).put("latest_received_at", "2026-01-06T08:00:00Z")
            .put("latest_is_business_day", !holiday);
        else if (path.endsWith("/market")) {
            JSONArray days = new JSONArray().put(prior);
            if (todayAcquired) days.put(today);
            value = new JSONObject().put("completed_dates", days);
        } else if (path.endsWith("/market/ingest")) { todayAcquired = true; value = new JSONObject(); }
        else if (path.endsWith("/daily/reference")) value = reference == null ? JSONObject.NULL : reference;
        else if (path.endsWith("/daily/generate")) {
            assertTrue(new JSONObject(body).getBoolean("reference_only"));
            reference = new JSONObject().put("phase", blocked ? "blocked" : "reference_saved")
                .put("scope", new JSONObject().put("analysis_mode", "latest_available_reference")
                    .put("universe", new JSONObject().put("latest_source_date", today)))
                .put("snapshot", blocked ? JSONObject.NULL : new JSONObject());
            value = reference;
        } else throw new AssertionError(path);
        return new JSONObject().put("status", 200).put("body", value);
    }

    DailyPipeline pipeline() {
        return new DailyPipeline(this::core, new DailyPipeline.Market() {
            public JSONObject fetch(boolean membership, String day, java.util.function.BooleanSupplier stopped) throws Exception {
                events.add("fetch:" + membership + ":" + day);
                return new JSONObject().put("status", 200).put("date", day).put("acquisitionId", "id")
                    .put("received_at", now.toString()).put("datasets", new JSONObject()).put("valuations", new JSONArray());
            }
            public void acknowledge(boolean membership, String day, String id) { events.add("ack:" + day); }
        }, new DailyPipeline.Progress() {
            public void state(String value, String day) { events.add("state:" + value); }
            public void notice(String key, String text) { events.add("notice:" + key); }
        }, () -> false, () -> now);
    }

    @Test public void beforeSeventeenKeepsSavedResultsAndDoesNotGenerate() throws Exception {
        now = Instant.parse("2026-01-06T07:59:59Z");
        assertFalse(pipeline().tick(prior));
        assertTrue(events.contains("state:waiting_cutoff"));
        assertFalse(events.stream().anyMatch(e -> e.contains("generate")));
    }

    @Test public void todayIsAcquiredBeforeReferenceGeneration() throws Exception {
        todayAcquired = false;
        assertTrue(pipeline().tick(prior));
        assertTrue(events.contains("fetch:false:" + today));
        assertTrue(events.contains("ack:" + today));
        assertFalse(events.stream().anyMatch(e -> e.contains("generate")));
        events.clear();
        assertFalse(pipeline().tick(prior));
        assertTrue(events.contains("POST /api/v1/mobile/daily/generate"));
        assertTrue(events.contains("state:reference_saved"));
        assertFalse(events.stream().anyMatch(e -> e.contains("decision/generate")));
    }

    @Test public void completedTodayIsNotComputedAgain() throws Exception {
        assertFalse(pipeline().tick(prior));
        events.clear();
        assertFalse(pipeline().tick(prior));
        assertTrue(events.contains("state:reference_saved"));
        assertFalse(events.stream().anyMatch(e -> e.contains("generate")));
    }

    @Test public void holidayDoesNotCreatePrediction() throws Exception {
        holiday = true;
        assertFalse(pipeline().tick(prior));
        assertTrue(events.contains("state:closed"));
        assertFalse(events.stream().anyMatch(e -> e.contains("generate")));
    }

    @Test public void failedReferenceDoesNotClaimACompletedRanking() throws Exception {
        blocked = true;
        assertFalse(pipeline().tick(prior));
        assertTrue(events.contains("state:inputs"));
        assertFalse(events.contains("state:reference_saved"));
    }
}
