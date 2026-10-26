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
    JSONObject fixture() throws Exception {
        try(java.io.InputStream input=InstrumentationRegistry.getInstrumentation().getContext().getAssets().open("record-reader-fixture.json")){
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
    @Test public void emptyStateDoesNotStartPython() throws Exception {
        JSONObject result=NativePortfolioReader.readRecords(context,owner.state,"/api/v1/execution-context").getJSONObject("body");
        assertTrue(result.isNull("proposal"));assertTrue(result.isNull("decision"));
        JSONObject note=NativePortfolioReader.readRecords(context,owner.state,"/api/v1/stocks/7203/note").getJSONObject("body");
        assertEquals("",note.getString("text"));assertTrue(note.isNull("revision"));
        java.lang.reflect.Field host=LocalComputeOwner.class.getDeclaredField("host");host.setAccessible(true);assertNull(host.get(owner));
    }
}
