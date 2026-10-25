package jp.stockai.app;

import android.annotation.SuppressLint;
import android.content.Context;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.ServiceWorkerClient;
import android.webkit.ServiceWorkerController;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Collections;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** Activity-independent host with APK resources and request-fenced checkpoint reads. */
final class ComputeHost {
    static final String ORIGIN = "https://compute.stockai.local";
    static final long TIMEOUT_SECONDS = 600;
    private final Context context;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final CompletableFuture<Void> ready = new CompletableFuture<>();
    private volatile CompletableFuture<JSONObject> pending;
    private final Object transferLock = new Object();
    private LocalStateStore.ReadLease incoming;
    private LocalStateStore.PendingWrite outgoing;
    private long expectedGeneration;
    private boolean stateExpected;
    private boolean optimizedStartup;
    private boolean deferredStartup;
    private String transferPhase = "idle";
    private volatile long requestId;
    private volatile boolean closed;
    private volatile boolean assetUnavailable;
    private final java.util.concurrent.atomic.AtomicInteger interpreterAssets = new java.util.concurrent.atomic.AtomicInteger();
    private WebView view;
    AnalysisCheckpoints checkpoints;
    String checkpointInput;
    private StringBuilder checkpointOutput;
    private int checkpointLength;

    ComputeHost(Context context) { this.context = context.getApplicationContext(); }

    private static WebResourceResponse denied() {
        return new WebResourceResponse("text/plain", "UTF-8", 403, "Forbidden", Collections.emptyMap(), new ByteArrayInputStream(new byte[0]));
    }

    static boolean localAsset(Uri uri) {
        return "https".equals(uri.getScheme()) && "compute.stockai.local".equals(uri.getHost())
            && (uri.getPort() == -1 || uri.getPort() == 443) && uri.getUserInfo() == null;
    }

