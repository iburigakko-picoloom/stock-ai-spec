package jp.stockai.app;

import android.util.AtomicFile;
import com.getcapacitor.JSObject;
import java.io.File;
import java.io.FileOutputStream;
import java.lang.ref.WeakReference;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
import org.json.JSONArray;

/** Encrypted historical display only. Never an input to a decision or a ledger write. */
final class SavedReadViews {
    private static final java.util.Map<String, SavedReadViews> instances = new java.util.HashMap<>();
    static synchronized SavedReadViews forDatabase(File database) throws Exception {
        String path = database.getCanonicalPath();
        SavedReadViews views = instances.get(path);
        if (views == null) {
            views = new SavedReadViews(new File(path + ".readviews"));
            instances.put(path, views);
        }
        return views;
    }
    private final File directory;
    private static final int MAX_BYTES = 2 * 1024 * 1024;
    private final Executor writer;
    interface Decoder { String decrypt(byte[] cipher) throws Exception; }
    private final Decoder decoder;
    private long epoch;
    private final Map<String, Long> fileRevisions = new HashMap<>();
    private long nextFileRevision;
    private long revisionFor(String path) { return fileRevisions.getOrDefault(path, 0L); }
    private void changedFile(String path) { fileRevisions.put(path, ++nextFileRevision); }
    private long nextTicket;
    private final Map<String, Long> latest = new HashMap<>();
    SavedReadViews(File directory) {
        this(directory, new ThreadPoolExecutor(0, 1, 30, TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(4), task -> {
                Thread thread = new Thread(task, "stockai-view-copy"); thread.setDaemon(true); return thread;
            }));
    }
    // Injectable executor keeps ordering and invalidation races deterministic in tests.
    SavedReadViews(File directory, Executor writer) { this(directory, writer, LocalStateStore::decrypt); }
    SavedReadViews(File directory, Executor writer, Decoder decoder) { this.directory = directory; this.writer = writer; this.decoder = decoder; }
    static boolean allowed(String path) {
        return path != null && (path.equals("/api/v1/home") || path.equals("/api/v1/home/ledger") || path.equals("/api/v1/today")
            || path.equals("/api/v1/mobile/portfolio")
            || path.equals("/api/v1/executions") || path.equals("/api/v1/portfolio/history")
            || path.matches("/api/v1/mobile/ranking/(5d|20d)")
            || path.matches("/api/v1/stocks/[A-Z0-9]{1,10}")
            || path.matches("/api/v1/validation\\?mode=(paper|live|historical)")
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
        if (cipher.length > MAX_BYTES) { file(path).delete(); changedFile(path); return; }
        AtomicFile target = file(path); FileOutputStream stream = null;
        try { stream = target.startWrite(); stream.write(cipher); target.finishWrite(stream); changedFile(path); }
        catch (Exception error) { if (stream != null) target.failWrite(stream); throw error; }
    }
    /** Queue only an optional encrypted display copy; the authoritative response never waits for it. */
    synchronized long epoch() { return epoch; }
    synchronized void saveAsyncIfUnchanged(String path, String result, long generation, long observedEpoch) {
        if (epoch == observedEpoch) saveAsync(path, result, generation);
    }
    synchronized void saveAsync(String path, String result, long generation) {
        // An oversized string must not be retained in the bounded writer queue.
        enqueue(path, result.length() > MAX_BYTES ? null : result, null, generation);
    }
    synchronized void saveObjectAsyncIfUnchanged(String path, JSONObject result, long generation, long observedEpoch) {
        if (epoch == observedEpoch) enqueue(path, null, new WeakReference<>(result), generation);
    }
    private void enqueue(String path, String bounded, WeakReference<JSONObject> object, long generation) {
        if (!allowed(path)) return;
        long capturedEpoch = epoch, ticket = ++nextTicket;
        latest.put(path, ticket);
        String savedAt = Instant.now().toString();
        try {
            writer.execute(() -> {
                try {
                    synchronized (this) {
                        if (epoch != capturedEpoch || !Long.valueOf(ticket).equals(latest.get(path))) return;
                    }
                    byte[] cipher = null;
                    // Direct-record replies are immutable after publication. A weak
                    // reference keeps the optional queue from retaining a large reply.
                    JSONObject response = object != null ? object.get() : bounded == null ? null : new JSONObject(bounded);
                    if (object != null && response == null) return; // Collected before the optional copy ran.
                    if (response != null) {
                        if (response.getInt("status") != 200) throw new SecurityException("DISPLAY_STATUS_INVALID");
                        JSONObject envelope = new JSONObject().put("schema", 1).put("path", path)
                            .put("savedAt", savedAt).put("generation", generation).put("body", response.get("body"));
                        if (object == null || fitsDisplayBudget(envelope, new long[]{MAX_BYTES - 64}, 0))
                            cipher = LocalStateStore.encrypt(envelope.toString());
                    }
                    synchronized (this) {
                        if (epoch != capturedEpoch || !Long.valueOf(ticket).equals(latest.get(path))) return;
                        AtomicFile target = file(path);
                        if (cipher == null || cipher.length > MAX_BYTES) { target.delete(); changedFile(path); return; }
                        FileOutputStream stream = null;
                        try { stream = target.startWrite(); stream.write(cipher); target.finishWrite(stream); changedFile(path); }
                        catch (Exception error) { if (stream != null) target.failWrite(stream); throw error; }
                    }
                } catch (Exception error) {
                    synchronized (this) {
                        if (epoch == capturedEpoch && Long.valueOf(ticket).equals(latest.get(path))) clear();
                    }
                } finally {
                    synchronized (this) {
                        if (epoch == capturedEpoch && Long.valueOf(ticket).equals(latest.get(path))) latest.remove(path);
                    }
                }
            });
        } catch (RejectedExecutionException ignored) {
            // The copy is optional. Keep the previous read-only copy if the bounded queue is busy.
            if (Long.valueOf(ticket).equals(latest.get(path))) latest.remove(path);
        }
    }
    // Bound the optional object before serializing it on the background writer.
    // Non-ASCII characters are conservatively counted as six bytes each.
    private static boolean fitsDisplayBudget(Object value, long[] remaining, int depth) throws Exception {
        if (depth > 48 || --remaining[0] < 0) return false;
        if (value == null || value == JSONObject.NULL) return consume(remaining, 4);
        if (value instanceof String) {
            String text = (String) value;
            if (!consume(remaining, 2)) return false;
            for (int i = 0; i < text.length(); i++) {
                char c = text.charAt(i);
                if (!consume(remaining, c < 32 || c >= 127 ? 6 : c == '"' || c == '\\' || c == '/' ? 2 : 1)) return false;
            }
            return true;
        }
        if (value instanceof JSONObject) {
            if (!consume(remaining, 2)) return false;
            JSONObject object = (JSONObject) value;
            java.util.Iterator<String> keys = object.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                if (!consume(remaining, 2) || !fitsDisplayBudget(key, remaining, depth + 1)
                        || !fitsDisplayBudget(object.get(key), remaining, depth + 1)) return false;
            }
            return true;
        }
        if (value instanceof JSONArray) {
            if (!consume(remaining, 2)) return false;
            JSONArray array = (JSONArray) value;
            for (int i = 0; i < array.length(); i++)
                if (!consume(remaining, 1) || !fitsDisplayBudget(array.get(i), remaining, depth + 1)) return false;
            return true;
        }
        if (value instanceof Boolean || value instanceof Integer || value instanceof Long
                || value instanceof Double || value instanceof Float || value instanceof Short || value instanceof Byte)
            return consume(remaining, value.toString().length());
        return false;
    }
    private static boolean consume(long[] remaining, long amount) {
        remaining[0] -= amount;
        return remaining[0] >= 0;
    }
    interface Delivery { void accept(JSObject result); }
    void readAndDeliver(String path, Delivery delivery) throws Exception {
        byte[] cipher;
        long readEpoch, readRevision;
        synchronized (this) {
            AtomicFile target = file(path);
            if (!target.getBaseFile().exists()) { delivery.accept(new JSObject().put("available", false)); return; }
            if (target.getBaseFile().length() > MAX_BYTES) throw new SecurityException("DISPLAY_TOO_LARGE");
            cipher = target.readFully();
            readEpoch = epoch;
            readRevision = revisionFor(path);
        }
        JSONObject value;
        try {
            value = new JSONObject(decoder.decrypt(cipher));
            if (value.getInt("schema") != 1 || !value.getString("path").equals(path)
                    || value.getLong("generation") < 0 || Instant.parse(value.getString("savedAt")).isAfter(Instant.now()))
                throw new SecurityException("DISPLAY_INVALID");
        } catch (Exception error) {
            synchronized (this) {
                if (epoch != readEpoch || revisionFor(path) != readRevision) { delivery.accept(new JSObject().put("available", false)); return; }
            }
            throw error;
        }
        synchronized (this) {
            if (epoch != readEpoch || revisionFor(path) != readRevision) { delivery.accept(new JSObject().put("available", false)); return; }
            delivery.accept(new JSObject().put("available", true).put("savedAt", value.getString("savedAt"))
                .put("readOnly", true).put("body", value.get("body")));
        }
    }
    JSObject read(String path) throws Exception {
        JSObject[] result = new JSObject[1];
        readAndDeliver(path, value -> result[0] = value);
        return result[0];
    }
    synchronized void clear() {
        epoch++; fileRevisions.clear(); latest.clear();
        File[] files = directory.listFiles();
        if (files != null) for (File file : files) new AtomicFile(file).delete();
    }
}
