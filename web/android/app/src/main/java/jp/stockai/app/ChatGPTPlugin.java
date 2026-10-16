package jp.stockai.app;

import android.content.Intent;
import android.net.Uri;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONArray;
import org.json.JSONObject;

/** Public OAuth client. Tokens never cross the Capacitor bridge. */
@CapacitorPlugin(name = "StockAIChatGPT")
public class ChatGPTPlugin extends Plugin {
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final ExecutorService researchExecutor = Executors.newSingleThreadExecutor();
    private volatile ServerSocket pending;
    private volatile String connectionState = "disconnected";
    private JSONArray catalog = new JSONArray();

    private NativeSecrets secrets() { return new NativeSecrets(getContext()); }
    private JSONObject credentials() throws Exception {
        String saved = secrets().read("credentials");
        return saved == null ? null : new JSONObject(saved);
    }
    private JSONObject selection() throws Exception {
        String saved = secrets().read("selection");
        return saved == null ? new JSONObject().put("model", "").put("effort", "medium") : new JSONObject(saved);
    }
    private JSObject status() throws Exception {
        JSONObject saved = credentials();
        return new JSObject().put("connected", saved != null)
            .put("planEnabled", saved != null && ChatGPTProtocol.hasPlanPermission(saved))
            .put("accountLabel", saved == null ? JSONObject.NULL : saved.optString("label", "ChatGPT"))
            .put("state", pending == null ? (saved == null ? "disconnected" : "connected") : connectionState)
            .put("selection", selection()).put("models", catalog).put("apiFallback", false);
    }
    interface Operation { void run() throws Exception; }
    private void execute(PluginCall call, Operation operation) {
        execute(call, operation, executor);
    }
    private void execute(PluginCall call, Operation operation, ExecutorService target) {
        target.execute(() -> {
            try { operation.run(); }
            catch (Exception error) {
                String code = error.getMessage();
                if (code == null || !code.matches("[A-Z_a-z0-9]{1,100}")) code = "CONNECTION_FAILED";
                call.reject("ChatGPT連携を完了できません（" + code + "）。接続・利用権限・選択した設定を確認してください。", code);
            }
        });
    }
    @PluginMethod public void getStatus(PluginCall call) {
        // Status and cancellation stay reachable while the authorization thread waits.
        try { call.resolve(status()); }
        catch (Exception error) { call.reject("保存済みの連携状態を確認できません。", "CREDENTIAL_READ_FAILED"); }
    }

    static String form(Map<String, String> values) throws Exception {
        StringBuilder output = new StringBuilder();
        for (Map.Entry<String, String> entry : values.entrySet()) {
            if (output.length() > 0) output.append('&');
            output.append(URLEncoder.encode(entry.getKey(), "UTF-8")).append('=')
                .append(URLEncoder.encode(entry.getValue(), "UTF-8"));
        }
        return output.toString();
    }
    static JSONObject fetch(String url, String post, String bearer) throws Exception {
        if (!Arrays.asList(ChatGPTProtocol.ISSUER + "/.well-known/jwks.json",
                ChatGPTProtocol.ISSUER + "/api/accounts/oauth/token", ChatGPTProtocol.RESOURCE + "/models").contains(url))
            throw new SecurityException("ENDPOINT_NOT_ALLOWED");
        HttpURLConnection connection = StockAIPlugin.connection(url);
        try {
            if (bearer != null) connection.setRequestProperty("Authorization", "Bearer " + bearer);
            if (post != null) {
                connection.setRequestMethod("POST"); connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
                try (OutputStream output = connection.getOutputStream()) { output.write(post.getBytes(StandardCharsets.UTF_8)); }
            }
            int code = connection.getResponseCode();
            if (code != 200) throw new IOException("HTTP_" + code);
            return new JSONObject(new String(StockAIPlugin.read(connection.getInputStream(), 4 * 1024 * 1024), StandardCharsets.UTF_8));
        } finally { connection.disconnect(); }
    }
    private JSONObject exchange(Map<String, String> values) throws Exception {
        JSONObject result = fetch(ChatGPTProtocol.ISSUER + "/api/accounts/oauth/token", form(values), null);
        if (!"Bearer".equalsIgnoreCase(result.getString("token_type"))
                || result.getString("access_token").isEmpty() || result.getLong("expires_in") <= 0)
            throw new SecurityException("INVALID_TOKEN_RESPONSE");
        result.put("expires_at", System.currentTimeMillis() / 1000 + result.getLong("expires_in"));
        return result;
    }

