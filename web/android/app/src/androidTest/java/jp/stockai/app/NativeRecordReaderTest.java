package jp.stockai.app;

import static org.junit.Assert.*;
import android.content.Context;
import android.database.sqlite.SQLiteDatabase;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
import org.json.JSONArray;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class NativeRecordReaderTest {
    Context context;
    File file;
    LocalComputeOwner owner;
    @Before public void isolatedOwner() throws Exception {
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(context.getPackageName().endsWith(".debug"));
        file = File.createTempFile("record-reader-test-", ".sqlite3", context.getCacheDir());
        owner = LocalComputeOwner.get(context, file);
    }
    @After public void cleanup() throws Exception {
        if (owner != null) owner.closeForTest().get(30, TimeUnit.SECONDS);
        if (file != null) SQLiteDatabase.deleteDatabase(file);
    }
    static void equalJson(Object left, Object right) throws Exception {
        if (left instanceof JSONObject) {
            JSONObject a=(JSONObject)left,b=(JSONObject)right;
            assertEquals(a.length(),b.length());
            java.util.Iterator<String> keys=a.keys();
            while(keys.hasNext()){String key=keys.next();equalJson(a.get(key),b.get(key));}
        } else if(left instanceof JSONArray){
            JSONArray a=(JSONArray)left,b=(JSONArray)right;assertEquals(a.length(),b.length());
            for(int i=0;i<a.length();i++)equalJson(a.get(i),b.get(i));
        } else if(left instanceof Number) assertEquals(((Number)left).doubleValue(),((Number)right).doubleValue(),0);
        else assertEquals(left,right);
    }
    JSONObject fixture() throws Exception { return fixture("record-reader-fixture.json"); }
    JSONObject fixture(String name) throws Exception {
        try(java.io.InputStream input=InstrumentationRegistry.getInstrumentation().getContext().getAssets().open(name)){
            java.io.ByteArrayOutputStream bytes=new java.io.ByteArrayOutputStream();
            byte[] buffer=new byte[8192];int count;
            while((count=input.read(buffer))!=-1)bytes.write(buffer,0,count);
            JSONObject value=new JSONObject(bytes.toString("UTF-8"));assertTrue(value.getBoolean("synthetic_only"));return value;
        }
    }
    @Test public void executionAndMemoMatchPythonAndBypassColdAndBusyInterpreter() throws Exception {
        JSONObject fixture=fixture();owner.state.write(owner.state.currentGeneration(),fixture.getString("state"));
        java.lang.reflect.Field host=LocalComputeOwner.class.getDeclaredField("host");host.setAccessible(true);
        assertNull(host.get(owner));
        long started=android.os.SystemClock.elapsedRealtime();
        equalJson(fixture.getJSONObject("expected_execution"),NativePortfolioReader.readRecords(context,owner.state,"/api/v1/execution-context").getJSONObject("body"));
        long direct=android.os.SystemClock.elapsedRealtime()-started;
        equalJson(fixture.getJSONObject("expected_note"),NativePortfolioReader.readRecords(context,owner.state,"/api/v1/stocks/7203/note").getJSONObject("body"));
        assertNull("Reads must not start Python",host.get(owner));
        CountDownLatch entered=new CountDownLatch(1), release=new CountDownLatch(1);
        java.lang.reflect.Field queue=LocalComputeOwner.class.getDeclaredField("queue");queue.setAccessible(true);
        ((ExecutorService)queue.get(owner)).execute(()->{entered.countDown();try{release.await();}catch(InterruptedException error){Thread.currentThread().interrupt();}});
        try {
            assertTrue(entered.await(10,TimeUnit.SECONDS));
            equalJson(fixture.getJSONObject("expected_execution"),NativePortfolioReader.readRecords(context,owner.state,"/api/v1/execution-context").getJSONObject("body"));
            equalJson(fixture.getJSONObject("expected_note"),NativePortfolioReader.readRecords(context,owner.state,"/api/v1/stocks/7203/note").getJSONObject("body"));
        } finally {release.countDown();}
        started=android.os.SystemClock.elapsedRealtime();
        equalJson(fixture.getJSONObject("expected_execution"),owner.request("GET","/api/v1/execution-context","null").get(300,TimeUnit.SECONDS).getJSONObject("body"));
        long cold=android.os.SystemClock.elapsedRealtime()-started;
        assertTrue("Direct read must beat cold Python",direct<cold);
        android.util.Log.i("StockAIRecordBenchmark","direct_ms="+direct+" cold_python_ms="+cold);
        assertEquals(0,context.getCacheDir().listFiles((dir,name)->name.startsWith("personal-read-")).length);
    }
    @Test public void memoSaveUsesOperationsOverlayAndSurvivesOwnerReopen() throws Exception {
        JSONObject fixture=fixture();owner.state.write(owner.state.currentGeneration(),fixture.getString("state"));
        JSONObject original=fixture.getJSONObject("expected_note");
        JSONObject body=new JSONObject().put("expectedRevision",original.getString("revision")).put("text","SYNTHETIC_UI_TEST: 保存後のメモ");
        JSONObject result=owner.request("POST","/api/v1/stocks/7203/note",body.toString()).get(300,TimeUnit.SECONDS);
        assertEquals(200,result.getInt("status"));
        try(LocalStateStore.StartupLease lease=owner.state.openStartupLease()){assertNotNull(lease.operations);}
        owner.closeForTest().get(30,TimeUnit.SECONDS);owner=LocalComputeOwner.get(context,file);
        equalJson(result.getJSONObject("body"),NativePortfolioReader.readRecords(context,owner.state,"/api/v1/stocks/7203/note").getJSONObject("body"));
        equalJson(fixture.getJSONObject("expected_execution"),NativePortfolioReader.readRecords(context,owner.state,"/api/v1/execution-context").getJSONObject("body"));
    }
    @Test public void manualTradeWithoutDecisionCommitsAtomicallyAndSurvivesRetryRestore() throws Exception {
        JSONObject fixture=fixture("manual-trade-fixture.json");
        owner.state.write(owner.state.currentGeneration(),fixture.getString("state"));
        equalJson(fixture.get("context"),NativePortfolioReader.readRecords(context,owner.state,"/api/v1/execution-entry-context").get("body"));
        java.lang.reflect.Field host=LocalComputeOwner.class.getDeclaredField("host");host.setAccessible(true);
        assertNull(host.get(owner));
        String path="/api/v1/executions/manual";
        JSONObject bad=new JSONObject(fixture.getJSONObject("trade_body").toString()).put("averageFillPrice","999999");
        assertEquals(422,owner.request("POST",path,bad.toString()).get(300,TimeUnit.SECONDS).getInt("status"));
        assertEquals(0,owner.request("GET","/api/v1/executions","null").get(300,TimeUnit.SECONDS).getJSONObject("body").getJSONArray("records").length());
        String body=fixture.getJSONObject("trade_body").toString();
        JSONObject result=owner.request("POST",path,body).get(300,TimeUnit.SECONDS);
        assertEquals(result.toString(),201,result.getInt("status"));
        equalJson(fixture.get("expected_trade"),result.get("body"));
        try(LocalStateStore.StartupLease lease=owner.state.openStartupLease()){assertNotNull(lease.operations);}
        owner.closeForTest().get(30,TimeUnit.SECONDS);owner=LocalComputeOwner.get(context,file);
        assertEquals(201,owner.request("POST",path,body).get(300,TimeUnit.SECONDS).getInt("status"));
        JSONObject expected=fixture.getJSONObject("expected_after");
        java.util.Iterator<String> paths=expected.keys();
        while(paths.hasNext()){String read=paths.next();equalJson(expected.get(read),NativePortfolioReader.readRecords(context,owner.state,read).get("body"));}
        String backup=owner.readState().get(300,TimeUnit.SECONDS).getString("payload");
        owner.closeForTest().get(30,TimeUnit.SECONDS);owner=LocalComputeOwner.get(context,file);
        owner.state.write(owner.state.currentGeneration(),backup);
        equalJson(expected.get("/api/v1/home/ledger"),NativePortfolioReader.readRecords(context,owner.state,"/api/v1/home/ledger").get("body"));
        assertTrue(owner.request("GET","/api/v1/execution-context","null").get(300,TimeUnit.SECONDS).getJSONObject("body").isNull("decision"));
    }
    @Test public void emptyStateDoesNotStartPython() throws Exception {
        JSONObject result=NativePortfolioReader.readRecords(context,owner.state,"/api/v1/execution-context").getJSONObject("body");
        assertTrue(result.isNull("proposal"));assertTrue(result.isNull("decision"));
        JSONObject note=NativePortfolioReader.readRecords(context,owner.state,"/api/v1/stocks/7203/note").getJSONObject("body");
        assertEquals("",note.getString("text"));assertTrue(note.isNull("revision"));
        java.lang.reflect.Field host=LocalComputeOwner.class.getDeclaredField("host");host.setAccessible(true);assertNull(host.get(owner));
    }
    @Test public void executionWritesCommitOnlyOperationsAndSurviveReopenWithoutDoubleApplication() throws Exception {
        JSONObject fixture=fixture();owner.state.write(owner.state.currentGeneration(),fixture.getString("state"));
        owner.request("GET","/api/v1/health","null").get(300,TimeUnit.SECONDS);
        String baseHash;
        try(LocalStateStore.StartupLease lease=owner.state.openStartupLease()){baseHash=lease.base.expectedHash;}
        String path="/api/v1/decisions/synthetic-record-reader/executions";
        String body=fixture.getJSONObject("trade_body").toString();
        JSONObject response=owner.request("POST",path,body).get(300,TimeUnit.SECONDS);
        assertEquals(201,response.getInt("status"));equalJson(fixture.get("expected_trade"),response.get("body"));
        try(LocalStateStore.StartupLease lease=owner.state.openStartupLease()){
            assertNotNull(lease.operations);assertEquals(baseHash,lease.base.expectedHash);
        }
        owner.closeForTest().get(30,TimeUnit.SECONDS);owner=LocalComputeOwner.get(context,file);
        // A response-loss retry after reopening must retain the original execution ID.
        assertEquals(201,owner.request("POST",path,body).get(300,TimeUnit.SECONDS).getInt("status"));
        JSONObject applied=owner.request("POST","/api/v1/portfolio/apply-executions",fixture.getJSONObject("apply_body").toString()).get(300,TimeUnit.SECONDS);
        assertEquals(200,applied.getInt("status"));equalJson(fixture.get("expected_apply"),applied.get("body"));
        try(LocalStateStore.StartupLease lease=owner.state.openStartupLease()){
            assertNotNull(lease.operations);assertEquals(baseHash,lease.base.expectedHash);
        }
        owner.closeForTest().get(30,TimeUnit.SECONDS);owner=LocalComputeOwner.get(context,file);
        JSONObject expected=fixture.getJSONObject("expected_after");
        java.util.Iterator<String> paths=expected.keys();
        while(paths.hasNext()){
            String read=paths.next();equalJson(expected.get(read),NativePortfolioReader.readRecords(context,owner.state,read).get("body"));
        }
        // Retrying the identical apply may be rejected as old, but must never change balances.
        owner.request("POST","/api/v1/portfolio/apply-executions",fixture.getJSONObject("apply_body").toString()).get(300,TimeUnit.SECONDS);
        equalJson(expected.get("/api/v1/home/ledger"),NativePortfolioReader.readRecords(context,owner.state,"/api/v1/home/ledger").get("body"));
        // Full backup composition must also include the durable operations overlay.
        String backup=owner.readState().get(300,TimeUnit.SECONDS).getString("payload");
        owner.closeForTest().get(30,TimeUnit.SECONDS);owner=LocalComputeOwner.get(context,file);
        owner.state.write(owner.state.currentGeneration(),backup);
        equalJson(expected.get("/api/v1/home/ledger"),NativePortfolioReader.readRecords(context,owner.state,"/api/v1/home/ledger").get("body"));
        equalJson(expected.get("/api/v1/executions"),owner.request("GET","/api/v1/executions","null").get(300,TimeUnit.SECONDS).get("body"));
    }
    @Test public void balancesAndHistoriesMatchPythonWithoutStartingOrWaitingForPython() throws Exception {
        JSONObject fixture=fixture();owner.state.write(owner.state.currentGeneration(),fixture.getString("state"));
        JSONObject expected=fixture.getJSONObject("expected_views");
        CountDownLatch entered=new CountDownLatch(1), release=new CountDownLatch(1);
        java.lang.reflect.Field queue=LocalComputeOwner.class.getDeclaredField("queue");queue.setAccessible(true);
        ((ExecutorService)queue.get(owner)).execute(()->{entered.countDown();try{release.await();}catch(InterruptedException error){Thread.currentThread().interrupt();}});
        long direct=0;
        try {
            assertTrue(entered.await(10,TimeUnit.SECONDS));
            java.util.Iterator<String> paths=expected.keys();
            while(paths.hasNext()){
                String path=paths.next();long started=android.os.SystemClock.elapsedRealtime();
                equalJson(expected.get(path),NativePortfolioReader.readRecords(context,owner.state,path).get("body"));
                long elapsed=android.os.SystemClock.elapsedRealtime()-started;
                if(path.equals("/api/v1/home/ledger"))direct=elapsed;
                android.util.Log.i("StockAIDisplayBenchmark",path+" direct_ms="+elapsed);
            }
            java.lang.reflect.Field host=LocalComputeOwner.class.getDeclaredField("host");host.setAccessible(true);assertNull(host.get(owner));
            owner.readViews.save("/api/v1/stocks/B",new JSONObject().put("status",200).put("body",new JSONObject().put("symbol","B")),owner.state.currentGeneration());
            assertTrue(owner.readViews.read("/api/v1/stocks/B").getBoolean("available"));
            assertFalse(SavedReadViews.allowed("/api/v1/proposals/current/decision"));
            assertFalse(SavedReadViews.allowed("/api/v1/mobile/chatgpt-manual/status"));
        }finally{release.countDown();}
        long started=android.os.SystemClock.elapsedRealtime();
        equalJson(expected.get("/api/v1/home/ledger"),owner.request("GET","/api/v1/home/ledger","null").get(300,TimeUnit.SECONDS).getJSONObject("body"));
        long cold=android.os.SystemClock.elapsedRealtime()-started;
        assertTrue(direct<cold);
        android.util.Log.i("StockAIDisplayBenchmark","home_direct_ms="+direct+" cold_python_ms="+cold);
    }
}
