package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import android.database.sqlite.SQLiteDatabase;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import java.io.IOException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class MarketDownloadTest {
    SQLiteDatabase db;
    File file;
    final String day = "2026-01-05";
    final List<String> calls = new ArrayList<>();
    @Before public void open() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        file = File.createTempFile("market-fixture-", ".sqlite3", context.getCacheDir());
        db = SQLiteDatabase.openOrCreateDatabase(file, null);
    }
    @After public void close() {
        if (db != null) db.close();
        if (file != null) SQLiteDatabase.deleteDatabase(file);
    }
    JSONObject page(JSONArray data, String next) throws Exception {
        return new JSONObject().put("status", 200).put("received_at", Instant.now().toString())
            .put("body", new JSONObject().put("data", data).put("pagination_key", next));
    }
    JSONObject ordinary(String endpoint, String selected, String cursor) throws Exception {
        calls.add(endpoint + ":" + cursor);
        JSONObject row = new JSONObject().put(endpoint.equals("/fins/summary") ? "DiscDate" : "Date", selected);
        if (endpoint.equals("/markets/calendar")) row.put("HolDiv", 1);
        else row.put("Code", "12340");
        return page(new JSONArray().put(row), "");
    }
    @Test public void interruptedPagesResumeAfterDatabaseReopenAndCompletedReceiptIsReused() throws Exception {
        MarketDownload first = new MarketDownload(db, (endpoint, selected, cursor) -> {
            if (endpoint.equals("/equities/master")) {
                if (cursor == null) return page(new JSONArray().put(new JSONObject().put("Date", day).put("Code", "12340")), "second");
                throw new IOException("synthetic network interruption");
            }
            return ordinary(endpoint, selected, cursor);
        });
        try { first.fetch(day); fail("network interruption accepted"); } catch (IOException expected) { }
        db.close(); db = SQLiteDatabase.openOrCreateDatabase(file, null);
        MarketDownload resumed = new MarketDownload(db, (endpoint, selected, cursor) -> {
            if (endpoint.equals("/equities/master")) assertEquals("second", cursor);
            assertFalse(endpoint.equals("/markets/calendar"));
            return ordinary(endpoint, selected, cursor);
        });
        JSONObject result = resumed.fetch(day);
        assertEquals(2, result.getJSONObject("datasets").getJSONArray("security_master").length());
        assertEquals(1, result.getJSONArray("valuations").length());
        MarketDownload recovered = new MarketDownload(db, (e, d, c) -> { throw new AssertionError("completed request resent"); });
        assertEquals(result.toString(), recovered.fetch(day).toString());
        recovered.acknowledge(day, "wrong-id");
        assertEquals(result.getString("acquisitionId"), recovered.fetch(day).getString("acquisitionId"));
        recovered.acknowledge(day, result.getString("acquisitionId"));
        assertNotEquals(result.getString("acquisitionId"), new MarketDownload(db, this::ordinary).fetch(day).getString("acquisitionId"));
        // A delayed acknowledgment of the previous observation cannot delete the correction.
        recovered.acknowledge(day, result.getString("acquisitionId"));
        recovered.fetch(day);
    }
    @Test public void forbiddenPlanPreservesPageAndCannotBeAcknowledged() throws Exception {
        MarketDownload journal = new MarketDownload(db, (endpoint, selected, cursor) -> {
            if (endpoint.equals("/equities/valuation")) return new JSONObject().put("status", 403);
            return ordinary(endpoint, selected, cursor);
        });
        JSONObject result = journal.fetch(day);
        assertEquals(403, result.getInt("status"));
        assertFalse(result.has("datasets"));
        try { journal.acknowledge(day, result.getString("acquisitionId")); fail("partial day acknowledged"); }
        catch (IOException expected) { }
        int previous = calls.size();
        JSONObject completed = new MarketDownload(db, this::ordinary).fetch(day);
        assertEquals(previous + 1, calls.size());
        assertEquals(result.getString("acquisitionId"), completed.getString("acquisitionId"));
    }
    @Test public void paginationCycleAndWrongSourceDateDoNotAdvanceTheCursor() throws Exception {
        MarketDownload journal = new MarketDownload(db, (endpoint, selected, cursor) ->
            page(new JSONArray().put(new JSONObject().put("Date", day).put("HolDiv", "1")), "cycle"));
        try { journal.fetch(day); fail("cycle accepted"); } catch (IOException expected) { }
        MarketDownload invalid = new MarketDownload(db, (e, d, c) ->
            page(new JSONArray().put(new JSONObject().put("Date", "2026-01-04")), ""));
        try { invalid.fetch(day); fail("out of range row accepted"); } catch (IOException expected) { }
        MarketDownload valid = new MarketDownload(db, (endpoint, selected, cursor) -> {
            if (endpoint.equals("/markets/calendar")) { assertEquals("cycle", cursor); return page(new JSONArray(), ""); }
            return ordinary(endpoint, selected, cursor);
        });
        assertEquals(200, valid.fetch(day).getInt("status"));
    }
    @Test public void holidaysUseOnlyCalendarWithoutInventingPrices() throws Exception {
        MarketDownload journal = new MarketDownload(db, (endpoint, selected, cursor) -> {
            assertEquals("/markets/calendar", endpoint);
            return page(new JSONArray().put(new JSONObject().put("Date", day).put("HolDiv", 0)), "");
        });
        JSONObject result = journal.fetch(day);
        assertEquals(0, result.getJSONObject("datasets").getJSONArray("daily_prices").length());
        assertEquals(0, result.getJSONArray("valuations").length());
    }
    @Test public void explicitRestartPreservesRejectedEvidenceAndReplacesOnlyTheActiveAcquisition() throws Exception {
        MarketDownload journal = new MarketDownload(db, this::ordinary);
        String original = journal.fetch(day).getString("acquisitionId");
        journal.restart(day);
        JSONObject next = journal.fetch(day);
        assertNotEquals(original, next.getString("acquisitionId"));
        try (android.database.Cursor rows = db.rawQuery("SELECT COUNT(*) FROM market_download_pages WHERE id=?", new String[]{original})) {
            rows.moveToFirst(); assertEquals(6, rows.getInt(0));
        }
        journal.acknowledge(day, original);
        assertEquals(next.getString("acquisitionId"), journal.fetch(day).getString("acquisitionId"));
    }
    @Test public void pagesLargerThanCursorWindowSurviveAndTamperingIsRejected() throws Exception {
        byte[] data = new byte[3 * 1024 * 1024]; new Random(7).nextBytes(data);
        String large = android.util.Base64.encodeToString(data, android.util.Base64.NO_WRAP);
        MarketDownload journal = new MarketDownload(db, (endpoint, selected, cursor) -> {
            if (!endpoint.equals("/equities/master")) return ordinary(endpoint, selected, cursor);
            return page(new JSONArray().put(new JSONObject().put("Date", day).put("Code", "12340").put("fixture", large)), "");
        });
        JSONObject result = journal.fetch(day);
        assertEquals(large, result.getJSONObject("datasets").getJSONArray("security_master").getJSONObject(0).getString("fixture"));
        db.execSQL("UPDATE market_download_chunks SET payload=? WHERE endpoint=1 AND piece=0", new Object[]{new byte[]{1, 2}});
        try { journal.fetch(day); fail("corrupt page accepted"); } catch (IOException expected) { }
    }
}
