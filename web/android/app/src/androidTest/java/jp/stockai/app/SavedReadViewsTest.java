package jp.stockai.app;

import static org.junit.Assert.*;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import java.nio.file.Files;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class SavedReadViewsTest {
    @Test public void encryptedHistoricalViewsRejectTamperingAndWrongPaths() throws Exception {
        File dir = new File(InstrumentationRegistry.getInstrumentation().getTargetContext().getCacheDir(), "read-view-test-" + System.nanoTime());
        SavedReadViews views = new SavedReadViews(dir);
        try {
            assertFalse(views.read("/api/v1/home").getBoolean("available"));
            views.save("/api/v1/home", new JSONObject().put("status", 200).put("body", new JSONObject().put("fixture", "private-fixture")), 9);
            assertTrue(new SavedReadViews(dir).read("/api/v1/home").getBoolean("readOnly"));
            File[] files = dir.listFiles(); assertNotNull(files); assertEquals(1, files.length);
            byte[] bytes = Files.readAllBytes(files[0].toPath());
            assertFalse(new String(bytes, java.nio.charset.StandardCharsets.UTF_8).contains("private-fixture"));
            bytes[bytes.length - 1] ^= 1; Files.write(files[0].toPath(), bytes);
            try { views.read("/api/v1/home"); fail("Corrupt display accepted"); } catch (javax.crypto.AEADBadTagException expected) { }
            try { views.read("/api/v1/home?other=1"); fail("Unknown path accepted"); } catch (IllegalArgumentException expected) { }
            views.clear(); assertFalse(views.read("/api/v1/home").getBoolean("available"));
        } finally { views.clear(); dir.delete(); }
    }
}
