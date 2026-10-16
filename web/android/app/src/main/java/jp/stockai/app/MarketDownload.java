package jp.stockai.app;

import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.UUID;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;
import org.json.JSONArray;
import org.json.JSONObject;

/** Page receipts survive Activity/process loss until the shared database confirms the day. */
final class MarketDownload {
    static final Object LOCK = new Object();
    static final String[][] ENDPOINTS = {
        {"trading_calendar", "/markets/calendar"}, {"security_master", "/equities/master"},
        {"daily_prices", "/equities/bars/daily"}, {"topix", "/indices/bars/daily/topix"},
        {"financial_summary", "/fins/summary"}, {"valuations", "/equities/valuation"}
    };
    static final long MAX_BYTES = 64L * 1024 * 1024;
    interface Remote { JSONObject fetch(String endpoint, String day, String cursor) throws Exception; }
    final SQLiteDatabase db;
    final Remote remote;
    final String[][] endpoints;
    final boolean membershipOnly;
    String key(String day) { return membershipOnly ? "membership:" + day : day; }

    MarketDownload(SQLiteDatabase db, Remote remote) {
        this(db, remote, false);
    }
    MarketDownload(SQLiteDatabase db, Remote remote, boolean membershipOnly) {
        this.db = db; this.remote = remote; this.membershipOnly = membershipOnly;
        this.endpoints = membershipOnly ? new String[][]{ENDPOINTS[0], ENDPOINTS[1]} : ENDPOINTS;
        db.execSQL("CREATE TABLE IF NOT EXISTS market_downloads(day TEXT PRIMARY KEY, id TEXT NOT NULL UNIQUE, endpoint INTEGER NOT NULL, cursor TEXT, bytes INTEGER NOT NULL, received_at TEXT)");
        db.execSQL("CREATE TABLE IF NOT EXISTS market_download_pages(id TEXT NOT NULL, endpoint INTEGER NOT NULL, page INTEGER NOT NULL, input_cursor TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, received_at TEXT NOT NULL, row_count INTEGER NOT NULL, PRIMARY KEY(id,endpoint,page), UNIQUE(id,endpoint,input_cursor))");
        db.execSQL("CREATE TABLE IF NOT EXISTS market_download_chunks(id TEXT NOT NULL, endpoint INTEGER NOT NULL, page INTEGER NOT NULL, piece INTEGER NOT NULL, payload BLOB NOT NULL, PRIMARY KEY(id,endpoint,page,piece))");
        db.execSQL("CREATE TABLE IF NOT EXISTS market_download_retired(id TEXT PRIMARY KEY, day TEXT NOT NULL, retired_at TEXT NOT NULL)");
    }

    JSONObject fetch(String day) throws Exception {
        return fetch(day, Integer.MAX_VALUE, () -> false);
    }

