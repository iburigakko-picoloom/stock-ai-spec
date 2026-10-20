package jp.stockai.app;

import android.content.Context;
import java.io.IOException;
import java.time.Instant;
import java.util.HashSet;
import java.util.Set;
import org.json.JSONObject;

/** Durable provider-call receipts; acknowledged attempts can never be sent twice. */
final class ResearchJournal {
    private static final Set<String> active = new HashSet<>();
    private final NativeSecrets secrets;

    ResearchJournal(Context context) { secrets = new NativeSecrets(context); }
    private String key(String id) throws IOException {
        if (id == null || !id.matches("[0-9a-f]{32}")) throw new IOException("INVALID_ATTEMPT_ID");
        return "research-" + id;
    }
    private JSONObject inspect(String id) throws Exception {
        String saved = secrets.read(key(id));
        if (saved == null) return new JSONObject().put("attemptId", id).put("state", "missing");
        JSONObject result = new JSONObject(saved);
        if (result.optString("state").equals("running") && !active.contains(id))
            result.put("state", "interrupted").put("errorCode", "PROCESS_INTERRUPTED");
        return result;
    }
    JSONObject current(String id) throws Exception {
        synchronized (active) { return inspect(id); }
    }
    JSONObject begin(String id, String digest, String model, String effort) throws Exception {
        synchronized (active) {
            JSONObject previous = inspect(id);
            if (!previous.getString("state").equals("missing")) {
                if (previous.has("requestSha256") && (
                        !previous.optString("requestSha256").equals(digest)
                        || !previous.optString("model").equals(model)
                        || !previous.optString("effort").equals(effort)))
                    throw new IOException("ATTEMPT_REQUEST_CHANGED");
                return previous.put("dispatch", false);
            }
            if (digest == null || !digest.matches("[0-9a-f]{64}") || model == null || effort == null)
                throw new IOException("INVALID_RESEARCH_REQUEST");
            JSONObject receipt = new JSONObject().put("attemptId", id).put("requestSha256", digest)
                .put("model", model).put("effort", effort).put("state", "running")
                .put("startedAt", Instant.now().toString());
            secrets.write(key(id), receipt.toString());
            active.add(id);
            return receipt.put("dispatch", true);
        }
    }
    JSONObject recover(String id) throws Exception {
        synchronized (active) {
            JSONObject current = inspect(id);
            if (current.getString("state").equals("missing")) {
                current.put("state", "interrupted").put("errorCode", "EXECUTION_NOT_DISPATCHED");
                secrets.write(key(id), current.toString());
            }
            return current;
        }
    }
    JSONObject complete(String id, JSONObject response) throws Exception {
        synchronized (active) {
            JSONObject receipt = inspect(id);
            if (!active.contains(id) || !receipt.getString("state").equals("running"))
                throw new IOException("RESEARCH_NOT_RUNNING");
            receipt.put("state", "completed").put("response", response).put("completedAt", Instant.now().toString());
            secrets.write(key(id), receipt.toString());
            return receipt;
        }
    }
    void fail(String id, String code) throws Exception {
        synchronized (active) {
            JSONObject receipt = inspect(id);
            // If persistence failed after receiving output, preserve any saved
            // completed response so recovery can still commit it to the ledger.
            if (receipt.optString("state").equals("completed")) return;
            receipt.remove("response"); receipt.put("state", "failed").put("errorCode", code)
                .put("completedAt", Instant.now().toString());
            secrets.write(key(id), receipt.toString());
        }
    }
    void release(String id) { synchronized (active) { active.remove(id); } }
    void acknowledge(String id) throws Exception {
        synchronized (active) {
            if (active.contains(id)) throw new IOException("RESEARCH_STILL_RUNNING");
            JSONObject receipt = inspect(id);
            if (receipt.optString("state").equals("completed")) {
                receipt.remove("response"); receipt.put("state", "acknowledged");
                secrets.write(key(id), receipt.toString());
            }
        }
    }
}
