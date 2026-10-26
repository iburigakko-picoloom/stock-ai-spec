package jp.stockai.app;

import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import org.json.JSONArray;
import org.json.JSONObject;

/** Small committed record views. No prediction validation, model loading, or writes. */
final class NativeRecordViews {
    static boolean handles(String path) {
        return "/api/v1/execution-context".equals(path)
            || (path != null && path.matches("/api/v1/stocks/[A-Z0-9]{1,10}/note"));
    }
    private static String day() { return LocalDate.now(ZoneId.of("Asia/Tokyo")).toString(); }
    static JSONObject empty(String path) throws Exception {
        if (path.endsWith("/note")) return new JSONObject().put("symbol", path.split("/")[4])
            .put("text", "").put("revision", JSONObject.NULL).put("updatedAt", JSONObject.NULL);
        return new JSONObject().put("businessDate", day()).put("proposal", JSONObject.NULL)
            .put("decision", JSONObject.NULL).put("accountLabels", new JSONObject());
    }
    private static String hash(String value) throws Exception {
        return StockAIPlugin.hex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    }
    private static JSONObject checked(Cursor row) throws Exception {
        String payload = row.getString(0);
        if (!hash(payload).equals(row.getString(1))) throw new SecurityException("RECORD_CONTENT_HASH");
        return new JSONObject(payload);
    }
    static JSONObject read(SQLiteDatabase db, String path) throws Exception {
        if (path.endsWith("/note")) {
            String symbol = path.split("/")[4];
            try (Cursor row = db.rawQuery("SELECT value FROM operational_metadata WHERE key=?", new String[]{"stock-note:" + symbol})) {
                if (!row.moveToFirst()) return empty(path);
                JSONObject envelope = new JSONObject(row.getString(0));
                String raw = envelope.getString("payload_json"), digest = hash(raw);
                JSONObject note = new JSONObject(raw);
                String text = note.getString("text");
                if (!(note.opt("text") instanceof String) || !(note.opt("symbol") instanceof String)
                        || !note.has("previous_revision") || !(note.opt("updated_at") instanceof String)
                        || !digest.equals(envelope.getString("sha256"))
                        || !"stock-note-v1".equals(note.getString("schema_version"))
                        || !symbol.equals(note.getString("symbol")) || text.indexOf(0) >= 0
                        || text.codePointCount(0, text.length()) > 5000
                        || (!note.isNull("previous_revision") && !note.getString("previous_revision").matches("[a-f0-9]{64}")))
                    throw new SecurityException("STOCK_NOTE_CONTENT");
                OffsetDateTime.parse(note.getString("updated_at"));
                return new JSONObject().put("symbol", symbol).put("text", text).put("revision", digest)
                    .put("updatedAt", note.getString("updated_at"));
            }
        }
        JSONObject result = empty(path);
        try (Cursor tables = db.rawQuery("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('proposals','user_decisions','portfolio_states')", null)) {
            if (!tables.moveToFirst() || tables.getInt(0) != 3) return null;
        }
        JSONObject proposal;
        String businessDate = day();
        try (Cursor row = db.rawQuery("SELECT payload,content_hash,proposal_id FROM proposals WHERE business_date=? ORDER BY generated_at DESC,proposal_id DESC LIMIT 1", new String[]{businessDate})) {
            if (!row.moveToFirst()) return result;
            proposal = checked(row);
            if (!proposal.getString("proposal_id").equals(row.getString(2))
                    || !OffsetDateTime.parse(proposal.getString("as_of")).atZoneSameInstant(ZoneId.of("Asia/Tokyo")).toLocalDate().toString().equals(businessDate))
                throw new SecurityException("EXECUTION_PROPOSAL_IDENTITY");
        }
        JSONArray lines = new JSONArray(), source = proposal.getJSONArray("lines");
        for (int i = 0; i < source.length(); i++) {
            JSONObject line = source.getJSONObject(i);
            lines.put(new JSONObject().put("lineId", line.getString("line_id"))
                .put("symbol", line.getString("symbol")).put("companyName", line.getString("company_name"))
                .put("accountBucketId", line.getString("account_bucket_id"))
                .put("currentShares", line.getLong("current_shares")).put("referencePrice", line.getString("reference_price")));
        }
        result.put("proposal", new JSONObject().put("proposalId", proposal.getString("proposal_id"))
            .put("asOf", NativePortfolioReader.timestamp(proposal.getString("as_of"))).put("lines", lines));
        try (Cursor row = db.rawQuery("SELECT payload,content_hash,decision_id,version FROM user_decisions WHERE proposal_id=? ORDER BY version DESC LIMIT 1", new String[]{proposal.getString("proposal_id")})) {
            if (row.moveToFirst()) {
                JSONObject decision = checked(row);
                if (!proposal.getString("proposal_id").equals(decision.getString("proposal_id"))
                        || !row.getString(2).equals(decision.getString("decision_id")) || row.getLong(3) != decision.getLong("version"))
                    throw new SecurityException("EXECUTION_DECISION_IDENTITY");
                decision.put("saved_at", NativePortfolioReader.timestamp(decision.getString("saved_at")));
                result.put("decision", decision);
            }
        }
        try (Cursor row = db.rawQuery("SELECT payload,content_hash,portfolio_id FROM portfolio_states WHERE portfolio_id=?", new String[]{proposal.getString("current_portfolio_id")})) {
            if (!row.moveToFirst()) throw new SecurityException("EXECUTION_PORTFOLIO_MISSING");
            JSONObject portfolio = checked(row), labels = new JSONObject();
            if (!row.getString(2).equals(portfolio.getString("portfolio_id"))) throw new SecurityException("EXECUTION_PORTFOLIO_IDENTITY");
            JSONArray buckets = portfolio.getJSONArray("account_buckets");
            for (int i = 0; i < buckets.length(); i++) {
                JSONObject bucket = buckets.getJSONObject(i);
                String type = bucket.getString("account_type");
                labels.put(bucket.getString("bucket_id"), type.equals("taxable_specified") ? "特定口座" : type.equals("taxable_general") ? "一般口座" : type.equals("nisa") ? "NISA" : type);
            }
            result.put("accountLabels", labels);
        }
        return result;
    }
}