    JSONObject fetch(String day, int pageBudget, java.util.function.BooleanSupplier stopped) throws Exception {
        if (pageBudget < 1) throw new IllegalArgumentException();
        synchronized (LOCK) {
            LocalDate selected = LocalDate.parse(day);
            LocalDate today = LocalDate.now(ZoneId.of("Asia/Tokyo"));
            if (!selected.toString().equals(day) || (membershipOnly ? selected.isAfter(today) : !selected.isBefore(today)))
                throw new IOException("CLOSED_SOURCE_DAY_REQUIRED");
            db.execSQL("INSERT OR IGNORE INTO market_downloads VALUES(?,?,0,NULL,0,NULL)",
                new Object[]{key(day), UUID.randomUUID().toString()});
            int fetched = 0;
            while (true) {
                if (stopped.getAsBoolean()) throw new InterruptedException();
                String id, cursor, previousReceipt; int index; long bytes;
                try (Cursor row = db.rawQuery("SELECT id,endpoint,cursor,bytes,received_at FROM market_downloads WHERE day=?", new String[]{key(day)})) {
                    if (!row.moveToFirst()) throw new IOException("DOWNLOAD_MISSING");
                    id = row.getString(0); index = row.getInt(1); cursor = row.getString(2);
                    bytes = row.getLong(3); previousReceipt = row.getString(4);
                }
                if (index == endpoints.length) return assemble(day, id, previousReceipt);
                if (fetched >= pageBudget) return new JSONObject().put("date", day).put("status", 202)
                    .put("acquisitionId", id);
                int count;
                try (Cursor rows = db.rawQuery("SELECT COUNT(*) FROM market_download_pages WHERE id=? AND endpoint=?", new String[]{id, String.valueOf(index)})) {
                    rows.moveToFirst(); count = rows.getInt(0);
                }
                if (count >= 100) throw new IOException("PAGE_LIMIT");
                JSONObject response = remote.fetch(endpoints[index][1], day, cursor);
                int status = response.getInt("status");
                if (status != 200) return new JSONObject().put("date", day).put("status", status)
                    .put("failedDataset", endpoints[index][0]).put("acquisitionId", id);
                JSONObject body = response.getJSONObject("body");
                JSONArray values = body.getJSONArray("data");
                if (values.length() > 50000) throw new IOException("PAGE_LIMIT");
                for (int i = 0; i < values.length(); i++) {
                    JSONObject value = values.getJSONObject(i);
                    LocalDate source = LocalDate.parse(value.getString(index == 4 ? "DiscDate" : "Date"));
                    if (index == 0 ? source.isBefore(selected) || source.isAfter(selected.plusDays(21)) : !source.equals(selected))
                        throw new IOException("SOURCE_DATE_CHANGED");
                }
                String next = body.isNull("pagination_key") ? "" : body.getString("pagination_key");
                if (next.length() > 8192 || (!next.isEmpty() && next.equals(cursor))) throw new IOException("PAGINATION_LOOP");
                if (!next.isEmpty()) try (Cursor prior = db.rawQuery(
                        "SELECT 1 FROM market_download_pages WHERE id=? AND endpoint=? AND input_cursor=?",
                        new String[]{id, String.valueOf(index), next})) {
                    if (prior.moveToFirst()) throw new IOException("PAGINATION_LOOP");
                }
                byte[] raw = values.toString().getBytes(StandardCharsets.UTF_8);
                if (raw.length > 20 * 1024 * 1024 || bytes + raw.length > MAX_BYTES) throw new IOException("DAY_SIZE_LIMIT");
                String received = response.getString("received_at");
                Instant receipt = Instant.parse(received);
                if (receipt.isAfter(Instant.now().plusSeconds(5)) || (previousReceipt != null && receipt.isBefore(Instant.parse(previousReceipt))))
                    throw new IOException("RECEIPT_CLOCK_CHANGED");
                String digest = StockAIPlugin.hex(MessageDigest.getInstance("SHA-256").digest(raw));
                db.beginTransaction();
                try {
                    byte[] compressed = compress(raw);
                    db.execSQL("INSERT INTO market_download_pages VALUES(?,?,?,?,?,?,?,?)",
                        new Object[]{id, index, count, cursor == null ? "" : cursor, compressed.length, digest, received, values.length()});
                    for (int offset = 0, piece = 0; offset < compressed.length; offset += 256 * 1024, piece++)
                        db.execSQL("INSERT INTO market_download_chunks VALUES(?,?,?,?,?)", new Object[]{id, index, count, piece,
                            java.util.Arrays.copyOfRange(compressed, offset, Math.min(compressed.length, offset + 256 * 1024))});
                    int following = next.isEmpty() ? index + 1 : index;
                    if (index == 0 && next.isEmpty() && !businessDay(id, day)) following = endpoints.length;
                    db.execSQL("UPDATE market_downloads SET endpoint=?,cursor=?,bytes=?,received_at=? WHERE day=? AND id=?",
                        new Object[]{following, next.isEmpty() ? null : next, bytes + raw.length, received, key(day), id});
                    db.setTransactionSuccessful();
                } finally { db.endTransaction(); }
                fetched++;
            }
        }
    }

    private boolean businessDay(String id, String day) throws Exception {
        JSONArray calendar = records(id, 0); JSONObject exact = null;
        for (int i = 0; i < calendar.length(); i++) if (calendar.getJSONObject(i).getString("Date").equals(day)) {
            if (exact != null) throw new IOException("DUPLICATE_CALENDAR_DAY"); exact = calendar.getJSONObject(i);
        }
        if (exact == null || !exact.optString("HolDiv").matches("[0-3]")) throw new IOException("CALENDAR_DAY_MISSING");
        return exact.getString("HolDiv").equals("1") || exact.getString("HolDiv").equals("2");
    }

