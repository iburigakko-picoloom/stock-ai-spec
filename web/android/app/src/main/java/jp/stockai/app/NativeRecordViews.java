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
        return "/api/v1/execution-entry-context".equals(path) || "/api/v1/execution-context".equals(path)
            || "/api/v1/execution-context?includeManual=1".equals(path)
            || "/api/v1/home/ledger".equals(path) || "/api/v1/executions".equals(path)
            || "/api/v1/portfolio/history".equals(path) || "/api/v1/jobs".equals(path)
            || (path != null && path.matches("/api/v1/stocks/[A-Z0-9]{1,10}/note"));
    }
    private static String day() { return LocalDate.now(ZoneId.of("Asia/Tokyo")).toString(); }
    static Object empty(String path) throws Exception {
        if (path.equals("/api/v1/execution-entry-context")) return new JSONObject().put("portfolioId",JSONObject.NULL).put("asOf",JSONObject.NULL).put("accountLabels",new JSONObject()).put("holdings",new JSONArray());
        if (path.equals("/api/v1/portfolio/history") || path.equals("/api/v1/jobs")) return new JSONArray();
        if (path.equals("/api/v1/executions")) return new JSONObject().put("records", new JSONArray()).put("appliedIds", new JSONArray());
        if (path.equals("/api/v1/home/ledger")) return new JSONObject().put("portfolio", JSONObject.NULL).put("holdings", new JSONArray()).put("blockingReason", "保有未登録").put("initialLedger", JSONObject.NULL);
        if (path.endsWith("/note")) return new JSONObject().put("symbol", path.split("/")[4])
            .put("text", "").put("revision", JSONObject.NULL).put("updatedAt", JSONObject.NULL);
        JSONObject context = new JSONObject().put("businessDate", day()).put("proposal", JSONObject.NULL)
            .put("decision", JSONObject.NULL).put("accountLabels", new JSONObject());
        if (path.equals("/api/v1/execution-context?includeManual=1"))
            context.put("manualContext", empty("/api/v1/execution-entry-context"));
        return context;
    }
    private static String hash(String value) throws Exception {
        return StockAIPlugin.hex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    }
    private static JSONObject checked(Cursor row) throws Exception {
        String payload = row.getString(0);
        if (!hash(payload).equals(row.getString(1))) throw new SecurityException("RECORD_CONTENT_HASH");
        return new JSONObject(payload);
    }
    private static String jsonTime(String value) {
        String text = NativePortfolioReader.timestamp(value);
        return text.endsWith("+00:00") ? text.substring(0,text.length()-6)+"Z" : text;
    }
    private static final java.math.MathContext MONEY = new java.math.MathContext(28, java.math.RoundingMode.HALF_EVEN);
    private static java.math.BigDecimal money(JSONObject row, String key) throws Exception {
        return new java.math.BigDecimal(row.getString(key));
    }
    private static JSONObject metadata(SQLiteDatabase db, String key) throws Exception {
        try (Cursor row = db.rawQuery("SELECT value FROM operational_metadata WHERE key=?", new String[]{key})) {
            return row.moveToFirst() ? new JSONObject(row.getString(0)) : null;
        }
    }
    private static JSONObject labels(JSONObject ledger) throws Exception {
        JSONObject labels = new JSONObject(); JSONArray buckets = ledger.getJSONArray("account_buckets");
        for (int i = 0; i < buckets.length(); i++) {
            JSONObject bucket = buckets.getJSONObject(i); String type = bucket.getString("account_type");
            labels.put(bucket.getString("bucket_id"), type.equals("taxable_specified") ? "特定口座" : type.equals("taxable_general") ? "一般口座" : type.equals("nisa") ? "NISA" : type);
        }
        return labels;
    }
    private static JSONObject home(SQLiteDatabase db) throws Exception {
        JSONObject ledger = NativePortfolioReader.latestLedger(db);
        JSONObject result = (JSONObject) empty("/api/v1/home/ledger");
        result.put("initialLedger", JSONObject.NULL);
        if (ledger == null) return result;
        JSONObject names = new JSONObject();
        try (Cursor row = db.rawQuery("SELECT payload,content_hash FROM proposals WHERE business_date=? ORDER BY generated_at DESC,proposal_id DESC LIMIT 1", new String[]{day()})) {
            if (row.moveToFirst()) {
                JSONArray lines = checked(row).getJSONArray("lines");
                for (int i = 0; i < lines.length(); i++) {JSONObject line = lines.getJSONObject(i); names.put(line.getString("symbol") + ":" + line.getString("account_bucket_id"), line.getString("company_name"));}
            }
        }
        java.math.BigDecimal cash = java.math.BigDecimal.ZERO, reserved = cash, buying = cash, equity = cash;
        JSONArray cashRows = ledger.getJSONArray("cash"), positions = ledger.getJSONArray("positions"), holdings = new JSONArray();
        for (int i = 0; i < cashRows.length(); i++) {
            JSONObject row = cashRows.getJSONObject(i);
            cash = cash.add(money(row,"available_cash"),MONEY); reserved = reserved.add(money(row,"reserved_cash"),MONEY);
            buying = buying.add(money(row,"available_cash").subtract(money(row,"reserved_cash"),MONEY),MONEY);
        }
        for (int i = 0; i < positions.length(); i++) {
            JSONObject row = positions.getJSONObject(i); String symbol = row.getString("symbol"), bucket = row.getString("account_bucket_id");
            java.math.BigDecimal shares = new java.math.BigDecimal(row.getString("shares"));
            java.math.BigDecimal value = money(row,"market_price").multiply(shares,MONEY);
            java.math.BigDecimal book = money(row,"average_acquisition_price").multiply(shares,MONEY);
            equity = equity.add(value,MONEY);
            holdings.put(new JSONObject().put("symbol",symbol).put("companyName",names.optString(symbol+":"+bucket,symbol))
                .put("accountBucketId",bucket).put("shares",row.getLong("shares"))
                .put("averageAcquisitionPrice",row.getString("average_acquisition_price")).put("currentPrice",row.getString("market_price"))
                .put("marketValue",value.toString()).put("unrealizedPnlAmount",value.subtract(book,MONEY).toString())
                .put("latestAction",JSONObject.NULL).put("recommendedShares",JSONObject.NULL).put("proposalId",JSONObject.NULL));
        }
        String mode = "UNCONFIGURED";
        try (Cursor row = db.rawQuery("SELECT value FROM operational_metadata WHERE key='runtime_mode'",null)) {if(row.moveToFirst())mode=row.getString(0);}
        result.put("runtimeMode",mode).put("holdings",holdings).put("accountLabels",labels(ledger)).put("blockingReason",JSONObject.NULL)
            .put("portfolio",new JSONObject().put("asOf",jsonTime(ledger.getString("as_of")))
                .put("totalAssets",cash.add(equity,MONEY).toString()).put("cashValue",cash.toString()).put("reservedCash",reserved.toString())
                .put("buyingPower",buying.toString()).put("equityValue",equity.toString()).put("holdingsCount",positions.length()));
        try (Cursor rows = db.rawQuery("SELECT p.preview_id,p.payload,p.content_hash,c.confirmed_at FROM mobile_initial_previews p JOIN mobile_initial_confirmations c ON p.preview_id=c.preview_id",null)) {
            while(rows.moveToNext()) {
                String payload=rows.getString(1); if(!hash(payload).equals(rows.getString(0)) || !hash(payload).equals(rows.getString(2)))throw new SecurityException("INITIAL_LEDGER_HASH");
                JSONObject value=new JSONObject(payload);
                if(value.getJSONObject("portfolio").getString("portfolio_id").equals(ledger.getString("portfolio_id"))) {
                    result.put("initialLedger",new JSONObject().put("confirmedAt",rows.getString(3)).put("referencePriceDate",value.getJSONObject("prices").get("date")));break;
                }
            }
        }
        return result;
    }
    private static Object history(SQLiteDatabase db, String path) throws Exception {
        JSONArray records = new JSONArray();
        if(path.equals("/api/v1/executions")) {
            try(Cursor rows=db.rawQuery("SELECT payload,content_hash FROM executions ORDER BY executed_at,execution_id",null)) {
                while(rows.moveToNext()){JSONObject record=checked(rows);record.put("executed_at",jsonTime(record.getString("executed_at")));records.put(record);}
            }
            JSONObject ledger=NativePortfolioReader.latestLedger(db);
            return new JSONObject().put("records",records).put("appliedIds",ledger==null ? new JSONArray() : ledger.getJSONArray("applied_execution_ids"));
        }
        if(path.equals("/api/v1/portfolio/history")) {
            try(Cursor rows=db.rawQuery("SELECT payload,content_hash FROM portfolio_states ORDER BY created_at DESC,portfolio_id DESC LIMIT 100",null)) {
                while(rows.moveToNext()) {
                    JSONObject record=checked(rows), envelope=metadata(db,"account_edit_record:"+record.getString("portfolio_id"));
                    record.put("as_of",jsonTime(record.getString("as_of")));record.put("correctionRecord",JSONObject.NULL);
                    if(envelope!=null) {
                        String raw=envelope.getString("payload");JSONObject correction=new JSONObject(raw);
                        if(!hash(raw).equals(envelope.getString("sha256")) || !record.getString("portfolio_id").equals(correction.getString("portfolio_id")))throw new SecurityException("CORRECTION_HASH");
                        record.put("correctionRecord",correction.getJSONObject("record"));
                    }
                    records.put(record);
                }
            }
            return records;
        }
        java.util.List<JSONObject> jobs=new java.util.ArrayList<>();
        try(Cursor rows=db.rawQuery("SELECT payload,content_hash FROM automation_jobs",null)) {while(rows.moveToNext())jobs.add(checked(rows));}
        jobs.sort((a,b)->{
            try {int time=OffsetDateTime.parse(b.getString("started_at")).toInstant().compareTo(OffsetDateTime.parse(a.getString("started_at")).toInstant());return time!=0 ? time : b.getString("run_id").compareTo(a.getString("run_id"));}
            catch(Exception error){throw new IllegalArgumentException("JOB_TIME",error);}
        });
        for(JSONObject record:jobs.subList(0,Math.min(100,jobs.size()))) {
            // OperationalModel serializes UTC as Z; retain its canonical text.
            for(String key:new String[]{"started_at","finished_at","data_as_of","morning_data_as_of"})if(record.has(key) && !record.isNull(key))record.put(key,jsonTime(record.getString(key)));
            records.put(record);
        }
        return records;
    }
    static Object read(SQLiteDatabase db, String path) throws Exception {
        if(path.equals("/api/v1/execution-entry-context")) {
            JSONObject ledger=NativePortfolioReader.latestLedger(db);
            if(ledger==null)return empty(path);
            JSONArray holdings=new JSONArray(), positions=ledger.getJSONArray("positions");
            for(int i=0;i<positions.length();i++){JSONObject row=positions.getJSONObject(i);holdings.put(new JSONObject().put("symbol",row.getString("symbol")).put("accountBucketId",row.getString("account_bucket_id")).put("shares",row.getLong("shares")));}
            return new JSONObject().put("portfolioId",ledger.getString("portfolio_id")).put("asOf",NativePortfolioReader.timestamp(ledger.getString("as_of"))).put("accountLabels",labels(ledger)).put("holdings",holdings);
        }
        String required = path.equals("/api/v1/home/ledger") ? "mobile_initial_previews" : path.equals("/api/v1/jobs") ? "automation_jobs" : path.equals("/api/v1/executions") ? "executions" : "portfolio_states";
        try(Cursor row=db.rawQuery("SELECT name FROM sqlite_master WHERE type='table' AND name=?",new String[]{required})) {if(!row.moveToFirst())return null;}
        if (path.equals("/api/v1/home/ledger")) return home(db);
        if (path.equals("/api/v1/executions") || path.equals("/api/v1/portfolio/history") || path.equals("/api/v1/jobs")) return history(db, path);
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
        JSONObject result = (JSONObject) empty("/api/v1/execution-context");
        boolean includeManual = path.equals("/api/v1/execution-context?includeManual=1");
        try (Cursor tables = db.rawQuery("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('proposals','user_decisions','portfolio_states')", null)) {
            if (!tables.moveToFirst() || tables.getInt(0) != 3) return null;
        }
        JSONObject proposal;
        String businessDate = day();
        try (Cursor row = db.rawQuery("SELECT payload,content_hash,proposal_id FROM proposals WHERE business_date=? ORDER BY generated_at DESC,proposal_id DESC LIMIT 1", new String[]{businessDate})) {
            if (!row.moveToFirst()) {
                if (includeManual) result.put("manualContext", read(db, "/api/v1/execution-entry-context"));
                return result;
            }
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
                decision.put("saved_at",jsonTime(decision.getString("saved_at")));
                result.put("decision", decision);
            }
        }
        if (includeManual && result.isNull("decision")) result.put("manualContext", read(db, "/api/v1/execution-entry-context"));
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
