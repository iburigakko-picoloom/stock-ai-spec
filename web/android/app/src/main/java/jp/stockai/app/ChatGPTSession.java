package jp.stockai.app;

import android.content.Context;
import java.io.IOException;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.json.JSONObject;

/** One owner registration, with atomically rotated native-only credentials. */
final class ChatGPTSession {
    interface Remote {
        JSONObject refresh(JSONObject saved) throws Exception;
        JSONObject jwks() throws Exception;
        void revoke(JSONObject saved) throws Exception;
    }
    private static final Object LOCK = new Object();
    private static final Set<String> signOutRequests = ConcurrentHashMap.newKeySet();
    private final NativeSecrets secrets;
    private final Remote remote;
    private final String storageKey;
    private final String legacyKey;

    ChatGPTSession(Context context, Remote remote) { this(context, remote, "session-v2", "credentials"); }
    ChatGPTSession(Context context, Remote remote, String storageKey) {
        this(context, remote, storageKey, null);
    }
    ChatGPTSession(Context context, Remote remote, String storageKey, String legacyKey) {
        this.secrets = new NativeSecrets(context); this.remote = remote;
        this.storageKey = storageKey; this.legacyKey = legacyKey;
    }
    private JSONObject read() throws Exception {
        String saved = secrets.read(storageKey);
        if (saved != null) return new JSONObject(saved);
        synchronized (LOCK) {
            saved = secrets.read(storageKey);
            if (saved != null) return new JSONObject(saved);
            JSONObject state = new JSONObject().put("epoch", 0);
            // Migrate the previously shipped native format without exporting it.
            String legacy = legacyKey == null ? null : secrets.read(legacyKey);
            if (legacy != null) {
                JSONObject credentials = new JSONObject(legacy);
                state.put("registration", registrationOf(credentials)).put("credentials", credentials);
            }
            secrets.write(storageKey, state.toString());
            if (legacy != null) secrets.remove(legacyKey);
            return state;
        }
    }
    private static JSONObject registrationOf(JSONObject credentials) throws Exception {
        String client = credentials.getString("client_id"), subject = credentials.getString("subject");
        if (client.isEmpty() || client.equals("dynamic_agent_client") || subject.isEmpty())
            throw new SecurityException("INVALID_SAVED_REGISTRATION");
        return new JSONObject().put("client_id", client).put("subject", subject)
            .put("label", credentials.optString("label", "ChatGPT"));
    }
    JSONObject snapshot() throws Exception {
        JSONObject state = read(); JSONObject credentials = state.optJSONObject("credentials");
        if (credentials != null) {
            JSONObject identity = registrationOf(credentials), registration = state.getJSONObject("registration");
            if (!identity.getString("client_id").equals(registration.getString("client_id"))
                    || !identity.getString("subject").equals(registration.getString("subject")))
                throw new SecurityException("SAVED_ACCOUNT_MISMATCH");
        }
        return state;
    }
    boolean isSigningOut() { return !signOutRequests.isEmpty(); }
    String requestSignOut() {
        String ticket = UUID.randomUUID().toString(); signOutRequests.add(ticket); return ticket;
    }
    void cancelSignOutRequest(String ticket) { signOutRequests.remove(ticket); }
    JSONObject authorization() throws Exception {
        synchronized (LOCK) {
            if (isSigningOut()) throw new IOException("SIGN_OUT_PENDING");
            return snapshot();
        }
    }
    void rememberClient(long epoch, String client) throws Exception {
        synchronized (LOCK) {
            JSONObject state = read();
            if (state.getLong("epoch") != epoch || isSigningOut()) throw new IOException("AUTHORIZATION_CANCELLED_OR_EXPIRED");
            JSONObject registration = state.optJSONObject("registration");
            if (client == null || client.isEmpty() || client.equals("dynamic_agent_client")
                    || (registration != null && !registration.getString("client_id").equals(client)))
                throw new SecurityException("SAVED_ACCOUNT_MISMATCH");
            state.put("pending_client", client); secrets.write(storageKey, state.toString());
        }
    }
    void accept(long epoch, String client, JSONObject tokens, JSONObject claims, long now) throws Exception {
        synchronized (LOCK) {
            JSONObject state = read(), registration = state.optJSONObject("registration");
            if (isSigningOut() || state.getLong("epoch") != epoch) throw new IOException("AUTHORIZATION_CANCELLED_OR_EXPIRED");
            if (!state.optString("pending_client", client).equals(client)
                    || (registration != null && (!registration.getString("client_id").equals(client)
                    || !registration.getString("subject").equals(claims.getString("sub")))))
                throw new SecurityException("SAVED_ACCOUNT_MISMATCH");
            JSONObject value = new JSONObject(tokens.toString());
            validateTokens(value, now);
            value.put("client_id", client).put("subject", claims.getString("sub"))
                .put("label", claims.optString("email", registration == null ? "ChatGPT" : registration.optString("label", "ChatGPT")));
            state.put("epoch", epoch + 1).put("registration", registrationOf(value)).put("credentials", value);
            state.remove("pending_client"); state.remove("revocation_confirmed");
            state.remove("reauthorization_required");
            secrets.write(storageKey, state.toString());
        }
    }
    private static void validateTokens(JSONObject value, long now) throws Exception {
        if (!value.getString("token_type").equalsIgnoreCase("Bearer")
                || value.getString("access_token").isEmpty() || value.getString("refresh_token").isEmpty()
                || value.getLong("expires_at") <= now)
            throw new SecurityException("INVALID_TOKEN_RESPONSE");
    }
    JSONObject active(long now) throws Exception {
        synchronized (LOCK) {
            if (isSigningOut()) throw new IOException("SIGN_IN_REQUIRED");
            JSONObject state = snapshot(), saved = state.optJSONObject("credentials");
            if (saved == null) throw new IOException("SIGN_IN_REQUIRED");
            if (!ChatGPTProtocol.hasPlanPermission(saved)) throw new IOException("PLAN_PERMISSION_REQUIRED");
            if (saved.getLong("expires_at") <= now + 60) {
                JSONObject renewed;
                try { renewed = remote.refresh(new JSONObject(saved.toString())); }
                catch (ChatGPTProtocol.ProviderFailure failure) {
                    if (failure.terminalRefresh()) {
                        state.remove("credentials"); state.put("epoch", state.getLong("epoch") + 1);
                        state.put("reauthorization_required", true);
                        secrets.write(storageKey, state.toString());
                        throw failure;
                    }
                    throw failure;
                }
                validateTokens(renewed, now);
                if (renewed.has("id_token")) ChatGPTProtocol.validateIdToken(
                    renewed.getString("id_token"), remote.jwks(), saved.getString("client_id"),
                    null, saved.getString("subject"), now);
                if (renewed.has("client_id") && !saved.getString("client_id").equals(renewed.getString("client_id")))
                    throw new SecurityException("SAVED_ACCOUNT_MISMATCH");
                // Identity comes only from the verified registration, never from
                // arbitrary response fields. Refresh rotation is one durable write.
                for (String field : new String[]{"access_token", "refresh_token", "token_type", "expires_at", "expires_in", "scope", "id_token"})
                    if (renewed.has(field)) saved.put(field, renewed.get(field));
                state.put("credentials", saved); secrets.write(storageKey, state.toString());
                // Save the new refresh token even when plan permission was removed.
                if (!ChatGPTProtocol.hasPlanPermission(saved)) throw new IOException("PLAN_PERMISSION_REQUIRED");
            }
            return new JSONObject(saved.toString()).put("_session_epoch", state.getLong("epoch"));
        }
    }
    boolean canUse(JSONObject tokens) throws Exception {
        JSONObject state = snapshot();
        return !isSigningOut() && state.optJSONObject("credentials") != null
            && tokens.optLong("_session_epoch", -1) == state.getLong("epoch")
            && tokens.getString("client_id").equals(state.getJSONObject("registration").getString("client_id"));
    }
    boolean signOut() throws Exception {
        return signOut(requestSignOut());
    }
    boolean signOut(String ticket) throws Exception {
        try {
            synchronized (LOCK) {
                JSONObject state = snapshot(), saved = state.optJSONObject("credentials");
                if (legacyKey != null) secrets.remove(legacyKey);
                if (saved == null) return state.optBoolean("revocation_confirmed", false);
                state.remove("credentials"); state.remove("reauthorization_required");
                state.put("epoch", state.getLong("epoch") + 1).put("revocation_confirmed", false);
                secrets.write(storageKey, state.toString());
                for (int attempt = 0; attempt < 2; attempt++) {
                    try {
                        remote.revoke(saved); state.put("revocation_confirmed", true);
                        secrets.write(storageKey, state.toString()); return true;
                    } catch (Exception error) {
                        boolean temporary = error instanceof IOException
                            && (!(error instanceof ChatGPTProtocol.ProviderFailure)
                                || ((ChatGPTProtocol.ProviderFailure) error).status >= 500);
                        if (!temporary || attempt == 1 || Thread.currentThread().isInterrupted()) return false;
                        try { Thread.sleep(250); }
                        catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); return false; }
                    }
                }
                return false;
            }
        } finally { signOutRequests.remove(ticket); }
    }
}
