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
    private static long lastRequest;
    final Context context;
    final SQLiteDatabase db;

    MarketClient(Context context, SQLiteDatabase db) {
        this.context = context.getApplicationContext(); this.db = db;
    }

    static String apiKey(Context context) throws Exception {
        String saved = context.getSharedPreferences("stockai-secrets", 0).getString("jquants", null);
        return saved == null ? null : LocalStateStore.decrypt(Base64.decode(saved, Base64.NO_WRAP));
    }

    MarketDownload download(boolean membership) {
        return new MarketDownload(db, (endpoint, day, page) -> {
            synchronized (PROVIDER) {
                String credential = apiKey(context);
                if (credential == null) throw new IllegalStateException("API_KEY_REQUIRED");
                long delay = 12500 - (android.os.SystemClock.elapsedRealtime() - lastRequest);
                if (lastRequest != 0 && delay > 0) Thread.sleep(delay);
                String query = endpoint.equals("/markets/calendar")
                    ? "?from=" + day + "&to=" + java.time.LocalDate.parse(day).plusDays(21) : "?date=" + day;
                if (page != null) query += "&pagination_key=" + java.net.URLEncoder.encode(page, "UTF-8");
                HttpURLConnection conn = StockAIPlugin.connection("https://api.jquants.com/v2" + endpoint + query);
                conn.setRequestProperty("x-api-key", credential);
                try {
                    lastRequest = android.os.SystemClock.elapsedRealtime();
                    int status = conn.getResponseCode();
                    JSONObject result = new JSONObject().put("status", status);
                    if (status == 200) {
                        JSONObject body = new JSONObject(new String(StockAIPlugin.read(conn.getInputStream(), 20 * 1024 * 1024), StandardCharsets.UTF_8));
                        result.put("body", body).put("received_at", java.time.Instant.now().toString());
                    }
                    return result;
                } finally { conn.disconnect(); }
            }
        }, membership);
    }
}
