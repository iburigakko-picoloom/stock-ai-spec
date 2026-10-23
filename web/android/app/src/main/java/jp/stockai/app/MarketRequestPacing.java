package jp.stockai.app;

/** Monotonic, shared by manual and Worker requests under MarketClient.PROVIDER. */
final class MarketRequestPacing {
    static final long CONSERVATIVE_MS = 12_500;
    static final long PAID_MS = 1_100; // below Light and financial-summary 60/min limits
    static final long COOLDOWN_MS = 120_000;
    private static final long PROOF_LIFETIME_MS = 24 * 60 * 60 * 1000L;
    private String credentialId;
    private long lastRequest = -1;
    private long paidProof = -1;
    private long blockedUntil;

    void credential(String id) {
        if (!id.equals(credentialId)) {
            credentialId = id;
            paidProof = -1;
            // Keep pacing/cooldown across key rotation: limits apply per account.
        }
    }

    long delay(long now) {
        boolean paid = paidProof >= 0 && now >= paidProof && now - paidProof < PROOF_LIFETIME_MS;
        long interval = paid ? PAID_MS : CONSERVATIVE_MS;
        return Math.max(0, Math.max(blockedUntil - now,
            lastRequest < 0 ? 0 : lastRequest + interval - now));
    }

    void started(long now) { lastRequest = now; }

    void response(String endpoint, int status, boolean hasRows, long now) {
        if (status == 429) {
            paidProof = -1;
            blockedUntil = Math.max(blockedUntil, now + COOLDOWN_MS);
        } else if (status == 401 || status == 403) {
            paidProof = -1;
        } else if (status == 200 && hasRows && endpoint.equals("/indices/bars/daily/topix")) {
            // Official plan matrix: TOPIX is unavailable on Free. Calendar is NOT proof.
            paidProof = now;
        }
    }
}
