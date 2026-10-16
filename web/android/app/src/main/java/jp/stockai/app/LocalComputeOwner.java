package jp.stockai.app;

import android.content.Context;
import android.database.sqlite.SQLiteDatabase;
import android.os.Looper;
import com.getcapacitor.JSObject;
import java.io.File;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONObject;

/** One serialized interpreter and durable writer per application database. */
final class LocalComputeOwner {
    private static final Map<String, LocalComputeOwner> owners = new HashMap<>();
    private final Context context;
    private final String identity;
    private final ExecutorService queue = Executors.newSingleThreadExecutor();
    private final AtomicInteger queued = new AtomicInteger();
    final LocalStateStore state;
    private volatile ComputeHost host;
    private long generation;
    private volatile boolean closed;

    static LocalComputeOwner get(Context context) throws Exception {
        return get(context, context.getDatabasePath(LocalStateStore.DATABASE));
    }

    static synchronized LocalComputeOwner get(Context context, File file) throws Exception {
        String identity = file.getCanonicalPath();
        LocalComputeOwner owner = owners.get(identity);
        if (owner == null || owner.closed) {
            owner = new LocalComputeOwner(context, file, identity); owners.put(identity, owner);
        }
        return owner;
    }

    private LocalComputeOwner(Context context, File file, String identity) {
        this.context = context.getApplicationContext(); this.identity = identity;
        File parent = file.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) throw new IllegalStateException("STATE_UNAVAILABLE");
        state = new LocalStateStore(SQLiteDatabase.openOrCreateDatabase(file, null));
    }

    interface Operation<T> { T run() throws Exception; }

    private <T> CompletableFuture<T> submit(Operation<T> operation) {
        CompletableFuture<T> result = new CompletableFuture<>();
        if (closed) {
            result.completeExceptionally(new IllegalStateException("COMPUTE_QUEUE_UNAVAILABLE")); return result;
        }
        if (queued.incrementAndGet() > 64) {
            queued.decrementAndGet(); result.completeExceptionally(new IllegalStateException("COMPUTE_QUEUE_UNAVAILABLE"));
            return result;
        }
        try { queue.execute(() -> {
            try {
                if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("COMPUTE_ON_MAIN_THREAD");
                result.complete(operation.run());
            } catch (Exception ignored) {
                // Never propagate account payloads, Python traces or provider URLs.
                result.completeExceptionally(new IllegalStateException("COMPUTE_OPERATION_FAILED"));
            } finally { queued.decrementAndGet(); }
        }); } catch (java.util.concurrent.RejectedExecutionException ignored) {
            queued.decrementAndGet(); result.completeExceptionally(new IllegalStateException("COMPUTE_QUEUE_UNAVAILABLE"));
        }
        return result;
    }

    private void dropHost() { if (host != null) { host.close(); host = null; } }

    private String initializeCandidate(ComputeHost candidate, String payload) throws Exception {
        candidate.start();
        JSONObject reply = candidate.request(new JSONObject().put("command", "initialize").put("state", payload));
        if (reply.isNull("state") || !(reply.get("state") instanceof String)) throw new IllegalStateException("STATE_VALIDATION_FAILED");
        return reply.getString("state");
    }

    private void initializeIfNeeded() throws Exception {
        if (host != null && state.currentGeneration() != generation) dropHost();
        if (host != null) return;
        JSObject saved = state.read(); generation = saved.getLong("generation");
        ComputeHost candidate = new ComputeHost(context);
        try {
            String migrated = initializeCandidate(candidate, saved.getString("payload"));
            generation = state.write(generation, migrated); host = candidate;
        } catch (Exception error) { candidate.close(); throw error; }
    }

    static void validateRequest(String method, String path, String body) {
        if (!("GET".equals(method) || "POST".equals(method)) || path == null || path.length() > 4096
            || !path.startsWith("/api/v1/") || path.contains("\\") || path.contains("#")
            || path.chars().anyMatch(c -> c < 32 || c == 127)
            || body == null || body.length() > LocalStateStore.MAX_CHARACTERS) throw new IllegalArgumentException();
    }

    CompletableFuture<JSObject> request(String method, String path, String body) {
        try { validateRequest(method, path, body); }
        catch (Exception error) {
            CompletableFuture<JSObject> rejected = new CompletableFuture<>();
            rejected.completeExceptionally(new IllegalArgumentException("INVALID_LOCAL_REQUEST")); return rejected;
        }
        return submit(() -> {
            try {
                initializeIfNeeded();
                JSONObject reply = host.request(new JSONObject().put("command", "request")
                    .put("method", method).put("path", path).put("body", body));
                JSONObject result = reply.getJSONObject("result");
                int status = result.getInt("status");
                if (status < 100 || status > 599 || !result.has("body")) throw new IllegalStateException("INVALID_COMPUTE_REPLY");
                if ("POST".equals(method)) {
                    if (reply.isNull("state")) throw new IllegalStateException("COMPUTE_COMMIT_MISSING");
                    generation = state.write(generation, reply.getString("state"));
                } else if (!reply.isNull("state") || state.currentGeneration() != generation)
                    throw new IllegalStateException("UNEXPECTED_READ_COMMIT_OR_STATE_CHANGE");
                return new JSObject(result.toString());
            } catch (Exception error) { dropHost(); throw error; }
        });
    }

    CompletableFuture<JSObject> readState() { return submit(() -> state.read()); }

    CompletableFuture<JSObject> restore(String payload, Long expectedGeneration) {
        return submit(() -> {
            if (payload == null || payload.length() > LocalStateStore.MAX_CHARACTERS) throw new IllegalArgumentException();
            long previous = state.read().getLong("generation");
            if (expectedGeneration != null && expectedGeneration != previous) throw new IllegalStateException("STATE_CONFLICT");
            // Keep only one WASM heap resident. Failed validation leaves the
            // durable original untouched and the next request reloads it.
            dropHost();
            ComputeHost candidate = new ComputeHost(context);
            try {
                String verified = initializeCandidate(candidate, payload);
                long saved = state.write(previous, verified);
                dropHost(); host = candidate; generation = saved;
                return new JSObject().put("generation", saved);
            } catch (Exception error) {
                candidate.close();
                try { if (state.currentGeneration() != previous) dropHost(); }
                catch (Exception ignored) { dropHost(); }
                throw error;
            }
        });
    }

    // Test-only lifecycle exercise uses an isolated DB; application consumers
    // never destroy the owner when an Activity disappears.
    CompletableFuture<Void> closeForTest() {
        if (closed) return CompletableFuture.completedFuture(null);
        if (!context.getPackageName().endsWith(".debug")) {
            CompletableFuture<Void> rejected = new CompletableFuture<>();
            rejected.completeExceptionally(new SecurityException()); return rejected;
        }
        ComputeHost active = host;
        if (active != null) active.close();
        return submit(() -> {
            dropHost(); state.database.close(); closed = true;
            synchronized (LocalComputeOwner.class) { owners.remove(identity, this); }
            queue.shutdown(); return null;
        });
    }
}
