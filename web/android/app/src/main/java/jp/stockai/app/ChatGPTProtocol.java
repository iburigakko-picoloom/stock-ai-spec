package jp.stockai.app;

import android.util.Base64;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.Reader;
import java.math.BigInteger;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.Signature;
import java.security.spec.RSAPublicKeySpec;
import java.util.HashMap;
import java.util.Map;
import java.util.Arrays;
import java.util.HashSet;
import org.json.JSONArray;
import org.json.JSONObject;

/** Small public-client protocol boundary; never logs token or callback values. */
final class ChatGPTProtocol {
    static final String ISSUER = "https://auth.openai.com";
    static final String RESOURCE = "https://api.openai.com/v1";
    static final String SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct";

    static String random() {
        byte[] bytes = new byte[32]; new SecureRandom().nextBytes(bytes);
        return Base64.encodeToString(bytes, Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
    }

    static byte[] decode(String value) {
        return Base64.decode(value, Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
    }

    static String challenge(String verifier) throws Exception {
        return Base64.encodeToString(MessageDigest.getInstance("SHA-256").digest(
            verifier.getBytes(StandardCharsets.US_ASCII)), Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
    }

    static Map<String, String> callback(String target, String expectedState, String expectedClient) throws Exception {
        if (target.length() > 8192 || !target.startsWith("/auth/callback?")) throw new SecurityException("Invalid callback path");
        Map<String, String> values = new HashMap<>();
        for (String pair : target.substring(target.indexOf('?') + 1).split("&")) {
            String[] item = pair.split("=", 2);
            String key = URLDecoder.decode(item[0], "UTF-8");
            String value = item.length == 2 ? URLDecoder.decode(item[1], "UTF-8") : "";
            if (values.put(key, value) != null) throw new SecurityException("Duplicate callback parameter");
        }
        if (!MessageDigest.isEqual(expectedState.getBytes(StandardCharsets.UTF_8),
                values.getOrDefault("state", "").getBytes(StandardCharsets.UTF_8)))
            throw new SecurityException("Callback state mismatch");
        if (values.containsKey("error")) throw new IOException("AUTHORIZATION_DENIED");
        String client = values.getOrDefault("client_id", expectedClient);
        if (client == null || client.isEmpty() || client.equals("dynamic_agent_client")
                || client.length() > 512 || (expectedClient != null && !expectedClient.equals(client)))
            throw new SecurityException("Callback client mismatch");
        if (values.getOrDefault("code", "").isEmpty()) throw new SecurityException("Missing callback code");
        values.put("client_id", client);
        return values;
    }

    static JSONObject validateIdToken(String token, JSONObject jwks, String client, String nonce,
            String expectedSubject, long now) throws Exception {
        if (token.length() > 32768) throw new SecurityException("ID token limit");
        String[] segments = token.split("\\.", -1);
        if (segments.length != 3) throw new SecurityException("Invalid ID token");
        JSONObject header = new JSONObject(new String(decode(segments[0]), StandardCharsets.UTF_8));
        if (!header.getString("alg").equals("RS256") || header.has("crit"))
            throw new SecurityException("Unsupported ID token algorithm");
        JSONArray keys = jwks.getJSONArray("keys"); JSONObject selected = null;
        for (int i = 0; i < keys.length(); i++) {
            JSONObject key = keys.getJSONObject(i);
            if (key.optString("kid").equals(header.getString("kid"))) {
                if (selected != null || !key.optString("kty").equals("RSA")
                        || !key.optString("use", "sig").equals("sig")
                        || !key.optString("alg", "RS256").equals("RS256"))
                    throw new SecurityException("Invalid signing key");
                selected = key;
            }
        }
        if (selected == null) throw new SecurityException("Unknown signing key");
        BigInteger modulus = new BigInteger(1, decode(selected.getString("n")));
        if (modulus.bitLength() < 2048) throw new SecurityException("Weak signing key");
        Signature signature = Signature.getInstance("SHA256withRSA");
        signature.initVerify(KeyFactory.getInstance("RSA").generatePublic(new RSAPublicKeySpec(
            modulus, new BigInteger(1, decode(selected.getString("e"))))));
        signature.update((segments[0] + "." + segments[1]).getBytes(StandardCharsets.US_ASCII));
        if (!signature.verify(decode(segments[2]))) throw new SecurityException("ID token signature mismatch");
        JSONObject claims = new JSONObject(new String(decode(segments[1]), StandardCharsets.UTF_8));
        Object audience = claims.get("aud"); boolean matches = client.equals(audience);
        if (audience instanceof JSONArray) {
            JSONArray audiences = (JSONArray) audience;
            for (int i = 0; i < audiences.length(); i++) matches |= client.equals(audiences.getString(i));
            if (audiences.length() > 1 && !client.equals(claims.optString("azp"))) matches = false;
        }
        if (!ISSUER.equals(claims.getString("iss")) || !matches || claims.getLong("exp") <= now
                || claims.optLong("iat", now) > now + 60 || claims.optLong("nbf", now) > now + 60
                || claims.getString("sub").isEmpty()
                || (nonce != null && !nonce.equals(claims.optString("nonce")))
                || (expectedSubject != null && !expectedSubject.equals(claims.getString("sub"))))
            throw new SecurityException("ID token claims mismatch");
        return claims;
    }

    static boolean hasPlanPermission(JSONObject tokens) {
        for (String scope : tokens.optString("scope").split("\\s+"))
            if (scope.equals("chatgpt.tokens.use.direct")) return true;
        return false;
    }

    static JSONObject researchRequest(String text, String digest, String model, String effort) throws Exception {
        if (text == null || text.length() > 512000 || digest == null || !digest.matches("[0-9a-f]{64}"))
            throw new SecurityException("INVALID_RESEARCH_REQUEST");
        byte[] hash = MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
        StringBuilder actual = new StringBuilder();
        for (byte item : hash) actual.append(String.format(java.util.Locale.ROOT, "%02x", item & 0xff));
        if (!MessageDigest.isEqual(actual.toString().getBytes(StandardCharsets.US_ASCII), digest.getBytes(StandardCharsets.US_ASCII)))
            throw new SecurityException("RESEARCH_REQUEST_HASH_MISMATCH");
        JSONObject body = new JSONObject(text);
        if (!body.keySet().equals(new HashSet<>(Arrays.asList("instructions", "input", "tools", "include")))
                || body.getString("instructions").length() > 8000 || body.getJSONArray("input").length() != 1
                || !body.getJSONArray("tools").toString().equals("[{\"type\":\"web_search\"}]")
                || !body.getJSONArray("include").toString().equals("[\"web_search_call.action.sources\"]"))
            throw new SecurityException("INVALID_RESEARCH_REQUEST");
        JSONObject input = body.getJSONArray("input").getJSONObject(0);
        if (!input.keySet().equals(new HashSet<>(Arrays.asList("role", "content")))
                || !input.getString("role").equals("user") || input.getString("content").isEmpty()
                || model == null || !model.matches("[a-zA-Z0-9._:-]{1,160}")
                || !Arrays.asList("low", "medium", "high", "xhigh", "max").contains(effort))
            throw new SecurityException("INVALID_RESEARCH_REQUEST");
        return body.put("model", model).put("reasoning", new JSONObject().put("effort", effort))
            .put("store", false).put("stream", true);
    }

    private static String boundedLine(BufferedReader reader) throws IOException {
        StringBuilder value = new StringBuilder(); int next;
        while ((next = reader.read()) != -1 && next != '\n') {
            if (value.length() >= 2 * 1024 * 1024) throw new IOException("RESPONSE_LIMIT");
            value.append((char) next);
        }
        if (next == -1 && value.length() == 0) return null;
        if (value.length() > 0 && value.charAt(value.length() - 1) == '\r') value.setLength(value.length() - 1);
        return value.toString();
    }

    static JSONObject readResponse(Reader source) throws Exception {
        BufferedReader reader = new BufferedReader(source);
        StringBuilder data = new StringBuilder(); long total = 0; String line;
        long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.MINUTES.toNanos(15);
        while ((line = boundedLine(reader)) != null) {
            total += line.length();
            if (System.nanoTime() > deadline) throw new IOException("RESPONSE_TIMEOUT");
            if (total > 8 * 1024 * 1024 || line.length() > 2 * 1024 * 1024)
                throw new IOException("RESPONSE_LIMIT");
            if (line.isEmpty()) {
                if (data.length() == 0) continue;
                if (data.toString().equals("[DONE]")) break;
                JSONObject event = new JSONObject(data.toString()); data.setLength(0);
                String type = event.optString("type");
                if (type.equals("response.completed")) {
                    JSONObject response = event.getJSONObject("response");
                    if (!response.getString("status").equals("completed") || !response.isNull("error")
                            || !response.isNull("incomplete_details")) throw new IOException("RESPONSE_INCOMPLETE");
                    return response;
                }
                if (type.equals("response.failed") || type.equals("response.incomplete") || type.equals("error")) {
                    JSONObject error = event.optJSONObject("error");
                    if (event.optJSONObject("response") != null) error = event.getJSONObject("response").optJSONObject("error");
                    String code = error == null ? "RESPONSE_INCOMPLETE" : error.optString("code", "RESPONSE_FAILED");
                    if (!code.matches("[a-zA-Z0-9_]{1,100}")) code = "RESPONSE_FAILED";
                    throw new IOException(code);
                }
            } else if (line.startsWith("data:")) {
                if (data.length() > 0) data.append('\n');
                data.append(line.substring(5).trim());
            }
        }
        throw new IOException("RESPONSE_INTERRUPTED");
    }
}
