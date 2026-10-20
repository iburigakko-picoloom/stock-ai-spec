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
import java.util.concurrent.FutureTask;
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
    private LocalStateStore.PendingWrite pendingBackup;
    private String backupToken;
    private long backupGeneration;

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
        // Cancelling a caller must also remove its work or interrupt its own
        // interpreter wait. A stopped Worker must not leave an orphan ahead
        // of its replacement. Count queued/running work exactly once.
        AtomicInteger phase = new AtomicInteger(); // queued=0, running=1, released=2
        FutureTask<Void> task = new FutureTask<>(() -> {
            if (!phase.compareAndSet(0, 1)) return null;
            try {
                if (!result.isCancelled()) {
                    if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("COMPUTE_ON_MAIN_THREAD");
                    result.complete(operation.run());
                }
            } catch (Exception error) {
                // The plugin always exposes a fixed error. Internal causes aid
                // isolated native tests; worker diagnostics contain only enums.
                result.completeExceptionally(new IllegalStateException("COMPUTE_OPERATION_FAILED", error));
            } finally { phase.set(2); queued.decrementAndGet(); }
            return null;
        });
        result.whenComplete((value, error) -> {
            if (result.isCancelled()) {
                task.cancel(true);
                if (phase.compareAndSet(0, 2)) queued.decrementAndGet();
            }
        });
        try { queue.execute(task); } catch (java.util.concurrent.RejectedExecutionException ignored) {
            if (phase.compareAndSet(0, 2)) queued.decrementAndGet();
            result.completeExceptionally(new IllegalStateException("COMPUTE_QUEUE_UNAVAILABLE"));
        }
        return result;
    }

    private void dropHost() { if (host != null) { host.close(); host = null; } }

    private long initializeCandidate(ComputeHost candidate, LocalStateStore.ReadLease source,
            long previous) throws Exception {
        candidate.start();
        try (ComputeHost.Reply reply = candidate.request(new JSONObject().put("command", "initialize"), source, previous)) {
            if (reply.state == null || !Boolean.TRUE.equals(reply.json.opt("state"))) throw new IllegalStateException("STATE_VALIDATION_FAILED");
            return state.commitTransfer(previous, reply.state);
        }
    }

    private void initializeIfNeeded() throws Exception {
        if (host != null && state.currentGeneration() != generation) dropHost();
        if (host != null) return;
        try (LocalStateStore.ReadLease saved = state.openReadLease()) {
            generation = saved.generation;
            ComputeHost candidate = new ComputeHost(context);
            try {
                generation = initializeCandidate(candidate, saved, generation); host = candidate;
            } catch (Exception error) { candidate.close(); throw error; }
        }
    }

    static void validateRequest(String method, String path, String body) {
        if (!("GET".equals(method) || "POST".equals(method)) || path == null || path.length() > 4096
            || !path.startsWith("/api/v1/") || path.contains("\\") || path.contains("#")
            || path.chars().anyMatch(c -> c < 32 || c == 127)
            || body == null || body.length() > LocalStateStore.MAX_INLINE_CHARACTERS) throw new IllegalArgumentException();
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
                try (ComputeHost.Reply reply = host.request(new JSONObject().put("command", "request")
                        .put("method", method).put("path", path).put("body", body), null, generation)) {
                    JSONObject result = reply.json.getJSONObject("result");
                    int status = result.getInt("status");
                    if (status < 100 || status > 599 || !result.has("body")) throw new IllegalStateException("INVALID_COMPUTE_REPLY");
                    if ("POST".equals(method)) {
                        if (reply.state == null || !Boolean.TRUE.equals(reply.json.opt("state"))) throw new IllegalStateException("COMPUTE_COMMIT_MISSING");
                        generation = state.commitTransfer(generation, reply.state);
                    } else if (reply.state != null || !reply.json.isNull("state") || state.currentGeneration() != generation)
                        throw new IllegalStateException("UNEXPECTED_READ_COMMIT_OR_STATE_CHANGE");
                    return new JSObject(result.toString());
                }
            } catch (Exception error) { dropHost(); throw error; }
        });
    }

    CompletableFuture<JSObject> readState() { return submit(() -> state.read()); }

    interface Input { java.io.InputStream open() throws Exception; }
    interface Output { java.io.OutputStream open() throws Exception; }

    CompletableFuture<JSObject> exportBackup(String password, Output destination) {
        return submit(() -> {
            try (LocalStateStore.ReadLease saved = state.openReadLease();
                    java.io.OutputStream output = destination.open()) {
                if (output == null) throw new java.io.IOException();
                try (PortableBackup.Writer writer = new PortableBackup.Writer(password,
                        saved.generation, saved.length, output)) {
                    for (int index = 0; index < saved.chunks; index++) writer.append(saved.next(index));
                    saved.finish(); writer.finish();
                }
            }
            return new JSObject();
        });
    }

    private void clearBackupPreview() {
        if (pendingBackup != null) pendingBackup.close();
        pendingBackup = null; backupToken = null;
    }

    CompletableFuture<JSObject> previewBackup(String password, Input source) {
        return submit(() -> {
            clearBackupPreview();
            long previous = state.currentGeneration();
            LocalStateStore.PendingWrite staged = new LocalStateStore.PendingWrite(context.getCacheDir(), previous);
            try (java.io.InputStream input = source.open()) {
                if (input == null) throw new java.io.IOException();
                PortableBackup.Metadata metadata = PortableBackup.read(password, input, staged::append);
                staged.seal();
                if (staged.length != metadata.characters || state.currentGeneration() != previous)
                    throw new IllegalStateException("STATE_CONFLICT");
                pendingBackup = staged; backupGeneration = previous;
                backupToken = java.util.UUID.randomUUID().toString();
                return new JSObject().put("token", backupToken).put("characters", staged.length);
            } catch (Exception error) {
                if (pendingBackup == staged) clearBackupPreview(); else staged.close();
                throw error;
            }
        });
    }

    CompletableFuture<JSObject> discardBackup(String token) {
        return submit(() -> {
            if (backupToken != null && backupToken.equals(token)) clearBackupPreview();
            return new JSObject();
        });
    }

    private long authenticatedGeneration() throws Exception {
        try (LocalStateStore.ReadLease saved = state.openReadLease()) {
            for (int index = 0; index < saved.chunks; index++) saved.next(index);
            saved.finish(); return saved.generation;
        }
    }

    private JSObject restoreFrom(LocalStateStore.ReadLease source, long previous) throws Exception {
        ComputeHost candidate = null;
        try (LocalStateStore.ReadLease incoming = source) {
            dropHost(); candidate = new ComputeHost(context);
            long saved = initializeCandidate(candidate, incoming, previous);
            host = candidate; generation = saved;
            return new JSObject().put("generation", saved);
        } catch (Exception error) {
            if (candidate != null) candidate.close();
            try { if (state.currentGeneration() != previous) dropHost(); }
            catch (Exception ignored) { dropHost(); }
            throw error;
        }
    }

    CompletableFuture<JSObject> restoreBackup(String token) {
        return submit(() -> {
            if (backupToken == null || !backupToken.equals(token)) throw new SecurityException("BACKUP_PREVIEW_REQUIRED");
            LocalStateStore.PendingWrite staged = pendingBackup;
            long previous = backupGeneration;
            pendingBackup = null; backupToken = null;
            try (LocalStateStore.PendingWrite owned = staged) {
                if (state.currentGeneration() != previous || authenticatedGeneration() != previous)
                    throw new IllegalStateException("STATE_CONFLICT");
                new DailyAutomation(context, state.database).stop();
                return restoreFrom(state.stagedLease(owned, previous), previous);
            }
        });
    }

    CompletableFuture<JSObject> restore(String payload, Long expectedGeneration) {
        java.util.concurrent.atomic.AtomicReference<String> incoming = new java.util.concurrent.atomic.AtomicReference<>(payload);
        return submit(() -> {
            if (incoming.get() == null || incoming.get().length() > LocalStateStore.MAX_INLINE_CHARACTERS)
                throw new IllegalArgumentException();
            // Preserve old-state authentication without assembling its full String.
            long previous = authenticatedGeneration();
            if (expectedGeneration != null && expectedGeneration != previous) throw new IllegalStateException("STATE_CONFLICT");
            // Keep only one WASM heap resident. Failed validation leaves the
            // durable original untouched and the next request reloads it.
            clearBackupPreview();
            return restoreFrom(state.stringLease(incoming.getAndSet(null), previous), previous);
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
            dropHost(); clearBackupPreview(); state.database.close(); closed = true;
            synchronized (LocalComputeOwner.class) { owners.remove(identity, this); }
            queue.shutdown(); return null;
        });
    }
}
