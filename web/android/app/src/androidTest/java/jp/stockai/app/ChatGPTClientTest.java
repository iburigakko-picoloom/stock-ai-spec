package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class ChatGPTClientTest {
    @Test public void applicationClientReusesCompletedReceiptWithoutCredentialOrProviderRequest() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        ChatGPTClient client = ChatGPTClient.get(context);
        assertSame(client, ChatGPTClient.get(context.getApplicationContext()));
        String id = UUID.randomUUID().toString().replace("-", ""), digest = new String(new char[64]).replace('\0', 'a');
        ResearchJournal journal = new ResearchJournal(context);
        try {
            journal.begin(id, digest, "fixture-model", "high");
            JSONObject complete = journal.complete(id, new JSONObject().put("fixture", true));
            journal.release(id);
            JSONObject result = client.respond(id, "never dispatched", digest, "fixture-model", "high").get(10, TimeUnit.SECONDS);
            assertEquals(complete.toString(), result.toString());
            journal.acknowledge(id);
            assertEquals("acknowledged", client.respond(id, "never dispatched", digest, "fixture-model", "high").get(10, TimeUnit.SECONDS).getString("state"));
        } finally { journal.release(id); new NativeSecrets(context).remove("research-" + id); }
    }
    @Test public void rejectedCompetingRequestCannotReleaseAnAcceptedReservation() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        String id = UUID.randomUUID().toString().replace("-", ""), digest = new String(new char[64]).replace('\0', 'a');
        ResearchJournal journal = new ResearchJournal(context);
        try {
            journal.begin(id, digest, "fixture-model", "high");
            try { ChatGPTClient.get(context).respond(id, "not sent", new String(new char[64]).replace('\0', 'b'), "fixture-model", "high").get(10, TimeUnit.SECONDS); fail("changed request accepted"); }
            catch (java.util.concurrent.ExecutionException expected) { assertEquals("ATTEMPT_REQUEST_CHANGED", expected.getCause().getMessage()); }
            assertEquals("running", journal.current(id).getString("state"));
        } finally { journal.release(id); new NativeSecrets(context).remove("research-" + id); }
    }
}
