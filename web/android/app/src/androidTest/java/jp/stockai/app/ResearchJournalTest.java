package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class ResearchJournalTest {
    private static String id() { return UUID.randomUUID().toString().replace("-", ""); }
    private static String sha(String text) throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte item : MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)))
            result.append(String.format(java.util.Locale.ROOT, "%02x", item & 0xff));
        return result.toString();
    }
    @Test public void completedResponseSurvivesActivityReplacementAndAcknowledgmentCannotResend() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        ResearchJournal journal = new ResearchJournal(context); String attempt = id();
        try {
            assertTrue(journal.begin(attempt, sha("request"), "fixture-model", "high").getBoolean("dispatch"));
            assertFalse(new ResearchJournal(context).begin(attempt, sha("request"), "fixture-model", "high").getBoolean("dispatch"));
            assertEquals("running", journal.recover(attempt).getString("state"));
            journal.complete(attempt, new JSONObject().put("id", "fixture-response").put("status", "completed"));
            journal.release(attempt);
            ResearchJournal replacement = new ResearchJournal(context);
            assertEquals("fixture-response", replacement.current(attempt).getJSONObject("response").getString("id"));
            replacement.acknowledge(attempt);
            assertEquals("acknowledged", journal.current(attempt).getString("state"));
            assertFalse(journal.current(attempt).has("response"));
            assertFalse(journal.begin(attempt, sha("request"), "fixture-model", "high").getBoolean("dispatch"));
            try { journal.begin(attempt, sha("changed"), "fixture-model", "high"); fail("Different input reused the attempt"); }
            catch (IOException expected) { assertEquals("ATTEMPT_REQUEST_CHANGED", expected.getMessage()); }
        } finally { journal.release(attempt); new NativeSecrets(context).remove("research-" + attempt); }
    }
    @Test public void recoverySealsAbsentAndStoppedAttemptsBeforeLateCallersCanDispatch() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        ResearchJournal journal = new ResearchJournal(context); String absent = id(), stopped = id();
        try {
            assertEquals("interrupted", journal.recover(absent).getString("state"));
            assertFalse(journal.begin(absent, sha("request"), "fixture-model", "high").getBoolean("dispatch"));
            journal.begin(stopped, sha("request"), "fixture-model", "high");
            journal.release(stopped); // no live native owner, as after process death
            assertEquals("interrupted", journal.recover(stopped).getString("state"));
            assertFalse(journal.begin(stopped, sha("request"), "fixture-model", "high").getBoolean("dispatch"));
        } finally {
            journal.release(absent); journal.release(stopped);
            new NativeSecrets(context).remove("research-" + absent); new NativeSecrets(context).remove("research-" + stopped);
        }
    }
    @Test public void researchPayloadIsPinnedAndCannotEnableStorageOrDifferentTools() throws Exception {
        JSONObject body = new JSONObject().put("instructions", "独立した調査")
            .put("input", new JSONArray().put(new JSONObject().put("role", "user").put("content", "company")))
            .put("tools", new JSONArray().put(new JSONObject().put("type", "web_search")))
            .put("include", new JSONArray().put("web_search_call.action.sources"));
        String input = body.toString();
        JSONObject request = ChatGPTProtocol.researchRequest(input, sha(input), "fixture-model", "high");
        assertFalse(request.getBoolean("store")); assertTrue(request.getBoolean("stream"));
        assertEquals("fixture-model", request.getString("model"));
        assertEquals("high", request.getJSONObject("reasoning").getString("effort"));
        try { ChatGPTProtocol.researchRequest(input, sha("changed"), "fixture-model", "high"); fail("Changed input accepted"); }
        catch (SecurityException expected) { }
        body.put("store", true); input = body.toString();
        try { ChatGPTProtocol.researchRequest(input, sha(input), "fixture-model", "high"); fail("Extra API field accepted"); }
        catch (SecurityException expected) { }
        body.remove("store"); body.put("tools", new JSONArray().put(new JSONObject().put("type", "code_interpreter"))); input = body.toString();
        try { ChatGPTProtocol.researchRequest(input, sha(input), "fixture-model", "high"); fail("Unapproved tool accepted"); }
        catch (SecurityException expected) { }
    }
}
