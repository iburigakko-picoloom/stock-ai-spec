package jp.stockai.app;

import java.io.IOException;
import java.time.Instant;
import java.util.function.BooleanSupplier;
import java.util.function.Supplier;
import org.json.JSONArray;
import org.json.JSONObject;

/** One provider phase per scheduled slice, reusing the shared immutable research protocol. */
final class DailyResearch {
    interface Core { JSONObject request(String method, String path, String body) throws Exception; }
    interface Provider {
        JSONObject selection() throws Exception;
        JSONObject respond(String id, String request, String digest, String model, String effort) throws Exception;
        JSONObject recover(String id) throws Exception;
        void acknowledge(String id) throws Exception;
    }
    interface Journal {
        JSONObject read(String day) throws Exception;
        void write(String day, JSONObject value) throws Exception;
    }
    final Core core;
    final Provider provider;
    final Journal journal;
    final DailyPipeline.Progress progress;
    final BooleanSupplier stopped;
    final Supplier<Instant> clock;
    static final String PROMPT = "independent-company-research-v1";

    DailyResearch(Core core, Provider provider, Journal journal, DailyPipeline.Progress progress,
            BooleanSupplier stopped, Supplier<Instant> clock) {
        this.core = core; this.provider = provider; this.journal = journal;
        this.progress = progress; this.stopped = stopped; this.clock = clock;
    }
    void check() throws InterruptedException { if (stopped.getAsBoolean() || Thread.currentThread().isInterrupted()) throw new InterruptedException(); }
    JSONObject api(String method, String path, JSONObject body) throws Exception {
        check(); JSONObject reply = core.request(method, "/api/v1/" + path, body == null ? "null" : body.toString()); check();
        if (reply.getInt("status") != 200) throw new IOException("RESEARCH_CORE_NOT_COMMITTED");
        return reply.getJSONObject("body");
    }
    void attention(String day, String code) throws Exception {
        progress.state("research_attention", day);
        progress.notice(day + ":research:" + code, "数値判定は保存済みです。ChatGPT調査の未完了状態を確認してください。");
    }
    boolean step() throws Exception {
        check(); String day = clock.get().atZone(DailyPipeline.JST).toLocalDate().toString();
        JSONObject plan = api("GET", "mobile/research/plan", null);
        if (!day.equals(plan.getString("day"))) return true;
        JSONArray symbols = plan.getJSONArray("symbols");
        if (symbols.length() == 0) { progress.state("research_complete", day); return false; }
        JSONObject chosen;
        try { chosen = provider.selection(); }
        catch (Exception error) { attention(day, ChatGPTClient.failureCode(error)); return false; }
        if (chosen.optString("model").isEmpty()) { attention(day, "MODEL_SELECTION_REQUIRED"); return false; }
        JSONObject batch = journal.read(day);
        if (batch == null) {
            batch = new JSONObject().put("day", day).put("snapshot_id", plan.getString("snapshot_id"))
                .put("symbols", symbols).put("model", chosen.getString("model")).put("effort", chosen.getString("effort"))
                .put("account_key", chosen.getString("account_key")).put("prompt_version", PROMPT)
                .put("runs", new JSONObject()).put("done", new JSONArray()).put("created_at", clock.get().toString());
            journal.write(day, batch);
        }
        if (!batch.getString("snapshot_id").equals(plan.getString("snapshot_id"))
                || !batch.getJSONArray("symbols").toString().equals(symbols.toString())
                || !batch.getString("model").equals(chosen.getString("model"))
                || !batch.getString("effort").equals(chosen.getString("effort"))
                || !batch.getString("account_key").equals(chosen.getString("account_key"))
                || !PROMPT.equals(batch.getString("prompt_version"))) {
            attention(day, "RESEARCH_SELECTION_CHANGED"); return false;
        }
        java.util.Set<String> done = new java.util.HashSet<>();
        JSONArray finished = batch.getJSONArray("done");
        for (int i = 0; i < finished.length(); i++) done.add(finished.getString(i));
        JSONObject blocked = batch.optJSONObject("blocked");
        if (blocked == null) { blocked = new JSONObject(); batch.put("blocked", blocked); }
        if (!done.isEmpty() || blocked.length() > 0) {
            JSONArray saved = api("GET", "research/" + batch.getString("snapshot_id"), null).getJSONArray("runs");
            java.util.Set<String> published = new java.util.HashSet<>();
            for (int i = 0; i < saved.length(); i++) {
                JSONObject value = saved.getJSONObject(i);
                String symbol = value.getJSONObject("run").getJSONObject("context").getString("symbol");
                if (value.getJSONObject("run").getString("run_id").equals(batch.getJSONObject("runs").optString(symbol)) && !value.isNull("record"))
                    published.add(symbol);
            }
            if (!published.containsAll(done)) { attention(day, "RESEARCH_RECORD_MISSING"); return false; }
            for (String symbol : published) if (blocked.has(symbol)) {
                blocked.remove(symbol); if (done.add(symbol)) finished.put(symbol);
                journal.write(day, batch);
            }
        }
        for (int i = 0; i < symbols.length(); i++) {
            String symbol = symbols.getString(i); if (done.contains(symbol) || blocked.has(symbol)) continue;
            check();
            if (!day.equals(clock.get().atZone(DailyPipeline.JST).toLocalDate().toString())) return false;
            progress.state("research_running", day);
            JSONObject runs = batch.getJSONObject("runs");
            String run = runs.optString(symbol);
            if (run.isEmpty()) {
                JSONObject configuration = new JSONObject().put("model", batch.getString("model"))
                    .put("effort", batch.getString("effort")).put("prompt_version", PROMPT);
                JSONObject started = api("POST", "research/" + batch.getString("snapshot_id") + "/" + symbol + "/start",
                    new JSONObject().put("configuration", configuration));
                run = started.getJSONObject("run").getString("run_id");
                runs.put(symbol, run); journal.write(day, batch);
            }
            JSONObject claim = api("POST", "research/" + run + "/claim", new JSONObject().put("retry", false));
            JSONArray prior = claim.getJSONArray("attempts");
            for (int n = 0; n < prior.length(); n++) {
                JSONObject item = prior.getJSONObject(n);
                if (item.getString("status").equals("completed")) {
                    try { provider.acknowledge(item.getString("attempt_id")); }
                    catch (Exception ignored) { /* Retain and reconcile the same durable response later. */ }
                }
            }
            String state = claim.getString("state");
            if (state.equals("completed")) { finished.put(symbol); journal.write(day, batch); return true; }
            if (state.equals("blocked")) { attention(day, "RESEARCH_RETRY_REQUIRES_OWNER"); return false; }
            JSONObject attempt = claim.getJSONObject("attempt"); String id = attempt.getString("attempt_id");
            JSONObject execution;
            if (state.equals("running")) execution = provider.recover(id);
            else if (state.equals("ready")) {
                check();
                try {
                    execution = provider.respond(id, claim.getString("request_json"), claim.getString("request_sha256"),
                        batch.getString("model"), batch.getString("effort"));
                } catch (Exception error) {
                    if (error instanceof InterruptedException) throw error;
                    execution = provider.recover(id); // A timeout never proves non-dispatch.
                }
                if (execution.has("requestSha256") && !execution.getString("requestSha256").equals(claim.getString("request_sha256")))
                    throw new IOException("ATTEMPT_REQUEST_CHANGED");
            } else throw new IOException("INVALID_RESEARCH_CLAIM");
            check();
            if (!id.equals(execution.getString("attemptId"))) throw new IOException("INVALID_ATTEMPT_ID");
            String outcome = execution.getString("state");
            if (outcome.equals("running")) return false;
            JSONObject receipt = new JSONObject();
            if (outcome.equals("completed")) receipt.put("response", execution.getJSONObject("response"))
                .put("started_at", execution.getString("startedAt")).put("completed_at", execution.getString("completedAt"));
            else receipt.put("error_code", execution.optString("errorCode", "EXECUTION_RECEIPT_UNAVAILABLE"))
                .put("interrupted", !outcome.equals("failed"));
            JSONObject saved = api("POST", "research/" + id + "/receipt", receipt);
            boolean accepted = false; String errorCode = "RESEARCH_INCOMPLETE";
            JSONArray attempts = saved.getJSONArray("attempts");
            for (int n = 0; n < attempts.length(); n++) {
                JSONObject item = attempts.getJSONObject(n);
                if (id.equals(item.getString("attempt_id"))) {
                    accepted = item.getString("status").equals("completed");
                    errorCode = item.optString("error_code", "RESEARCH_INCOMPLETE");
                }
            }
            if (!accepted) {
                if (errorCode.equals("INVALID_RESEARCH_RESPONSE")) {
                    blocked.put(symbol, errorCode); journal.write(day, batch); return true;
                }
                attention(day, errorCode); return false;
            }
            try { provider.acknowledge(id); } catch (Exception ignored) { /* Shared commit already succeeded. */ }
            if (!saved.isNull("record")) { finished.put(symbol); journal.write(day, batch); }
            return true;
        }
        if (blocked.length() > 0) { attention(day, "RESEARCH_INCOMPLETE"); return false; }
        progress.state("research_complete", day);
        progress.notice(day + ":research-complete:" + batch.getString("snapshot_id"), "今日の数値判定とChatGPT調査を保存しました。");
        return false;
    }
}