    WebResourceResponse asset(Uri uri) {
        if (!localAsset(uri)) return denied();
        String path = uri.getPath();
        if (path == null || !path.startsWith("/") || path.contains("\\") || path.contains("\u0000")) return denied();
        for (String part : path.split("/", -1)) if (part.equals(".") || part.equals("..")) return denied();
        if (path.startsWith("/analysis-checkpoint/")) {
            synchronized (transferLock) {
                String[] parts = path.split("/");
                if (parts.length != 4 || uri.getQuery() != null || closed || pending == null || pending.isDone()
                        || !Long.toString(requestId).equals(parts[2]) || checkpoints == null) return denied();
                try {
                    byte[] value = checkpoints.read(parts[3]).getBytes(java.nio.charset.StandardCharsets.US_ASCII);
                    return new WebResourceResponse("text/plain", "UTF-8", 200, "OK",
                        Map.of("Cache-Control", "no-store", "X-Content-Type-Options", "nosniff"), new ByteArrayInputStream(value));
                } catch (Exception ignored) { return denied(); }
            }
        }
        int bit = path.equals("/python/pyodide.mjs") ? 1 : path.equals("/python/pyodide.asm.js") ? 2
            : path.equals("/python/pyodide.asm.wasm") ? 4 : path.equals("/python/pyodide-lock.json") ? 8 : 0;
        interpreterAssets.getAndUpdate(value -> value | bit);
        try {
            InputStream content = context.getAssets().open("public" + path);
            String extension = path.substring(path.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
            String mime = switch (extension) {
                case "html" -> "text/html";
                case "js", "mjs" -> "text/javascript";
                case "json" -> "application/json";
                case "wasm" -> "application/wasm";
                default -> "application/octet-stream";
            };
            Map<String, String> headers = new HashMap<>();
            headers.put("Content-Security-Policy", "default-src 'none'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; worker-src 'self' blob:; connect-src 'self'; frame-src 'none'; base-uri 'none'; form-action 'none'");
            headers.put("Cache-Control", "no-store"); headers.put("X-Content-Type-Options", "nosniff");
            String encoding = mime.startsWith("text/") || mime.equals("application/json") ? "UTF-8" : null;
            return new WebResourceResponse(mime, encoding, 200, "OK", headers, content);
        } catch (Exception ignored) { assetUnavailable = true; return denied(); }
    }

    @SuppressLint("SetJavaScriptEnabled") // Trusted APK-only page; no arbitrary navigation or network.
    void start() throws Exception {
        main.post(() -> {
            if (closed) return;
            try {
                view = new WebView(context);
                view.getSettings().setJavaScriptEnabled(true);
                view.getSettings().setAllowFileAccess(false); view.getSettings().setAllowContentAccess(false);
                view.getSettings().setBlockNetworkLoads(true);
                view.getSettings().setMixedContentMode(android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW);
                // Worker imports/fetches may use the application-wide worker
                // loader rather than this WebViewClient (also used by Capacitor).
                ServiceWorkerController workers = ServiceWorkerController.getInstance();
                workers.getServiceWorkerWebSettings().setAllowFileAccess(false);
                workers.getServiceWorkerWebSettings().setAllowContentAccess(false);
                workers.getServiceWorkerWebSettings().setBlockNetworkLoads(true);
                workers.setServiceWorkerClient(new ServiceWorkerClient() {
                    @Override public WebResourceResponse shouldInterceptRequest(WebResourceRequest request) { return asset(request.getUrl()); }
                });
                view.addJavascriptInterface(new Bridge(), "StockAICompute");
                view.setWebViewClient(new WebViewClient() {
                    @Override public WebResourceResponse shouldInterceptRequest(WebView source, WebResourceRequest request) { return asset(request.getUrl()); }
                    @Override public boolean shouldOverrideUrlLoading(WebView source, WebResourceRequest request) { return true; }
                    @Override public void onReceivedError(WebView source, WebResourceRequest request, WebResourceError error) {
                        if (request.isForMainFrame()) ready.completeExceptionally(new IllegalStateException("COMPUTE_HOST_UNAVAILABLE"));
                    }
                    @Override public boolean onRenderProcessGone(WebView source, android.webkit.RenderProcessGoneDetail detail) {
                        synchronized (transferLock) {
                            IllegalStateException failure = new IllegalStateException(
                                "COMPUTE_RENDERER_" + (detail.didCrash() ? "CRASHED" : "KILLED") + "_STAGE_" + transferPhase);
                            ready.completeExceptionally(failure);
                            if (pending != null) pending.completeExceptionally(failure);
                        }
                        ComputeHost.this.close(); return true;
                    }
                });
                view.loadUrl(ORIGIN + "/compute.html");
            } catch (Exception ignored) { ready.completeExceptionally(new IllegalStateException("COMPUTE_HOST_UNAVAILABLE")); }
        });
        ready.get(120, TimeUnit.SECONDS);
    }

    static final class Reply implements AutoCloseable {
        final JSONObject json;
        final LocalStateStore.PendingWrite state;
        Reply(JSONObject json, LocalStateStore.PendingWrite state) { this.json = json; this.state = state; }
        @Override public void close() { if (state != null) state.close(); }
    }

    Reply request(JSONObject command, LocalStateStore.ReadLease source, long generation) throws Exception {
        if (closed) throw new IllegalStateException("COMPUTE_HOST_CLOSED");
        boolean initialization = command.optString("command").matches("initialize|initialize_operations");
        if (command.has("state") || (initialization != (source != null)))
            throw new IllegalArgumentException("STATE_TRANSFER_REQUIRED");
        long identity;
        CompletableFuture<JSONObject> response = new CompletableFuture<>();
        synchronized (transferLock) {
            if (closed || pending != null) throw new IllegalStateException("COMPUTE_HOST_BUSY_OR_CLOSED");
            identity = ++requestId;
            pending = response; incoming = source; expectedGeneration = generation;
            transferPhase = "dispatch";
            stateExpected = source != null || "POST".equals(command.optString("method"));
            optimizedStartup = initialization && command.optBoolean("optimized_startup");
            deferredStartup = optimizedStartup && command.optBoolean("defer_initialize");
        }
        try {
            command.put("id", identity);
            if (checkpointInput != null) command.put("checkpoint_length", checkpointInput.length());
            if (source != null) command.put("state_length", source.length);
            String script = "window.stockAICompute(" + command + ")";
            main.post(() -> {
                if (!closed && view != null) view.evaluateJavascript(script, null);
                else response.completeExceptionally(new IllegalStateException("COMPUTE_HOST_CLOSED"));
            });
            long timeout = source != null ? 120 : TIMEOUT_SECONDS;
            JSONObject value = response.get(timeout, TimeUnit.SECONDS);
            synchronized (transferLock) {
                if (closed || pending != response) throw new IllegalStateException("COMPUTE_HOST_CLOSED");
                Reply reply = new Reply(value, outgoing); outgoing = null; return reply;
            }
        } finally {
            synchronized (transferLock) {
                if (pending == response) {
                    pending = null;
                    if (incoming != null) incoming.close(); incoming = null;
                    if (outgoing != null) outgoing.close(); outgoing = null;
                    checkpointInput = null; checkpointOutput = null;
                }
            }
        }
    }

    void close() {
        closed = true;
        ready.completeExceptionally(new IllegalStateException("COMPUTE_HOST_CLOSED"));
        synchronized (transferLock) {
            CompletableFuture<JSONObject> response = pending;
            if (response != null) response.completeExceptionally(new IllegalStateException("COMPUTE_HOST_CLOSED"));
            if (incoming != null) incoming.close(); incoming = null;
            if (outgoing != null) outgoing.close(); outgoing = null;
            checkpointInput = null; checkpointOutput = null;
        }
        main.post(() -> { if (view != null) { view.removeJavascriptInterface("StockAICompute"); view.destroy(); view = null; } });
    }

    final class Bridge {
        @JavascriptInterface public String checkpointChunk(String identity, int offset) {
            synchronized (transferLock) {
                if (!active(identity) || checkpointInput == null || offset < 0 || offset >= checkpointInput.length()) return null;
                return checkpointInput.substring(offset, Math.min(checkpointInput.length(), offset + AnalysisCheckpoints.CHUNK));
            }
        }
        @JavascriptInterface public boolean beginCheckpoint(String identity, int length) {
            synchronized (transferLock) {
                if (!active(identity) || checkpoints == null || checkpointOutput != null || length < 1 || length > AnalysisCheckpoints.LIMIT + 4096) return false;
                checkpointLength = length; checkpointOutput = new StringBuilder(); return true;
            }
        }
        @JavascriptInterface public boolean appendCheckpoint(String identity, int offset, String value) {
            synchronized (transferLock) {
                if (!active(identity) || checkpointOutput == null || value == null || offset != checkpointOutput.length()
                        || value.length() > AnalysisCheckpoints.CHUNK || value.length() == 0
                        || offset + value.length() > checkpointLength) return false;
                checkpointOutput.append(value); return true;
            }
        }
        @JavascriptInterface public boolean commitCheckpoint(String identity) {
            synchronized (transferLock) {
                if (!active(identity) || checkpoints == null || checkpointOutput == null || checkpointOutput.length() != checkpointLength) return false;
                try { checkpoints.write(new JSONObject(checkpointOutput.toString())); checkpointOutput = null; return true; }
                catch (Exception error) { checkpointOutput = null; transferFailed(error); return false; }
            }
        }
        private boolean active(String identity) {
            return !closed && pending != null && !pending.isDone() && Long.toString(requestId).equals(identity);
        }
        private void transferFailed(Exception error) {
            if (pending != null) pending.completeExceptionally(new IllegalStateException("COMPUTE_STATE_TRANSFER_FAILED", error));
        }
        @JavascriptInterface public void ready() { if (!closed) ready.complete(null); }
        @JavascriptInterface public void progress(String identity, String phase) {
            synchronized (transferLock) {
                if (!active(identity) || phase == null
                        || !phase.matches("reading-input|posting-input|decoding-input|interpreter|packages|archive|state|request|export|export-archive|export-chunks|staging-output")) return;
                transferPhase = phase;
                if (checkpoints != null && phase.matches("export|export-archive|export-chunks|staging-output")) {
                    try { checkpoints.phase("saving"); }
                    catch (Exception error) { transferFailed(error); return; }
                }
                // Allowlisted stage only: no request bodies, provider URLs,
                // credentials, holdings, or exception messages in release logs.
                android.util.Log.i("StockAIComputeTiming", "request=" + requestId + " phase=" + phase);
                if ((context.getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
                    android.app.ActivityManager.MemoryInfo memory = new android.app.ActivityManager.MemoryInfo();
                    ((android.app.ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE)).getMemoryInfo(memory);
                    Runtime runtime = Runtime.getRuntime();
                    android.util.Log.i("StockAIComputeStage", "phase=" + phase + " java_used="
                        + (runtime.totalMemory() - runtime.freeMemory()) + " available=" + memory.availMem
                        + " low_memory=" + memory.lowMemory);
                }
            }
        }
        @JavascriptInterface public String inputChunk(String identity, double index) {
            synchronized (transferLock) {
                if (!active(identity)) return null;
                try {
                    if (incoming == null || !Double.isFinite(index) || index != (int) index) throw new SecurityException();
                    return incoming.next((int) index);
                } catch (Exception error) { transferFailed(error); return null; }
            }
        }
        @JavascriptInterface public boolean inputDone(String identity) {
            synchronized (transferLock) {
                if (!active(identity)) return false;
                try {
                    if (incoming == null) throw new SecurityException();
                    incoming.finish(); return true;
                } catch (Exception error) { transferFailed(error); return false; }
            }
        }
        @JavascriptInterface public boolean beginState(String identity, double length) {
            synchronized (transferLock) {
                if (!active(identity)) return false;
                try {
                    if (!stateExpected || outgoing != null || (incoming != null && !incoming.finished())
                            || !Double.isFinite(length) || length < 0 || length > LocalStateStore.MAX_CHARACTERS
                            || length != (int) length) throw new SecurityException();
                    outgoing = new LocalStateStore.PendingWrite(context.getCacheDir(), expectedGeneration, (int) length);
                    return true;
                } catch (Exception error) { transferFailed(error); return false; }
            }
        }
        @JavascriptInterface public boolean stateChunk(String identity, double index, String fragment) {
            synchronized (transferLock) {
                if (!active(identity)) return false;
                try {
                    if (outgoing == null || !Double.isFinite(index) || index != (int) index) throw new SecurityException();
                    outgoing.append((int) index, fragment); return true;
                } catch (Exception error) { transferFailed(error); return false; }
            }
        }
        @JavascriptInterface public void complete(String identity, String payload) {
            synchronized (transferLock) {
            CompletableFuture<JSONObject> response = pending;
            try {
                if (!active(identity)) return;
                if (payload.length() > LocalStateStore.MAX_INLINE_CHARACTERS + 4 * 1024 * 1024) throw new IllegalArgumentException();
                JSONObject value = new JSONObject(payload);
                if (value.has("error")) {
                    String code = value.optString("code");
                    if (!code.matches("(interpreter|packages|archive|state|request)_(wasm|type|python|other)|worker_js|checkpoint_pause")) code = "unknown";
                    response.completeExceptionally(new IllegalStateException("COMPUTE_" + code + "_ASSETMASK_" + interpreterAssets.get() + (assetUnavailable ? "_APK_ASSET_UNAVAILABLE" : "")));
                    return;
                }
                if (value.getLong("id") != requestId || (incoming != null && !incoming.finished())) throw new SecurityException();
                if (optimizedStartup) {
                    String mode = value.getJSONObject("result").getString("persistence");
                    if (deferredStartup ? !mode.equals("deferred") : !mode.matches("none|operations|full"))
                        throw new SecurityException();
                    boolean saves = mode.equals("operations") || mode.equals("full");
                    if (saves) {
                        if (!Boolean.TRUE.equals(value.opt("state")) || outgoing == null) throw new SecurityException();
                        outgoing.seal();
                    } else if (!value.has("state") || !value.isNull("state") || outgoing != null) throw new SecurityException();
                } else if (stateExpected) {
                    if (!Boolean.TRUE.equals(value.opt("state")) || outgoing == null) throw new SecurityException();
                    outgoing.seal();
                } else if (!value.has("state") || !value.isNull("state") || outgoing != null) throw new SecurityException();
                response.complete(value);
            } catch (Exception ignored) {
                if (response != null) response.completeExceptionally(new IllegalStateException("COMPUTE_FAILED"));
            }
            }
        }
    }
}
