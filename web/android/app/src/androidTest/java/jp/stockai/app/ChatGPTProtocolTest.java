package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import android.util.Base64;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.IOException;
import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.Signature;
import java.security.interfaces.RSAPublicKey;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class ChatGPTProtocolTest {
    KeyPair pair;
    JSONObject jwks;
    final long now = 1800000000L;
    static String encoded(byte[] bytes) { return Base64.encodeToString(bytes, Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING); }
    @Before public void createIndependentSigningKey() throws Exception {
        KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA"); generator.initialize(2048); pair = generator.generateKeyPair();
        RSAPublicKey key = (RSAPublicKey) pair.getPublic();
        jwks = new JSONObject().put("keys", new JSONArray().put(new JSONObject().put("kty", "RSA").put("kid", "synthetic-key")
            .put("n", encoded(key.getModulus().toByteArray())).put("e", encoded(key.getPublicExponent().toByteArray()))));
    }
    JSONObject claims() throws Exception {
        return new JSONObject().put("iss", ChatGPTProtocol.ISSUER).put("aud", "synthetic-client").put("sub", "synthetic-owner")
            .put("nonce", "synthetic-nonce").put("iat", now - 10).put("exp", now + 60);
    }
    String token(JSONObject claims) throws Exception {
        String body = encoded(new JSONObject().put("alg", "RS256").put("kid", "synthetic-key").toString().getBytes(StandardCharsets.UTF_8))
            + "." + encoded(claims.toString().getBytes(StandardCharsets.UTF_8));
        Signature signer = Signature.getInstance("SHA256withRSA"); signer.initSign(pair.getPrivate()); signer.update(body.getBytes(StandardCharsets.US_ASCII));
        return body + "." + encoded(signer.sign());
    }
    void rejected(JSONObject value) throws Exception {
        try { ChatGPTProtocol.validateIdToken(token(value), jwks, "synthetic-client", "synthetic-nonce", "synthetic-owner", now); fail("Invalid claims accepted"); }
        catch (SecurityException expected) { }
    }
    @Test public void pkceMatchesIndependentRfc7636Vector() throws Exception {
        assertEquals("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM", ChatGPTProtocol.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"));
        assertNotEquals(ChatGPTProtocol.random(), ChatGPTProtocol.random());
    }
    @Test public void callbackBindsStatePathClientAndRejectsDuplicates() throws Exception {
        assertEquals("issued", ChatGPTProtocol.callback("/auth/callback?state=bound&code=opaque&client_id=issued", "bound", null).get("client_id"));
        assertEquals("issued", ChatGPTProtocol.callback("/auth/callback?state=bound&code=opaque", "bound", "issued").get("client_id"));
        for (String value : new String[]{"/callback?state=bound&code=x&client_id=issued", "/auth/callback?state=other&code=x&client_id=issued",
                "/auth/callback?state=bound&state=bound&code=x&client_id=issued", "/auth/callback?state=bound&code=x&client_id=other"}) {
            try { ChatGPTProtocol.callback(value, "bound", "issued"); fail("Invalid callback accepted"); }
            catch (SecurityException expected) { }
        }
        try { ChatGPTProtocol.callback("/auth/callback?state=bound&error=access_denied", "bound", null); fail("Denied consent accepted"); }
        catch (IOException expected) { assertEquals("AUTHORIZATION_DENIED", expected.getMessage()); }
    }
    @Test public void identityRequiresSignatureIssuerAudienceNonceExpiryAndSameOwner() throws Exception {
        JSONObject valid = ChatGPTProtocol.validateIdToken(token(claims()), jwks, "synthetic-client", "synthetic-nonce", "synthetic-owner", now);
        assertEquals("synthetic-owner", valid.getString("sub"));
        rejected(claims().put("iss", "https://example.invalid")); rejected(claims().put("aud", "other"));
        rejected(claims().put("nonce", "other")); rejected(claims().put("sub", "other"));
        rejected(claims().put("exp", now)); rejected(claims().put("iat", now + 61));
        rejected(claims().put("nbf", now + 61)); rejected(claims().put("aud", new JSONArray().put("synthetic-client").put("other")));
        String original = token(claims());
        String[] parts = original.split("\\.");
        String tampered = parts[0] + "." + encoded(claims().put("sub", "other").toString().getBytes(StandardCharsets.UTF_8)) + "." + parts[2];
        try { ChatGPTProtocol.validateIdToken(tampered, jwks, "synthetic-client", "synthetic-nonce", null, now); fail("Unsigned claims accepted"); }
        catch (SecurityException expected) { }
    }
    @Test public void planPermissionComesFromGrantedTokenScopesOnly() throws Exception {
        assertFalse(ChatGPTProtocol.hasPlanPermission(new JSONObject().put("scope", "openid email")));
        assertFalse(ChatGPTProtocol.hasPlanPermission(new JSONObject().put("scope", "prefix_chatgpt.tokens.use.direct")));
        assertTrue(ChatGPTProtocol.hasPlanPermission(new JSONObject().put("scope", ChatGPTProtocol.SCOPES)));
    }
    @Test public void onlyCompletedStreamIsSuccessful() throws Exception {
        String prefix = "event: response.output_text.delta\ndata: {\"type\":\"response.output_text.delta\",\"delta\":\"partial\"}\n\n";
        JSONObject result = ChatGPTProtocol.readResponse(new StringReader(prefix
            + "data: {\"type\":\"response.completed\",\"response\":{\"status\":\"completed\",\"output\":[]}}\n\n"));
        assertEquals("completed", result.getString("status"));
        for (String ending : new String[]{"", "data: [DONE]\n\n", "data: {\"type\":\"response.incomplete\"}\n\n",
                "data: {\"type\":\"response.failed\",\"response\":{\"error\":{\"code\":\"subscription_sharing_usage_limit_exceeded\"}}}\n\n"}) {
            try { ChatGPTProtocol.readResponse(new StringReader(prefix + ending)); fail("Partial output accepted as successful"); }
            catch (IOException expected) { }
        }
    }
    @Test public void credentialEnvelopeIsNativeEncryptedAndNameAuthenticated() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        String name = "test-" + UUID.randomUUID(); NativeSecrets store = new NativeSecrets(context);
        try {
            store.write(name, "synthetic-test-credential"); assertEquals("synthetic-test-credential", store.read(name));
            String encrypted = context.getSharedPreferences("stockai-chatgpt-private", 0).getString(name, null);
            assertNotNull(encrypted); assertFalse(encrypted.contains("synthetic-test-credential"));
            context.getSharedPreferences("stockai-chatgpt-private", 0).edit().putString(name + "-other", encrypted).commit();
            try { store.read(name + "-other"); fail("Ciphertext substitution accepted"); } catch (java.security.GeneralSecurityException expected) { }
        } finally { store.remove(name); store.remove(name + "-other"); }
    }
}
