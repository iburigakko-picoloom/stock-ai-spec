package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.IOException;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Isolated native preference keys; never reads or overwrites an owner's session. */
@RunWith(AndroidJUnit4.class)
public class ChatGPTSessionTest {
    private final long now = 1800000000L;
    private JSONObject tokens(String access, String refresh, long expires, String scope) throws Exception {
        return new JSONObject().put("access_token", access).put("refresh_token", refresh)
            .put("token_type", "Bearer").put("expires_at", expires).put("scope", scope);
    }
    private final class Fixture implements AutoCloseable {
        final Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        final String key = "test-session-" + UUID.randomUUID(), legacy = key + "-legacy";
        final AtomicInteger refreshes = new AtomicInteger(), revocations = new AtomicInteger();
        JSONObject renewed;
        Exception refreshFailure, revokeFailure;
        CountDownLatch entered, release;
        final ChatGPTSession.Remote remote = new ChatGPTSession.Remote() {
            @Override public JSONObject refresh(JSONObject saved) throws Exception {
                refreshes.incrementAndGet();
                assertEquals("synthetic-refresh-old", saved.getString("refresh_token"));
                if (entered != null) { entered.countDown(); assertTrue(release.await(3, TimeUnit.SECONDS)); }
                if (refreshFailure != null) throw refreshFailure;
                return new JSONObject(renewed.toString());
            }
            @Override public JSONObject jwks() { throw new AssertionError("Fixture has no ID token"); }
            @Override public void revoke(JSONObject saved) throws Exception {
                revocations.incrementAndGet();
                assertNull(session.snapshot().optJSONObject("credentials"));
                assertFalse(session.canUse(new JSONObject(saved.toString()).put("_session_epoch", 1)));
                assertEquals("synthetic-client", saved.getString("client_id"));
                if (revokeFailure != null) throw revokeFailure;
            }
        };
        final ChatGPTSession session = new ChatGPTSession(context, remote, key);
        Fixture() throws Exception {
            assertTrue(context.getPackageName().endsWith(".debug"));
            renewed = tokens("synthetic-access-new", "synthetic-refresh-new", now + 3600, ChatGPTProtocol.SCOPES);
        }
        void login(long expires) throws Exception {
            long epoch = session.authorization().getLong("epoch");
            session.rememberClient(epoch, "synthetic-client");
            session.accept(epoch, "synthetic-client", tokens(
                "synthetic-access-old", "synthetic-refresh-old", expires, ChatGPTProtocol.SCOPES
            ), new JSONObject().put("sub", "synthetic-owner").put("email", "synthetic@example.invalid"), now);
        }
        @Override public void close() throws Exception {
            if (release != null) release.countDown();
            new NativeSecrets(context).remove(key); new NativeSecrets(context).remove(legacy);
        }
    }
    @Test public void rotationIsDurableBeforeRemovedPlanPermissionBlocksInference() throws Exception {
        try (Fixture fixture = new Fixture()) {
            fixture.login(now + 1); fixture.renewed.put("scope", "openid email offline_access");
            try { fixture.session.active(now + 2); fail("Removed permission allowed inference"); }
            catch (IOException expected) { assertEquals("PLAN_PERMISSION_REQUIRED", expected.getMessage()); }
            JSONObject saved = fixture.session.snapshot().getJSONObject("credentials");
            assertEquals("synthetic-refresh-new", saved.getString("refresh_token"));
            assertEquals("synthetic-access-new", saved.getString("access_token"));
            assertFalse(ChatGPTProtocol.hasPlanPermission(saved));
            assertEquals(1, fixture.refreshes.get());
        }
    }
    @Test public void onlyConfirmedTerminalRefreshFailureClearsTokensAndKeepsOwnerMapping() throws Exception {
        for (String code : new String[]{"invalid_grant", "invalid_refresh_token", "token_expired",
                "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"}) {
            try (Fixture fixture = new Fixture()) {
                fixture.login(now + 1);
                fixture.refreshFailure = ChatGPTProtocol.failure(400, new JSONObject().put("error", code).toString(), "req-fixture");
                try { fixture.session.active(now + 2); fail("Unusable token was accepted"); }
                catch (ChatGPTProtocol.ProviderFailure expected) { assertEquals(code, expected.code); }
                JSONObject state = fixture.session.snapshot();
                assertNull(state.optJSONObject("credentials"));
                assertTrue(state.getBoolean("reauthorization_required"));
                assertEquals("synthetic-client", state.getJSONObject("registration").getString("client_id"));
                assertEquals("synthetic-owner", state.getJSONObject("registration").getString("subject"));
            }
        }
        try (Fixture fixture = new Fixture()) {
            fixture.login(now + 1); String before = fixture.session.snapshot().toString();
            fixture.refreshFailure = ChatGPTProtocol.failure(503, "{\"detail\":\"temporary\"}", "req-fixture");
            try { fixture.session.active(now + 2); fail("Unavailable refresh counted as success"); }
            catch (ChatGPTProtocol.ProviderFailure expected) { assertEquals(503, expected.status); }
            assertEquals(before, fixture.session.snapshot().toString());
        }
    }
    @Test public void concurrentConsumersShareOneRefreshAndStatusRemainsReadable() throws Exception {
        try (Fixture fixture = new Fixture()) {
            fixture.login(now + 1); fixture.entered = new CountDownLatch(1); fixture.release = new CountDownLatch(1);
            AtomicReference<Throwable> failure = new AtomicReference<>();
            Runnable use = () -> {
                try { assertEquals("synthetic-access-new", fixture.session.active(now + 2).getString("access_token")); }
                catch (Throwable error) { failure.set(error); }
            };
            Thread first = new Thread(use), second = new Thread(use);
            first.start(); assertTrue(fixture.entered.await(2, TimeUnit.SECONDS)); second.start();
            assertNotNull(fixture.session.snapshot().getJSONObject("credentials"));
            fixture.release.countDown(); first.join(3000); second.join(3000);
            assertFalse(first.isAlive()); assertFalse(second.isAlive());
            if (failure.get() != null) throw new AssertionError(failure.get());
            assertEquals(1, fixture.refreshes.get());
        }
    }
    @Test public void logoutStopsRequestsClearsTokensAndRetainsRegistrationOnRemoteFailure() throws Exception {
        try (Fixture fixture = new Fixture()) {
            fixture.login(now + 3600); JSONObject active = fixture.session.active(now);
            String ticket = fixture.session.requestSignOut();
            assertFalse(fixture.session.canUse(active));
            fixture.revokeFailure = new IOException("NETWORK_UNAVAILABLE");
            assertFalse(fixture.session.signOut(ticket));
            assertFalse(fixture.session.isSigningOut());
            JSONObject state = fixture.session.snapshot();
            assertNull(state.optJSONObject("credentials"));
            assertEquals("synthetic-client", state.getJSONObject("registration").getString("client_id"));
            assertFalse(state.getBoolean("revocation_confirmed"));
            assertEquals(2, fixture.revocations.get());
            assertFalse(state.toString().contains("synthetic-access-old"));
            assertFalse(state.toString().contains("synthetic-refresh-old"));
        }
        try (Fixture fixture = new Fixture()) {
            fixture.login(now + 3600); assertTrue(fixture.session.signOut());
            assertTrue(fixture.session.snapshot().getBoolean("revocation_confirmed"));
            assertEquals(1, fixture.revocations.get());
        }
    }
    @Test public void lateOrDifferentIdentityCannotOverwriteTheRegisteredOwner() throws Exception {
        try (Fixture fixture = new Fixture()) {
            fixture.login(now + 3600); long epoch = fixture.session.authorization().getLong("epoch");
            fixture.session.rememberClient(epoch, "synthetic-client");
            try {
                fixture.session.accept(epoch, "synthetic-client", fixture.renewed,
                    new JSONObject().put("sub", "different-owner"), now);
                fail("Different identity replaced owner");
            } catch (SecurityException expected) { }
            fixture.session.signOut();
            try {
                fixture.session.accept(epoch, "synthetic-client", fixture.renewed,
                    new JSONObject().put("sub", "synthetic-owner"), now);
                fail("Late authorization undid logout");
            } catch (IOException expected) { }
            assertNull(fixture.session.snapshot().optJSONObject("credentials"));
        }
    }
    @Test public void legacyCredentialsMigrateAtomicallyWithinIsolatedKeys() throws Exception {
        try (Fixture fixture = new Fixture()) {
            JSONObject legacy = tokens("synthetic-access-old", "synthetic-refresh-old", now + 3600, ChatGPTProtocol.SCOPES)
                .put("client_id", "synthetic-client").put("subject", "synthetic-owner").put("label", "Synthetic owner");
            new NativeSecrets(fixture.context).write(fixture.legacy, legacy.toString());
            ChatGPTSession migrated = new ChatGPTSession(fixture.context, fixture.remote, fixture.key, fixture.legacy);
            assertEquals("synthetic-client", migrated.snapshot().getJSONObject("registration").getString("client_id"));
            assertEquals("synthetic-access-old", migrated.active(now).getString("access_token"));
            assertNull(new NativeSecrets(fixture.context).read(fixture.legacy));
        }
    }
    @Test public void diagnosticsUseOnlyStableCodesAndDiscoveryCannotRedirectTokensToAnotherOrigin() throws Exception {
        ChatGPTProtocol.ProviderFailure failure = ChatGPTProtocol.failure(400,
            "{\"error\":\"invalid_grant\",\"error_description\":\"synthetic-secret-do-not-expose\"}", "req-fixture");
        assertTrue(failure.terminalRefresh()); assertEquals("invalid_grant", failure.getMessage());
        assertFalse(failure.getMessage().contains("synthetic-secret")); assertEquals("oauth_error", failure.shape);
        assertFalse(ChatGPTProtocol.failure(503, "{\"error\":\"invalid_grant\"}", "req-fixture").terminalRefresh());
        assertEquals("HTTP_403", ChatGPTProtocol.failure(403, "{\"detail\":\"denied\"}", "req-fixture").code);
        String valid = ChatGPTProtocol.ISSUER + "/api/accounts/oauth/revoke";
        assertEquals(valid, ChatGPTProtocol.revocationEndpoint(new JSONObject().put("issuer", ChatGPTProtocol.ISSUER).put("revocation_endpoint", valid)));
        for (String url : new String[]{"http://auth.openai.com/revoke", "https://example.com/revoke", "https://user@auth.openai.com/revoke", valid + "#other", valid + "?token=unsafe"}) {
            try { ChatGPTProtocol.revocationEndpoint(new JSONObject().put("issuer", ChatGPTProtocol.ISSUER).put("revocation_endpoint", url)); fail("Untrusted revocation endpoint accepted"); }
            catch (SecurityException expected) { }
        }
    }
}
