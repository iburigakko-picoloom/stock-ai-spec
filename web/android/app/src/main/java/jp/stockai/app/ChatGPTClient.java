package jp.stockai.app;

import android.content.Context;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONObject;

/** Application-owned ChatGPT transport. No Activity, browser or paid-key fallback. */
final class ChatGPTClient {
    private static final Map<String, ChatGPTClient> clients = new HashMap<>();
    private static final Set<HttpURLConnection> responseConnections = new HashSet<>();
    private static final java.util.concurrent.ScheduledExecutorService deadlines = Executors.newSingleThreadScheduledExecutor();
    private final Context context;
    private final ExecutorService researchQueue = Executors.newSingleThreadExecutor();
    private final AtomicInteger queued = new AtomicInteger();
    static synchronized ChatGPTClient get(Context context) {
        String key = context.getApplicationContext().getFilesDir().getAbsolutePath();
        ChatGPTClient result = clients.get(key);
        if (result == null) { result = new ChatGPTClient(context); clients.put(key, result); }
        return result;
    }
    private ChatGPTClient(Context context) { this.context = context.getApplicationContext(); }
    private NativeSecrets secrets() { return new NativeSecrets(context); }
    ChatGPTSession session() {
        return new ChatGPTSession(context, new ChatGPTSession.Remote() {
            @Override public JSONObject refresh(JSONObject saved) throws Exception {
                Map<String, String> body = new LinkedHashMap<>(); body.put("grant_type", "refresh_token");
                body.put("client_id", saved.getString("client_id")); body.put("refresh_token", saved.getString("refresh_token"));
                body.put("resource", ChatGPTProtocol.RESOURCE); return exchange(body);
            }
            @Override public JSONObject jwks() throws Exception {
                return fetch(ChatGPTProtocol.ISSUER + "/.well-known/jwks.json", null, null);
            }
            @Override public void revoke(JSONObject saved) throws Exception { revokeSession(saved); }
        });
    }
    JSONObject selection() throws Exception {
        String saved = secrets().read("selection");
        return saved == null ? new JSONObject().put("model", "").put("effort", "medium") : new JSONObject(saved);
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
            if (code != 200) throw providerFailure(connection, code);
            return new JSONObject(new String(StockAIPlugin.read(connection.getInputStream(), 4 * 1024 * 1024), StandardCharsets.UTF_8));
        } finally { connection.disconnect(); }
    }
    private static ChatGPTProtocol.ProviderFailure providerFailure(HttpURLConnection connection, int code) throws Exception {
        String body = "";
        try {
            if (connection.getErrorStream() != null) body = new String(
                StockAIPlugin.read(connection.getErrorStream(), 65536), StandardCharsets.UTF_8);
        } catch (Exception unreadable) { /* Retain the known HTTP status, never a partial message. */ }
        return ChatGPTProtocol.failure(code, body, connection.getHeaderField("x-request-id"));
    }
    static void revokeSession(JSONObject saved) throws Exception {
        HttpURLConnection discovery = StockAIPlugin.connection(ChatGPTProtocol.ISSUER + "/.well-known/openid-configuration");
        String endpoint;
        try {
            discovery.setConnectTimeout(5000); discovery.setReadTimeout(5000);
            int code = discovery.getResponseCode(); if (code != 200) throw providerFailure(discovery, code);
            JSONObject document = new JSONObject(new String(StockAIPlugin.read(discovery.getInputStream(), 65536), StandardCharsets.UTF_8));
            endpoint = ChatGPTProtocol.revocationEndpoint(document);
        } finally { discovery.disconnect(); }
        Map<String, String> values = new LinkedHashMap<>();
        values.put("client_id", saved.getString("client_id")); values.put("token", saved.getString("refresh_token"));
        values.put("token_type_hint", "refresh_token");
        HttpURLConnection connection = StockAIPlugin.connection(endpoint);
        try {
            connection.setConnectTimeout(5000); connection.setReadTimeout(5000);
            connection.setRequestMethod("POST"); connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
            try (OutputStream output = connection.getOutputStream()) { output.write(form(values).getBytes(StandardCharsets.UTF_8)); }
            int code = connection.getResponseCode(); if (code != 200) throw providerFailure(connection, code);
        } finally { connection.disconnect(); }
    }
    JSONObject exchange(Map<String, String> values) throws Exception {
        JSONObject result = fetch(ChatGPTProtocol.ISSUER + "/api/accounts/oauth/token", form(values), null);
        if (!"Bearer".equalsIgnoreCase(result.getString("token_type"))
                || result.getString("access_token").isEmpty() || result.getLong("expires_in") <= 0)
            throw new SecurityException("INVALID_TOKEN_RESPONSE");
        result.put("expires_at", System.currentTimeMillis() / 1000 + result.getLong("expires_in"));
        return result;
    }

    JSONObject infer(JSONObject tokens, JSONObject request) throws Exception {
        HttpURLConnection connection = StockAIPlugin.connection(ChatGPTProtocol.RESOURCE + "/responses");
        java.util.concurrent.atomic.AtomicBoolean expired = new java.util.concurrent.atomic.AtomicBoolean();
        java.util.concurrent.ScheduledFuture<?> deadline = deadlines.schedule(() -> {
            expired.set(true); connection.disconnect();
        }, 315, java.util.concurrent.TimeUnit.SECONDS);
        try {
            synchronized (responseConnections) {
                if (!session().canUse(tokens)) throw new IOException("SIGN_IN_REQUIRED");
                responseConnections.add(connection);
            }
            connection.setReadTimeout(300000); connection.setRequestMethod("POST"); connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setRequestProperty("Accept", "text/event-stream");
            connection.setRequestProperty("Authorization", "Bearer " + tokens.getString("access_token"));
            try (OutputStream output = connection.getOutputStream()) { output.write(request.toString().getBytes(StandardCharsets.UTF_8)); }
            int code = connection.getResponseCode(); if (code != 200) throw providerFailure(connection, code);
            try (InputStreamReader input = new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8)) {
                JSONObject result = ChatGPTProtocol.readResponse(input);
                if (expired.get()) throw new IOException("RESEARCH_TIMEOUT");
                return result;
            }
        } finally { deadline.cancel(false); synchronized (responseConnections) { responseConnections.remove(connection); } connection.disconnect(); }
    }

    JSONObject activeCredentials() throws Exception { return session().active(System.currentTimeMillis() / 1000); }
    JSONObject researchSelection() throws Exception {
        ChatGPTSession manager = session(); JSONObject state = manager.snapshot();
        JSONObject credentials = state.optJSONObject("credentials");
        if (credentials == null || manager.isSigningOut() || !ChatGPTProtocol.hasPlanPermission(credentials))
            throw new IOException("SIGN_IN_REQUIRED");
        String identity = credentials.getString("client_id") + "\u0000" + credentials.getString("subject");
        return selection().put("account_key", StockAIPlugin.hex(java.security.MessageDigest.getInstance("SHA-256")
            .digest(identity.getBytes(StandardCharsets.UTF_8))));
    }
    static String failureCode(Throwable error) {
        while (error instanceof java.util.concurrent.CompletionException || error instanceof java.util.concurrent.ExecutionException) error = error.getCause();
        String code = error == null ? null : error.getMessage();
        return code != null && code.matches("[A-Za-z0-9_]{1,100}") ? code : "CONNECTION_FAILED";
    }
    static void disconnectResponses() {
        HttpURLConnection[] connections;
        synchronized (responseConnections) { connections = responseConnections.toArray(new HttpURLConnection[0]); }
        for (HttpURLConnection connection : connections) {
            try { connection.disconnect(); } catch (RuntimeException ignored) { }
        }
    }
    void rememberFailure(Exception error) {
        if (error instanceof ChatGPTProtocol.ProviderFailure) {
            ChatGPTProtocol.ProviderFailure value = (ChatGPTProtocol.ProviderFailure) error;
            try { secrets().write("last-connection-error", new JSONObject().put("status", value.status)
                .put("code", value.code).put("shape", value.shape).put("request_id", value.requestId)
                .put("parameter", value.parameter).toString()); } catch (Exception ignored) { }
        }
    }
    CompletableFuture<JSONObject> respond(String id, String json, String digest, String model, String effort) {
        CompletableFuture<JSONObject> result = new CompletableFuture<>();
        if (queued.incrementAndGet() > 64) {
            queued.decrementAndGet(); result.completeExceptionally(new IOException("RESEARCH_QUEUE_FULL")); return result;
        }
        ResearchJournal journal = new ResearchJournal(context);
        boolean reserved = false;
        try {
            JSONObject prior = journal.begin(id, digest, model, effort);
            boolean dispatch = prior.getBoolean("dispatch"); prior.remove("dispatch");
            if (!dispatch) { queued.decrementAndGet(); result.complete(prior); return result; }
            reserved = true;
            researchQueue.execute(() -> {
                try {
                    JSONObject request = ChatGPTProtocol.researchRequest(json, digest, model, effort);
                    JSONObject chosen = selection();
                    if (!chosen.getString("model").equals(model) || !chosen.getString("effort").equals(effort))
                        throw new IOException("MODEL_SELECTION_CHANGED");
                    result.complete(journal.complete(id, infer(activeCredentials(), request)));
                } catch (Exception error) {
                    rememberFailure(error);
                    try { journal.fail(id, failureCode(error)); } catch (Exception ignored) { }
                    result.completeExceptionally(error);
                } finally { journal.release(id); queued.decrementAndGet(); }
            });
        } catch (Exception error) {
            if (reserved) journal.release(id);
            queued.decrementAndGet(); result.completeExceptionally(error);
        }
        return result;
    }
}
