package jp.stockai.app;

import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import com.getcapacitor.JSObject;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.security.MessageDigest;
import org.json.JSONObject;

/** Reproducible intermediate results, separate from immutable account/forecast archives. */
final class AnalysisCheckpoints {
    static final int LIMIT = 128 * 1024 * 1024, STORE_LIMIT = 512 * 1024 * 1024, CHUNK = 256 * 1024;
    final SQLiteDatabase db;
    private String scope;
    // Immutable, committed metadata only. Notifications must never wait for DB/AES work.
    private volatile String published = "{}";
    AnalysisCheckpoints(SQLiteDatabase db) throws Exception {
        this.db = db;
        db.execSQL("CREATE TABLE IF NOT EXISTS analysis_checkpoint_meta(id INTEGER PRIMARY KEY CHECK(id=1),payload BLOB NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS analysis_checkpoint_chunks(name TEXT NOT NULL,piece INTEGER NOT NULL,payload BLOB NOT NULL,PRIMARY KEY(name,piece))");
        published = meta().toString();
    }
    private JSONObject meta() throws Exception {
        try (Cursor cursor = db.rawQuery("SELECT payload FROM analysis_checkpoint_meta WHERE id=1", null)) {
            return cursor.moveToFirst() ? new JSONObject(LocalStateStore.decrypt(cursor.getBlob(0))) : new JSONObject();
        }
    }
    private void save(JSONObject value) throws Exception {
        db.execSQL("INSERT OR REPLACE INTO analysis_checkpoint_meta VALUES(1,?)", new Object[]{LocalStateStore.encrypt(value.toString())});
        if (!db.inTransaction()) published = value.toString();
    }
    synchronized String begin(Context context, long generation, String body) throws Exception {
        String code;
        try (java.io.InputStream input = context.getAssets().open("public/python/build-info.json")) {
            code = new JSONObject(new String(input.readAllBytes(), StandardCharsets.UTF_8)).getString("source_commit");
        }
        String inputKey = code + ":" + body + ":" + LocalDate.now(ZoneId.of("Asia/Tokyo"));
        String key = generation + ":" + inputKey;
        scope = LocalStateStore.hex(MessageDigest.getInstance("SHA-256").digest(key.getBytes(StandardCharsets.UTF_8)));
        JSONObject saved = meta();
        if (!scope.equals(saved.optString("scope"))) {
            db.beginTransaction();
            try {
                db.execSQL("DELETE FROM analysis_checkpoint_chunks");
                saved = new JSONObject().put("scope", scope).put("runId", java.util.UUID.randomUUID().toString())
                    .put("revision", saved.optLong("revision"))
                    .put("inputKey", inputKey).put("startedAt", Instant.now().toString())
                    .put("phase", "preparing").put("done", 0).put("total", 0).put("state", "running");
                save(saved); db.setTransactionSuccessful();
            } finally { db.endTransaction(); }
            published = saved.toString();
        } else {
            saved.put("state", "running"); saved.remove("failure"); saved.remove("blockingReasons");
            saved.remove("responseCode"); saved.remove("responseStatus"); saved.remove("diagnostic");
            save(saved);
        }
        JSONObject records = new JSONObject();
        // Return only the index, never an entire history-sized String.
        try (Cursor rows = db.rawQuery("SELECT DISTINCT name FROM analysis_checkpoint_chunks ORDER BY name", null)) {
            while (rows.moveToNext()) records.put(rows.getString(0), JSONObject.NULL);
        }
        return new JSONObject().put("startedAt", saved.getString("startedAt")).put("records", records).put("budgetSeconds", 480).toString();
    }
    synchronized String read(String name) throws Exception {
        JSONObject saved = meta();
        if (scope == null || !scope.equals(saved.optString("scope"))
                || !name.matches("inputs|features-result|source-[0-9a-f]{64}|features-[0-9a-f]{64}|model-[0-9a-f]{64}"))
            throw new SecurityException("CHECKPOINT_SCOPE");
        StringBuilder value = new StringBuilder(); int index = 0;
        try (Cursor rows = db.rawQuery("SELECT piece,payload FROM analysis_checkpoint_chunks WHERE name=? ORDER BY piece", new String[]{name})) {
            while (rows.moveToNext()) {
                JSONObject chunk = new JSONObject(LocalStateStore.decrypt(rows.getBlob(1)));
                if (rows.getInt(0) != index || !saved.getString("runId").equals(chunk.getString("runId"))
                        || !name.equals(chunk.getString("name")) || index++ != chunk.getInt("piece"))
                    throw new SecurityException("CHECKPOINT_CHUNK_IDENTITY");
                value.append(chunk.getString("data"));
                if (value.length() > LIMIT) throw new SecurityException("CHECKPOINT_LIMIT");
            }
        }
        if (index == 0) throw new SecurityException("CHECKPOINT_NOT_SAVED");
        return value.toString();
    }
    synchronized void write(JSONObject message) throws Exception {
        JSONObject saved = meta();
        if (scope == null || !scope.equals(saved.optString("scope"))) throw new SecurityException("CHECKPOINT_SCOPE");
        String key = message.getString("key"), phase = message.getString("phase");
        int done = message.getInt("done"), total = message.getInt("total");
        if (!key.matches("|inputs|features-result|source-[0-9a-f]{64}|features-[0-9a-f]{64}|model-[0-9a-f]{64}")
                || !phase.matches("preparing|features|predicting") || done < 0 || total < 0 || total > 20000
                || (total > 0 && done >= total)) throw new SecurityException("CHECKPOINT_PROGRESS");
        db.beginTransaction();
        try {
            if (!message.isNull("data")) {
                String value = message.getString("data");
                if (key.isEmpty() || value.length() > LIMIT || !value.matches("[A-Za-z0-9+/=]+")) throw new SecurityException("CHECKPOINT_DATA");
                try (Cursor quota = db.rawQuery("SELECT COALESCE(SUM(length(payload)),0) FROM analysis_checkpoint_chunks WHERE name<>? AND (?<>'inputs' OR name NOT LIKE 'source-%')", new String[]{key, key})) {
                    quota.moveToFirst();
                    if (quota.getLong(0) + value.length() + (long)(value.length() / CHUNK + 1) * 512 > STORE_LIMIT) throw new SecurityException("CHECKPOINT_LIMIT");
                }
                if (key.equals("inputs")) db.execSQL("DELETE FROM analysis_checkpoint_chunks WHERE name LIKE 'source-%'");
                db.execSQL("DELETE FROM analysis_checkpoint_chunks WHERE name=?", new Object[]{key});
                for (int offset = 0, index = 0; offset < value.length(); offset += CHUNK, index++) {
                    JSONObject chunk = new JSONObject().put("runId", saved.getString("runId")).put("name", key).put("piece", index)
                        .put("data", value.substring(offset, Math.min(value.length(), offset + CHUNK)));
                    db.execSQL("INSERT INTO analysis_checkpoint_chunks VALUES(?,?,?)", new Object[]{key, index,
                        LocalStateStore.encrypt(chunk.toString())});
                }
            } else if (!key.isEmpty()) {
                try (Cursor row = db.rawQuery("SELECT 1 FROM analysis_checkpoint_chunks WHERE name=? LIMIT 1", new String[]{key})) {
                    if (!row.moveToFirst()) throw new SecurityException("CHECKPOINT_NOT_SAVED");
                }
            }
            if (!message.isNull("data")) saved.put("revision", saved.optLong("revision") + 1);
            saved.put("done", Math.max(saved.optInt("done"), done)).put("total", Math.max(saved.optInt("total"), total))
                .put("phase", phase).put("state", "running").put("updatedAt", Instant.now().toString());
            save(saved); db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
        published = saved.toString();
    }
    synchronized void phase(String phase) throws Exception {
        JSONObject value = meta();
        if (scope == null || !scope.equals(value.optString("scope"))) return;
        value.put("phase", phase); save(value);
    }
    synchronized void failed(Throwable error) throws Exception {
        String reason = "calculation";
        String diagnostic = "";
        for (Throwable cause = error; cause != null; cause = cause.getCause()) {
            if (cause instanceof java.util.concurrent.TimeoutException) { reason = "timeout"; break; }
            String message = cause.getMessage();
            if (message != null && message.matches("COMPUTE_((interpreter|packages|archive|state|request)_(wasm|type|python|other)_ASSETMASK_[0-9]+(_APK_ASSET_UNAVAILABLE)?|STATE_TRANSFER_FAILED|FAILED|RENDERER_(CRASHED|KILLED)_STAGE_[a-z-]+)")) diagnostic = message;
            if (message != null && message.contains("checkpoint_pause")) { reason = "continuing"; break; }
            if (message != null && (message.contains("RENDERER_") || message.contains("_wasm"))) reason = "memory";
        }
        JSONObject value = meta();
        if (!value.has("scope")) return;
        value.put("diagnostic", diagnostic.isEmpty() ? "ANALYSIS_" + reason.toUpperCase(java.util.Locale.ROOT) : diagnostic);
        value.put("state", "running").put("failure", reason); save(value);
    }
    synchronized void finish(String state) throws Exception {
        finish(state, null);
    }
    synchronized void finish(String state, JSONObject output) throws Exception {
        JSONObject saved = meta();
        if (!saved.has("scope")) return;
        saved.put("state", state);
        org.json.JSONArray reasons = new org.json.JSONArray();
        org.json.JSONArray codes = output == null ? null : output.optJSONArray("blocking_reasons");
        if (state.equals("blocked") && codes != null) {
            for (int i = 0; i < Math.min(codes.length(), 8); i++) {
                String code = codes.optString(i);
                if (code.matches("[A-Z0-9_:.-]{1,160}")) reasons.put(code);
            }
        }
        saved.put("blockingReasons", reasons);
        if (state.equals("blocked") && reasons.length() == 0 && saved.optInt("responseStatus") == 200)
            saved.put("responseCode", "FORECAST_BLOCKED_WITHOUT_REASON");
        if (state.equals("complete") && saved.optInt("total") > 0) saved.put("done", saved.getInt("total"));
        save(saved);
    }
    synchronized void response(int status, JSONObject output) throws Exception {
        JSONObject saved = meta();
        if (!saved.has("scope")) return;
        saved.put("responseStatus", status);
        String code = output == null ? "" : output.optString("code");
        String diagnostic = output == null ? "" : output.optString("diagnostic");
        saved.put("responseCode", code.matches("[A-Z0-9_]{1,80}") ? code : "");
        saved.put("diagnostic", diagnostic.matches("[A-Za-z0-9_.:]{1,180}") ? diagnostic : "");
        save(saved);
    }
    synchronized void committed(long previous, long generation) throws Exception {
        JSONObject value = meta();
        if (!value.has("inputKey")) return;
        String expected = LocalStateStore.hex(MessageDigest.getInstance("SHA-256").digest(
            (previous + ":" + value.getString("inputKey")).getBytes(StandardCharsets.UTF_8)));
        if (!expected.equals(value.optString("scope"))) return;
        scope = LocalStateStore.hex(MessageDigest.getInstance("SHA-256").digest(
            (generation + ":" + value.getString("inputKey")).getBytes(StandardCharsets.UTF_8)));
        value.put("scope", scope); save(value);
    }
    JSObject status(boolean running) throws Exception {
        JSONObject value = new JSONObject(published);
        if (!value.has("scope")) return new JSObject().put("state", "idle");
        int done = value.optInt("done"), total = value.optInt("total");
        String state = value.optString("state");
        if (state.equals("running") && !running) state = "interrupted";
        return new JSObject().put("state", state).put("phase", value.optString("phase"))
            .put("percent", total > 0 ? Math.min(state.equals("complete") ? 100 : 99, done * 100 / total) : JSONObject.NULL)
            .put("savedUnits", done).put("totalUnits", total).put("savedRevision", value.optLong("revision"))
            .put("failure", value.optString("failure"))
            .put("responseStatus", value.optInt("responseStatus"))
            .put("responseCode", value.optString("responseCode"))
            .put("diagnostic", value.optString("diagnostic"))
            .put("blockingReasons", value.optJSONArray("blockingReasons") == null
                ? new org.json.JSONArray() : value.getJSONArray("blockingReasons"));
    }
}
