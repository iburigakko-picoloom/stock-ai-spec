package jp.stockai.app;

import android.util.AtomicFile;
import com.getcapacitor.JSObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import org.json.JSONObject;

/** Encrypted historical display only. Never an input to a decision or a ledger write. */
final class SavedReadViews {
    private final File directory;
    private static final int MAX_BYTES = 2 * 1024 * 1024;
    SavedReadViews(File directory) { this.directory = directory; }
    static boolean allowed(String path) {
        return path != null && (path.equals("/api/v1/home") || path.equals("/api/v1/today")
            || path.matches("/api/v1/ranking\\?rankType=(overall|5d|20d|morning)&limit=50"));
    }
    private AtomicFile file(String path) throws Exception {
        if (!allowed(path)) throw new IllegalArgumentException("DISPLAY_PATH_NOT_ALLOWED");
        if (!directory.exists() && !directory.mkdirs()) throw new IllegalStateException("DISPLAY_UNAVAILABLE");
        String id = StockAIPlugin.hex(MessageDigest.getInstance("SHA-256").digest(path.getBytes(StandardCharsets.UTF_8)));
        return new AtomicFile(new File(directory, id));
    }
    synchronized void save(String path, JSONObject result, long generation) throws Exception {
        if (!allowed(path) || result.getInt("status") != 200) return;
        JSONObject envelope = new JSONObject().put("schema", 1).put("path", path)
            .put("savedAt", Instant.now().toString()).put("generation", generation)
            .put("body", result.get("body"));
        byte[] cipher = LocalStateStore.encrypt(envelope.toString());
        if (cipher.length > MAX_BYTES) { file(path).delete(); return; }
        AtomicFile target = file(path); FileOutputStream stream = null;
        try { stream = target.startWrite(); stream.write(cipher); target.finishWrite(stream); }
        catch (Exception error) { if (stream != null) target.failWrite(stream); throw error; }
    }
    synchronized JSObject read(String path) throws Exception {
        AtomicFile target = file(path);
        if (!target.getBaseFile().exists()) return new JSObject().put("available", false);
        if (target.getBaseFile().length() > MAX_BYTES) throw new SecurityException("DISPLAY_TOO_LARGE");
        JSONObject value = new JSONObject(LocalStateStore.decrypt(target.readFully()));
        if (value.getInt("schema") != 1 || !value.getString("path").equals(path)
                || value.getLong("generation") < 0 || Instant.parse(value.getString("savedAt")).isAfter(Instant.now()))
            throw new SecurityException("DISPLAY_INVALID");
        return new JSObject().put("available", true).put("savedAt", value.getString("savedAt"))
            .put("readOnly", true).put("body", value.get("body"));
    }
    synchronized void clear() {
        File[] files = directory.listFiles();
        if (files != null) for (File file : files) new AtomicFile(file).delete();
    }
}
