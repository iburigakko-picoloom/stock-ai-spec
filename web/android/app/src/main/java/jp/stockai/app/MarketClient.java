package jp.stockai.app;

import android.content.Context;
import android.database.sqlite.SQLiteDatabase;
import android.util.Base64;
import java.net.HttpURLConnection;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** The same credential, pacing and page journal for Activity and scheduled work. */
final class MarketClient {
    private static final Object PROVIDER = new Object();
    private static final MarketRequestPacing PACING = new MarketRequestPacing();
    final Context context;
    final SQLiteDatabase db;

    MarketClient(Context context, SQLiteDatabase db) {
        this.context = context.getApplicationContext(); this.db = db;
    }

    static String apiKey(Context context) throws Exception {
        String saved = context.getSharedPreferences("stockai-secrets", 0).getString("jquants", null);
        return saved == null ? null : LocalStateStore.decrypt(Base64.decode(saved, Base64.NO_WRAP));
    }

    static String query(String endpoint, String day, String page) throws Exception {
        String query;
        if (endpoint.equals("/markets/calendar")) {
            query = "?from=" + day + "&to=" + java.time.LocalDate.parse(day).plusDays(21);
        } else if (endpoint.equals("/indices/bars/daily/topix")) {
            query = "?from=" + day + "&to=" + day;
        } else {
            query = "?date=" + day;
        }
        if (page != null) query += "&pagination_key=" + java.net.URLEncoder.encode(page, "UTF-8");
        return query;
    }

    MarketDownload download(boolean membership) {
        return new MarketDownload(db, (endpoint, day, page) -> {
            synchronized (PROVIDER) {
                String credential = apiKey(context);
                if (credential == null) throw new IllegalStateException("API_KEY_REQUIRED");
                PACING.credential(StockAIPlugin.hex(java.security.MessageDigest.getInstance("SHA-256")
                    .digest(credential.getBytes(StandardCharsets.UTF_8))));
                long delay = PACING.delay(android.os.SystemClock.elapsedRealtime());
                if (delay > 0) Thread.sleep(delay);
                if (Thread.currentThread().isInterrupted()) throw new InterruptedException();
                String query = query(endpoint, day, page);
                HttpURLConnection conn = StockAIPlugin.connection("https://api.jquants.com/v2" + endpoint + query);
                conn.setRequestProperty("x-api-key", credential);
                try {
                    PACING.started(android.os.SystemClock.elapsedRealtime());
                    int status = conn.getResponseCode();
                    PACING.response(endpoint, status, false, android.os.SystemClock.elapsedRealtime());
                    JSONObject result = new JSONObject().put("status", status);
                    if (status == 200) {
                        JSONObject body = new JSONObject(new String(StockAIPlugin.read(conn.getInputStream(), 20 * 1024 * 1024), StandardCharsets.UTF_8));
                        PACING.response(endpoint, status, body.getJSONArray("data").length() > 0,
                            android.os.SystemClock.elapsedRealtime());
                        result.put("body", body).put("received_at", java.time.Instant.now().toString());
                    }
                    return result;
                } finally { conn.disconnect(); }
            }
        }, membership);
    }
}
