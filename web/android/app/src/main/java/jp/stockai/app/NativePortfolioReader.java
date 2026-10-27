package jp.stockai.app;

import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.util.Base64;
import android.util.Base64InputStream;
import com.getcapacitor.JSObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HashSet;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.json.JSONObject;

/** Read the committed personal record without starting Python or unpacking market history. */
final class NativePortfolioReader {
    private static final long MAX_BYTES = 256L * 1024 * 1024;
    private static String digest(String text) throws Exception {
        return StockAIPlugin.hex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));
    }
    static String timestamp(String text) {
        java.time.OffsetDateTime time = java.time.OffsetDateTime.parse(text);
        String seconds = time.format(java.time.format.DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ss"));
        int micros = time.getNano() / 1000;
        return seconds + (micros == 0 ? "" : String.format(java.util.Locale.ROOT, ".%06d", micros))
            + (time.getOffset().getTotalSeconds() == 0 ? "+00:00" : time.getOffset().getId());
    }
    private static void copy(InputStream input, File target) throws Exception {
        try (FileOutputStream output = new FileOutputStream(target)) {
            byte[] buffer = new byte[64 * 1024]; long total = 0; int count;
            while ((count = input.read(buffer)) != -1) {
                total += count;
                if (total > MAX_BYTES) throw new SecurityException("PERSONAL_STATE_TOO_LARGE");
                output.write(buffer, 0, count);
            }
        }
    }
    // null means an old schema needs the existing Python migration, never an empty portfolio.
    static JSObject read(Context context, LocalStateStore state) throws Exception {
        return read(context, state, false);
    }
    static JSObject read(Context context, LocalStateStore state, boolean currentView) throws Exception {
        return read(context, state, currentView, null);
    }
    static JSObject readRecords(Context context, LocalStateStore state, String path) throws Exception {
        if (!NativeRecordViews.handles(path)) throw new IllegalArgumentException("INVALID_RECORD_VIEW");
        return read(context, state, false, path);
    }
    static JSObject readHomeWithDisplayCopy(Context context, LocalStateStore state, SavedReadViews views) throws Exception {
        return readRecordWithDisplayCopy(context, state, views, "/api/v1/home/ledger");
    }
    static boolean hasRecordDisplayCopy(String path) {
        return "/api/v1/home/ledger".equals(path) || "/api/v1/executions".equals(path)
            || "/api/v1/portfolio/history".equals(path);
    }
    static JSObject readRecordWithDisplayCopy(Context context, LocalStateStore state, SavedReadViews views, String path) throws Exception {
        if (!hasRecordDisplayCopy(path)) throw new IllegalArgumentException("INVALID_DISPLAY_RECORD");
        long epoch = views.epoch();
        long generation;
        JSObject result;
        try {
            generation = state.currentGeneration();
            result = readRecords(context, state, path);
        } catch (Exception error) {
            views.clear();
            throw error;
        }
        try {
            if (result != null && result.getInt("status") == 200 && state.currentGeneration() == generation)
                views.saveObjectAsyncIfUnchanged(path, result, generation, epoch);
        } catch (Exception ignored) { /* An optional display copy must not fail the authoritative read. */ }
        return result;
    }
    private static synchronized JSObject read(Context context, LocalStateStore state, boolean currentView, String recordPath) throws Exception {
        long started = android.os.SystemClock.elapsedRealtime();
        // Remove only this reader's interrupted temporary files, never a durable database.
        File[] interrupted = context.getCacheDir().listFiles((dir, name) -> name.startsWith("personal-read-"));
        if (interrupted != null) for (File file : interrupted) file.delete();
        File archive = File.createTempFile("personal-read-", ".zip", context.getCacheDir());
        File ledger = File.createTempFile("personal-read-", ".sqlite3", context.getCacheDir());
        try (LocalStateStore.StartupLease saved = state.openStartupLease()) {
            LocalStateStore.ReadLease source = saved.operations != null ? saved.operations : saved.base;
            if (source.length == 0) return recordPath == null ? null : new JSObject().put("status", 200).put("body", NativeRecordViews.empty(recordPath));
            StateArchiveMerge.LeaseInput raw = new StateArchiveMerge.LeaseInput(source);
            try (InputStream decoded = new Base64InputStream(raw, Base64.NO_WRAP)) { copy(decoded, archive); }
            raw.finish(); // Authenticate every ciphertext chunk, envelope hash and generation.
            try (ZipFile zip = new ZipFile(archive)) {
                archive.delete(); // Open descriptors remain usable; no persistent plaintext copy.
                HashSet<String> names = new HashSet<>();
                java.util.Enumeration<? extends ZipEntry> entries = zip.entries();
                while (entries.hasMoreElements()) {
                    ZipEntry entry = entries.nextElement();
                    if (entry.isDirectory() || !names.add(entry.getName())
                            || !(entry.getName().equals("operations.sqlite3")
                            || (saved.operations == null && entry.getName().equals("mobile.sqlite3"))))
                        throw new SecurityException("UNEXPECTED_PERSONAL_ARCHIVE");
                }
                if (!names.contains("operations.sqlite3")) return null;
                // No mobile.sqlite3 extraction, SQL scan or model/package loading.
                try (InputStream input = zip.getInputStream(zip.getEntry("operations.sqlite3"))) { copy(input, ledger); }
            }
            Object body;
            try (SQLiteDatabase db = SQLiteDatabase.openDatabase(ledger.getPath(), null,
                    SQLiteDatabase.OPEN_READONLY | SQLiteDatabase.NO_LOCALIZED_COLLATORS)) {
                ledger.delete();
                try (Cursor check = db.rawQuery("PRAGMA integrity_check", null)) {
                    if (!check.moveToFirst() || !"ok".equals(check.getString(0))) throw new SecurityException("PERSONAL_SQLITE_INTEGRITY");
                }
                if (recordPath != null) {
                    body = NativeRecordViews.read(db, recordPath);
                    if (body == null) return null;
                } else {
                try (Cursor table = db.rawQuery("SELECT name FROM sqlite_master WHERE type='table' AND name='manual_portfolio_imports'", null)) {
                    if (!table.moveToFirst()) return null;
                }
                try (Cursor row = db.rawQuery("SELECT payload,content_hash,export_sha256,revision_id,revision_sequence,owner_scope_hash FROM manual_portfolio_imports ORDER BY revision_sequence DESC LIMIT 1", null)) {
                    if (!row.moveToFirst()) return null;
                    String payload = row.getString(0);
                    if (!digest(payload).equals(row.getString(1))) throw new SecurityException("PERSONAL_CONTENT_HASH");
                    JSONObject imported = new JSONObject(payload);
                    String exportedText = imported.getString("export_json");
                    if (!"imported-manual-portfolio-v1".equals(imported.getString("schema_version"))
                            || !digest(exportedText).equals(imported.getString("export_sha256"))
                            || !imported.getString("export_sha256").equals(row.getString(2))) throw new SecurityException("PERSONAL_EXPORT_HASH");
                    JSONObject exported = new JSONObject(exportedText);
                    String revisionText = exported.getString("revision_json");
                    if (!"manual-portfolio-export-v1".equals(exported.getString("schema_version"))
                            || !digest(revisionText).equals(exported.getString("revision_id"))
                            || !exported.getString("revision_id").equals(row.getString(3))
                            || exported.getLong("revision_sequence") != row.getLong(4)) throw new SecurityException("PERSONAL_REVISION_HASH");
                    JSONObject revision = new JSONObject(revisionText);
                    if (!digest(revision.getString("owner")).equals(row.getString(5))
                            || Instant.parse(exported.getString("saved_at")).isAfter(Instant.parse(imported.getString("received_at"))))
                        throw new SecurityException("PERSONAL_RECEIPT_MISMATCH");
                    body = new JSONObject().put("revision_id", exported.getString("revision_id"))
                        .put("saved_at", timestamp(exported.getString("saved_at"))).put("portfolio", revision.getJSONObject("portfolio"));
                }
                if (currentView) {
                    body = currentBody(db, (JSONObject) body);
                    if (body == null) return null;
                }
                }
            }
            if (state.currentGeneration() != source.generation) throw new IllegalStateException("STATE_CONFLICT");
            android.util.Log.i("StockAIComputeTiming", "personal_read_ms="
                + (android.os.SystemClock.elapsedRealtime() - started) + " archive_chars=" + source.length
                + " operations_overlay=" + (saved.operations != null));
            return new JSObject().put("status", 200).put("body", body);
        } finally {
            archive.delete(); SQLiteDatabase.deleteDatabase(ledger);
        }
    }

    static JSONObject latestLedger(SQLiteDatabase db) throws Exception {
        JSONObject ledger = null;
        Instant latest = null;
        boolean tied = false;
        try (Cursor rows = db.rawQuery("SELECT portfolio_id,as_of,payload,content_hash FROM portfolio_states", null)) {
            while (rows.moveToNext()) {
                String payload = rows.getString(2);
                if (!digest(payload).equals(rows.getString(3))) throw new SecurityException("LEDGER_CONTENT_HASH");
                JSONObject value = new JSONObject(payload);
                Instant instant = Instant.parse(value.getString("as_of"));
                if (!rows.getString(0).equals(value.getString("portfolio_id"))
                        || !instant.equals(Instant.parse(rows.getString(1)))) throw new SecurityException("LEDGER_IDENTITY");
                if (latest == null || instant.isAfter(latest)) { ledger = value; latest = instant; tied = false; }
                else if (instant.equals(latest)) tied = true;
            }
        }
        if (tied || (latest != null && latest.isAfter(Instant.now()))) throw new SecurityException("LEDGER_BASE_CONFLICT");
        return ledger;
    }

    private static JSONObject currentBody(SQLiteDatabase db, JSONObject profile) throws Exception {
        try (Cursor tables = db.rawQuery("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('portfolio_states','mobile_personal_settings')", null)) {
            if (!tables.moveToFirst() || tables.getInt(0) != 2) return null;
        }
        JSONObject ledger = latestLedger(db), settings = null;
        String previous = null;
        int sequence = 0;
        try (Cursor rows = db.rawQuery("SELECT sequence,revision_id,payload,content_hash FROM mobile_personal_settings ORDER BY sequence", null)) {
            while (rows.moveToNext()) {
                String payload = rows.getString(2), hash = digest(payload);
                JSONObject value = new JSONObject(payload);
                if (!hash.equals(rows.getString(1)) || !hash.equals(rows.getString(3))
                        || rows.getInt(0) != ++sequence || value.getInt("sequence") != sequence
                        || (previous == null ? !value.isNull("parent") : !previous.equals(value.getString("parent"))))
                    throw new SecurityException("SETTINGS_CHAIN");
                settings = value.put("revision_id", hash); previous = hash;
            }
        }
        return new JSONObject().put("profile", profile).put("ledger", ledger == null ? JSONObject.NULL : ledger)
            .put("settings", settings == null ? JSONObject.NULL : settings);
    }
}