    @PluginMethod public void signIn(PluginCall call) {
        synchronized (this) {
            if (pending != null) { call.reject("ログイン画面を確認してください。", "AUTHORIZATION_PENDING"); return; }
            try {
                pending = new ServerSocket();
                pending.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), 0), 4);
                pending.setSoTimeout(1000); connectionState = "authorizing";
            } catch (Exception error) { closePending(); call.reject("認証の受取を開始できません。", "CALLBACK_UNAVAILABLE"); return; }
        }
        final ServerSocket listener = pending;
        execute(call, () -> {
            try {
                JSONObject previous = credentials();
                String host = secrets().read("host");
                if (host == null) { host = "urn:uuid:" + UUID.randomUUID(); secrets().write("host", host); }
                String client = previous == null ? null : previous.getString("client_id");
                String redirect = "http://127.0.0.1:" + listener.getLocalPort() + "/auth/callback";
                String state = ChatGPTProtocol.random(), nonce = ChatGPTProtocol.random(), verifier = ChatGPTProtocol.random();
                Map<String, String> query = new LinkedHashMap<>();
                query.put("client_id", client == null ? "dynamic_agent_client" : client);
                if (client == null) query.put("agent_name_hint", "StockAI");
                query.put("ext_agent_host_id", host); query.put("response_type", "code");
                query.put("redirect_uri", redirect); query.put("scope", ChatGPTProtocol.SCOPES);
                query.put("resource", ChatGPTProtocol.RESOURCE); query.put("state", state); query.put("nonce", nonce);
                query.put("code_challenge_method", "S256"); query.put("code_challenge", ChatGPTProtocol.challenge(verifier));
                if (previous != null) query.put("id_token_hint", previous.getString("id_token"));
                if (previous != null && !ChatGPTProtocol.hasPlanPermission(previous)) query.put("prompt", "consent");
                String url = ChatGPTProtocol.ISSUER + "/api/accounts/authorize?" + form(query);
                getActivity().runOnUiThread(() -> {
                    try { getActivity().startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); }
                    catch (RuntimeException error) { closePending(); }
                });
                Map<String, String> callback = awaitCallback(listener, state, client);
                Map<String, String> body = new LinkedHashMap<>();
                body.put("grant_type", "authorization_code"); body.put("client_id", callback.get("client_id"));
                body.put("code", callback.get("code")); body.put("code_verifier", verifier);
                body.put("redirect_uri", redirect); body.put("resource", ChatGPTProtocol.RESOURCE);
                JSONObject tokens = exchange(body);
                JSONObject claims = ChatGPTProtocol.validateIdToken(tokens.getString("id_token"),
                    fetch(ChatGPTProtocol.ISSUER + "/.well-known/jwks.json", null, null),
                    callback.get("client_id"), nonce, previous == null ? null : previous.getString("subject"),
                    System.currentTimeMillis() / 1000);
                tokens.put("client_id", callback.get("client_id")).put("subject", claims.getString("sub"))
                    .put("label", claims.optString("email", "ChatGPT"));
                if (!tokens.has("refresh_token")) throw new SecurityException("OFFLINE_PERMISSION_MISSING");
                secrets().write("credentials", tokens.toString());
                catalog = new JSONArray();
            } finally { closePending(); }
            call.resolve(status());
        });
    }

    private Map<String, String> awaitCallback(ServerSocket listener, String state, String client) throws Exception {
        long deadline = android.os.SystemClock.elapsedRealtime() + 300000;
        while (!listener.isClosed() && android.os.SystemClock.elapsedRealtime() < deadline) {
            try (Socket socket = listener.accept()) {
                socket.setSoTimeout(3000);
                if (!socket.getInetAddress().isLoopbackAddress()) continue;
                BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.US_ASCII));
                String line = reader.readLine();
                if (line == null || line.length() > 8192) continue;
                String[] request = line.split(" ");
                if (request.length != 3 || !request[0].equals("GET") || !request[2].equals("HTTP/1.1")) continue;
                boolean hostMatches = false; int count = 0;
                while ((line = reader.readLine()) != null && !line.isEmpty()) {
                    if (++count > 32 || line.length() > 8192) throw new SecurityException("CALLBACK_LIMIT");
                    if (line.toLowerCase(java.util.Locale.ROOT).startsWith("host:"))
                        hostMatches = line.substring(5).trim().equals("127.0.0.1:" + listener.getLocalPort());
                }
                if (!hostMatches) continue;
                try {
                    Map<String, String> callback = ChatGPTProtocol.callback(request[1], state, client);
                    reply(socket, true); return callback;
                } catch (SecurityException error) { reply(socket, false); }
                catch (IOException error) { reply(socket, false); throw error; }
            } catch (SocketTimeoutException ignored) { /* bounded listener; cancellation closes it */ }
        }
        throw new IOException("AUTHORIZATION_CANCELLED_OR_EXPIRED");
    }
    private void reply(Socket socket, boolean success) throws Exception {
        byte[] content = (success ? "StockAI: authorization received. Return to the app." : "StockAI: authorization was not accepted. Return to the app.")
            .getBytes(StandardCharsets.UTF_8);
        String header = "HTTP/1.1 " + (success ? "200 OK" : "400 Bad Request")
            + "\r\nContent-Type: text/plain; charset=utf-8\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: " + content.length + "\r\n\r\n";
        socket.getOutputStream().write(header.getBytes(StandardCharsets.US_ASCII));
        socket.getOutputStream().write(content); socket.getOutputStream().flush();
    }
    private synchronized void closePending() {
        if (pending != null) { try { pending.close(); } catch (IOException ignored) { } pending = null; }
    }
    @PluginMethod public void cancelSignIn(PluginCall call) { closePending(); call.resolve(); }
    @PluginMethod public void signOut(PluginCall call) {
        closePending(); execute(call, () -> { secrets().remove("credentials"); secrets().remove("selection"); catalog = new JSONArray(); call.resolve(status()); });
    }

    private JSONObject activeCredentials() throws Exception {
        synchronized (ChatGPTPlugin.class) {
        JSONObject saved = credentials();
        if (saved == null) throw new IOException("SIGN_IN_REQUIRED");
        if (!ChatGPTProtocol.hasPlanPermission(saved)) throw new IOException("PLAN_PERMISSION_REQUIRED");
        if (saved.getLong("expires_at") > System.currentTimeMillis() / 1000 + 60) return saved;
        Map<String, String> body = new LinkedHashMap<>(); body.put("grant_type", "refresh_token");
        body.put("client_id", saved.getString("client_id")); body.put("refresh_token", saved.getString("refresh_token"));
        body.put("resource", ChatGPTProtocol.RESOURCE);
        JSONObject renewed = exchange(body);
        if (renewed.has("id_token")) ChatGPTProtocol.validateIdToken(renewed.getString("id_token"),
            fetch(ChatGPTProtocol.ISSUER + "/.well-known/jwks.json", null, null), saved.getString("client_id"),
            null, saved.getString("subject"), System.currentTimeMillis() / 1000);
        if (!renewed.has("refresh_token")) throw new SecurityException("REFRESH_TOKEN_MISSING");
        if (!renewed.has("scope")) renewed.put("scope", saved.getString("scope"));
        for (java.util.Iterator<String> keys = renewed.keys(); keys.hasNext();) {
            String key = keys.next(); saved.put(key, renewed.get(key));
        }
        if (!ChatGPTProtocol.hasPlanPermission(saved)) throw new IOException("PLAN_PERMISSION_REQUIRED");
        secrets().write("credentials", saved.toString()); return saved;
        }
    }

    private static String failureCode(Exception error) {
        String code = error.getMessage();
        return code != null && code.matches("[A-Za-z0-9_]{1,100}") ? code : "CONNECTION_FAILED";
    }
    private static String executionId(PluginCall call) throws IOException {
        String id = call.getString("attemptId");
        if (id == null || !id.matches("[0-9a-f]{32}")) throw new IOException("INVALID_ATTEMPT_ID");
        return id;
    }
    private static JSONObject infer(JSONObject tokens, JSONObject request) throws Exception {
        HttpURLConnection connection = StockAIPlugin.connection(ChatGPTProtocol.RESOURCE + "/responses");
        try {
            connection.setReadTimeout(300000); connection.setRequestMethod("POST"); connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setRequestProperty("Accept", "text/event-stream");
            connection.setRequestProperty("Authorization", "Bearer " + tokens.getString("access_token"));
            try (OutputStream output = connection.getOutputStream()) { output.write(request.toString().getBytes(StandardCharsets.UTF_8)); }
            int code = connection.getResponseCode(); if (code != 200) throw new IOException("HTTP_" + code);
            try (InputStreamReader input = new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8)) {
                return ChatGPTProtocol.readResponse(input);
            }
        } finally { connection.disconnect(); }
    }
    @PluginMethod public void getExecution(PluginCall call) {
        // Never queue an observation behind a long-running request.
        try { call.resolve(JSObject.fromJSONObject(new ResearchJournal(getContext()).current(executionId(call)))); }
        catch (Exception error) { call.reject("調査の実行状態を確認できません。", failureCode(error)); }
    }
    @PluginMethod public void recoverExecution(PluginCall call) {
        try {
            call.resolve(JSObject.fromJSONObject(new ResearchJournal(getContext()).recover(executionId(call))));
        } catch (Exception error) { call.reject("調査の実行状態を回復できません。", failureCode(error)); }
    }
    @PluginMethod public void forgetExecution(PluginCall call) { execute(call, () -> {
        new ResearchJournal(getContext()).acknowledge(executionId(call)); call.resolve();
    }); }
    @PluginMethod public void respond(PluginCall call) {
        final String id;
        final ResearchJournal journal = new ResearchJournal(getContext());
        try {
            id = executionId(call);
            JSONObject previous = journal.begin(id, call.getString("requestSha256"), call.getString("model"), call.getString("effort"));
            boolean dispatch = previous.getBoolean("dispatch"); previous.remove("dispatch");
            if (!dispatch) { call.resolve(JSObject.fromJSONObject(previous)); return; }
        } catch (Exception error) { call.reject("調査を開始できません。", failureCode(error)); return; }
        try { execute(call, () -> {
            String digest = call.getString("requestSha256");
            String model = call.getString("model"), effort = call.getString("effort");
            try {
                JSONObject request = ChatGPTProtocol.researchRequest(call.getString("requestJson"), digest, model, effort);
                JSONObject chosen = selection();
                if (!chosen.getString("model").equals(model) || !chosen.getString("effort").equals(effort))
                    throw new IOException("MODEL_SELECTION_CHANGED");
                JSONObject tokens = activeCredentials();
                JSONObject response = infer(tokens, request);
                call.resolve(JSObject.fromJSONObject(journal.complete(id, response)));
            } catch (Exception error) {
                journal.fail(id, failureCode(error));
                throw error;
            } finally { journal.release(id); }
        }, researchExecutor); }
        catch (java.util.concurrent.RejectedExecutionException error) {
            journal.release(id); call.reject("調査の実行環境が停止しました。", "PROCESS_INTERRUPTED");
        }
    }
    @PluginMethod public void listModels(PluginCall call) { execute(call, () -> {
        JSONObject tokens = activeCredentials();
        JSONArray source = fetch(ChatGPTProtocol.RESOURCE + "/models", null, tokens.getString("access_token")).getJSONArray("models");
        JSONArray models = new JSONArray();
        for (int i = 0; i < source.length(); i++) {
            JSONObject item = source.getJSONObject(i);
            if (!item.optString("visibility").equals("list")) continue;
            String slug = item.getString("slug");
            if (!slug.matches("[a-zA-Z0-9._:-]{1,160}")) throw new SecurityException("INVALID_MODEL_CATALOG");
            models.put(new JSONObject().put("slug", slug).put("displayName", item.getString("display_name")));
        }
        catalog = models; call.resolve(status());
    }); }
    @PluginMethod public void saveSelection(PluginCall call) { execute(call, () -> {
        String model = call.getString("model"), effort = call.getString("effort");
        activeCredentials(); boolean found = false;
        for (int i = 0; i < catalog.length(); i++) found |= catalog.getJSONObject(i).getString("slug").equals(model);
        if (!found || !Arrays.asList("low", "medium", "high", "xhigh", "max").contains(effort))
            throw new IOException("MODEL_SELECTION_INVALID");
        secrets().write("selection", new JSONObject().put("model", model).put("effort", effort).toString());
        call.resolve(status());
    }); }

    @PluginMethod public void probe(PluginCall call) { execute(call, () -> {
        JSONObject tokens = activeCredentials(), chosen = selection();
        if (chosen.optString("model").isEmpty()) throw new IOException("MODEL_SELECTION_REQUIRED");
        JSONObject request = new JSONObject().put("model", chosen.getString("model"))
            .put("reasoning", new JSONObject().put("effort", chosen.getString("effort")))
            .put("store", false).put("stream", true)
            .put("tools", new JSONArray().put(new JSONObject().put("type", "web_search")))
            .put("input", new JSONArray().put(new JSONObject().put("role", "user").put("content",
                "接続確認です。日本取引所グループの公式サイトをWeb検索し、事業を日本語1文で説明して出典URLを示してください。投資判断は不要です。")));
        JSONObject result = infer(tokens, request);
            JSONArray outputs = result.getJSONArray("output"), citations = new JSONArray();
            StringBuilder text = new StringBuilder(); boolean searched = false;
            for (int i = 0; i < outputs.length(); i++) {
                JSONObject item = outputs.getJSONObject(i);
                if (item.optString("type").equals("web_search_call") && item.optString("status").equals("completed")) searched = true;
                JSONArray content = item.optJSONArray("content"); if (content == null) continue;
                for (int j = 0; j < content.length(); j++) {
                    JSONObject part = content.getJSONObject(j);
                    if (part.optString("type").equals("output_text")) text.append(part.getString("text"));
                    JSONArray annotations = part.optJSONArray("annotations"); if (annotations == null) continue;
                    for (int k = 0; k < annotations.length(); k++) {
                        JSONObject citation = annotations.getJSONObject(k);
                        if (citation.optString("type").equals("url_citation")
                                && citation.optString("url").startsWith("https://"))
                            citations.put(new JSONObject().put("url", citation.getString("url")).put("title", citation.optString("title", "出典")));
                    }
                }
            }
            if (!searched || citations.length() == 0 || text.length() == 0) throw new IOException("SEARCH_OR_CITATION_UNCONFIRMED");
            call.resolve(new JSObject().put("text", text.toString()).put("citations", citations)
                .put("model", chosen.getString("model")).put("effort", chosen.getString("effort"))
                .put("completedAt", java.time.Instant.now().toString()));
    }); }

    @Override protected void handleOnDestroy() {
        closePending(); executor.shutdownNow();
        // Finish already accepted calls and keep their receipts if only the
        // Activity goes away. Process death is recovered by ResearchJournal.
        researchExecutor.shutdown();
    }
}