    private JSONArray records(String id, int index) throws Exception {
        JSONArray result = new JSONArray();
        try (Cursor pages = db.rawQuery("SELECT page,size,sha256 FROM market_download_pages WHERE id=? AND endpoint=? ORDER BY page",
                new String[]{id, String.valueOf(index)})) {
            while (pages.moveToNext()) {
                ByteArrayOutputStream compressed = new ByteArrayOutputStream(); int piece = 0;
                int size = pages.getInt(1);
                if (size <= 0 || size > 21 * 1024 * 1024) throw new IOException("PAGE_SIZE_CHANGED");
                try (Cursor chunks = db.rawQuery("SELECT piece,payload FROM market_download_chunks WHERE id=? AND endpoint=? AND page=? ORDER BY piece",
                        new String[]{id, String.valueOf(index), String.valueOf(pages.getInt(0))})) {
                    while (chunks.moveToNext()) {
                        byte[] value = chunks.getBlob(1);
                        if (chunks.getInt(0) != piece++ || value.length > 256 * 1024 || compressed.size() + value.length > size)
                            throw new IOException("PAGE_CHUNKS_CHANGED");
                        compressed.write(value);
                    }
                }
                if (compressed.size() != size) throw new IOException("PAGE_CHUNKS_CHANGED");
                byte[] raw = StockAIPlugin.read(new GZIPInputStream(new ByteArrayInputStream(compressed.toByteArray())), 20 * 1024 * 1024);
                if (!StockAIPlugin.hex(MessageDigest.getInstance("SHA-256").digest(raw)).equals(pages.getString(2)))
                    throw new IOException("PAGE_RECEIPT_CHANGED");
                JSONArray values = new JSONArray(new String(raw, StandardCharsets.UTF_8));
                for (int i = 0; i < values.length(); i++) result.put(values.getJSONObject(i));
            }
        }
        return result;
    }

    private JSONObject assemble(String day, String id, String received) throws Exception {
        JSONObject datasets = new JSONObject();
        for (int i = 0; i < (membershipOnly ? endpoints.length : endpoints.length - 1); i++) datasets.put(endpoints[i][0], records(id, i));
        JSONArray receipts = new JSONArray();
        try (Cursor pages = db.rawQuery("SELECT endpoint,page,received_at,sha256,row_count FROM market_download_pages WHERE id=? ORDER BY endpoint,page", new String[]{id})) {
            while (pages.moveToNext()) receipts.put(new JSONObject().put("dataset", endpoints[pages.getInt(0)][0])
                .put("page", pages.getInt(1)).put("received_at", pages.getString(2))
                .put("sha256", pages.getString(3)).put("row_count", pages.getInt(4)));
        }
        JSONObject result = new JSONObject().put("status", 200).put("date", day).put("acquisitionId", id)
            .put("received_at", received).put("datasets", datasets).put("source_pages", receipts);
        if (membershipOnly) result.put("purpose", "membership");
        else result.put("valuations", records(id, endpoints.length - 1));
        return result;
    }

    void acknowledge(String day, String id) throws Exception {
        synchronized (LOCK) {
            db.beginTransaction();
            try {
                try (Cursor row = db.rawQuery("SELECT id,endpoint FROM market_downloads WHERE day=?", new String[]{key(day)})) {
                    if (!row.moveToFirst()) return;
                    if (!row.getString(0).equals(id)) return; // A later correction is a different acquisition.
                    if (row.getInt(1) != endpoints.length) throw new IOException("DOWNLOAD_NOT_COMMITTED");
                }
                db.execSQL("DELETE FROM market_download_pages WHERE id=?", new Object[]{id});
                db.execSQL("DELETE FROM market_download_chunks WHERE id=?", new Object[]{id});
                db.execSQL("DELETE FROM market_downloads WHERE day=? AND id=?", new Object[]{key(day), id});
                db.setTransactionSuccessful();
            } finally { db.endTransaction(); }
        }
    }

    void restart(String day) throws Exception {
        synchronized (LOCK) {
            LocalDate.parse(day);
            db.beginTransaction();
            try {
                // Preserve rejected page evidence. Only the active pointer changes.
                db.execSQL("INSERT OR IGNORE INTO market_download_retired SELECT id,day,? FROM market_downloads WHERE day=?",
                    new Object[]{Instant.now().toString(), key(day)});
                db.execSQL("DELETE FROM market_downloads WHERE day=?", new Object[]{key(day)});
                db.setTransactionSuccessful();
            } finally { db.endTransaction(); }
        }
    }

    static byte[] compress(byte[] raw) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try (GZIPOutputStream gzip = new GZIPOutputStream(output)) { gzip.write(raw); }
        return output.toByteArray();
    }
}
