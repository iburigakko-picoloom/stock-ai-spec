package jp.stockai.app;

import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.database.sqlite.SQLiteDatabase;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.util.Base64;
import androidx.core.content.FileProvider;
import androidx.activity.result.ActivityResult;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.PermissionState;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.ActivityCallback;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.*;

@CapacitorPlugin(name = "StockAI", permissions = {@Permission(alias = "dailyNotifications", strings = {android.Manifest.permission.POST_NOTIFICATIONS})})
public class StockAIPlugin extends Plugin {
    static final String REPO = "iburigakko-picoloom/stock-ai-spec";
    final ExecutorService executor = Executors.newSingleThreadExecutor();
    final ExecutorService networkExecutor = Executors.newSingleThreadExecutor();
    final ExecutorService displayExecutor = Executors.newSingleThreadExecutor();
    SQLiteDatabase db;
    volatile JSONObject pendingUpdate;
    static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder();
        for (byte value : bytes) result.append(String.format("%02x", value & 255));
        return result.toString();
    }

    LocalComputeOwner owner() throws Exception { return LocalComputeOwner.get(getContext()); }
    LocalStateStore stateStore() { return new LocalStateStore(db); }
    JSObject readStateData() throws Exception { return stateStore().read(); }
    long writeStateData(long generation, String payload) throws Exception { return stateStore().write(generation, payload); }
    void initializeStateTables() { stateStore(); }

    @Override public void load() {
        try { db = owner().state.database; }
        catch (Exception ignored) { throw new IllegalStateException("LOCAL_STATE_UNAVAILABLE"); }
    }

    interface Work { void run() throws Exception; }
    void background(PluginCall call, Work work) {
        executor.execute(() -> { try { work.run(); } catch (Exception ignored) {
            // Exceptions can contain provider URLs, credentials or account data.
            call.reject("端末の処理に失敗しました。通信・権限・保存領域を確認してください。", "STOCKAI_OPERATION_FAILED");
        }});
    }

    void network(PluginCall call, Work work) {
        networkExecutor.execute(() -> { try { work.run(); } catch (Exception ignored) {
            call.reject("通信を完了できませんでした。現在のアプリと保存データを使用できます。", "STOCKAI_NETWORK_FAILED");
        }});
    }

    byte[] encrypt(String text) throws Exception { return LocalStateStore.encrypt(text); }
    String decrypt(byte[] data) throws Exception { return LocalStateStore.decrypt(data); }

    void completeLocal(PluginCall call, java.util.concurrent.CompletableFuture<JSObject> result) {
        result.whenComplete((value, error) -> {
            if (error != null) call.reject("端末の計算・保存を完了できませんでした。保存済みの状態から再試行してください。", "STOCKAI_COMPUTE_FAILED");
            else call.resolve(value);
        });
    }

    void completeBackup(PluginCall call, java.util.concurrent.CompletableFuture<JSObject> result) {
        result.whenComplete((value, error) -> {
            if (error != null) call.reject("バックアップを確認できませんでした。パスワード・ファイル・保存領域を確認してください。", "STOCKAI_BACKUP_FAILED");
            else call.resolve(value);
        });
    }

    @PluginMethod public void compute(PluginCall call) {
        String personalPath = call.getString("path");
        if (ManualAnalysisService.handles(call.getString("method"), personalPath)) {
            completeLocal(call, ManualAnalysisService.start(getContext(), call.getString("body", "{}")));
            return;
        }
        if ("GET".equals(call.getString("method")) && ("/api/v1/mobile/portfolio".equals(personalPath)
                || "/api/v1/mobile/personal/current".equals(personalPath) || NativeRecordViews.handles(personalPath))) {
            displayExecutor.execute(() -> {
                try {
                    JSObject result = NativeRecordViews.handles(personalPath)
                        ? NativePortfolioReader.readRecords(getContext(), owner().state, personalPath)
                        : NativePortfolioReader.read(getContext(), owner().state, personalPath.endsWith("/current"));
                    if (result != null) { call.resolve(result); return; }
                    background(call, () -> completeLocal(call, owner().request("GET", personalPath, "null")));
                } catch (Exception error) { call.reject("保存情報を確認できませんでした。再確認してください。", "PERSONAL_READ_FAILED"); }
            });
            return;
        }
        background(call, () -> {
        completeLocal(call, owner().request(call.getString("method"), call.getString("path"), call.getString("body", "null")));
    }); }
    @PluginMethod public void readSavedView(PluginCall call) { displayExecutor.execute(() -> {
        try { call.resolve(SavedReadViews.forDatabase(
            getContext().getDatabasePath(LocalStateStore.DATABASE)).read(call.getString("path"))); }
        catch (Exception ignored) { call.reject("保存済み表示を確認できません。", "SAVED_VIEW_INVALID"); }
    }); }
    @PluginMethod public void readState(PluginCall call) { background(call, () -> {
        completeLocal(call, owner().readState());
    }); }
    @PluginMethod public void restoreState(PluginCall call) { background(call, () -> {
        owner().readViews.clear();
        automation().stop();
        completeLocal(call, owner().restore(call.getString("payload"), null));
    }); }
    @PluginMethod public void writeState(PluginCall call) { background(call, () -> {
        owner().readViews.clear();
        Object raw = call.getData().opt("generation");
        if (!(raw instanceof Number)) throw new IllegalArgumentException();
        double value = ((Number) raw).doubleValue();
        if (!Double.isFinite(value) || value < 0 || value > LocalStateStore.MAX_GENERATION || value != Math.rint(value)) throw new IllegalArgumentException();
        automation().stop();
        completeLocal(call, owner().restore(call.getString("payload"), (long) value));
    }); }

    DailyAutomation automation() throws Exception { return new DailyAutomation(getContext(), owner().state.database); }
    @PluginMethod public void dailyStatus(PluginCall call) { background(call, () -> call.resolve(new JSObject(automation().status().toString()))); }
    @PluginMethod public void analysisStatus(PluginCall call) { displayExecutor.execute(() -> {
        try {
            LocalComputeOwner current = owner();
            call.resolve(current.checkpoints.status(current.analyzing || ManualAnalysisService.isRunning()));
        } catch (Exception error) { call.reject("途中保存の状態を確認できません。", "CHECKPOINT_READ_FAILED"); }
    }); }
    @PluginMethod public void startDaily(PluginCall call) { background(call, () -> {
        if (apiKey() == null) { call.reject("設定でJ-Quants APIキーを保存してから開始してください。", "API_KEY_REQUIRED"); return; }
        automation().start(); call.resolve(new JSObject(automation().status().toString()));
    }); }
    @PluginMethod public void stopDaily(PluginCall call) { background(call, () -> {
        automation().stop(); call.resolve(new JSObject(automation().status().toString()));
    }); }
    @PluginMethod public void requestDailyNotifications(PluginCall call) {
        if (Build.VERSION.SDK_INT < 33 || getPermissionState("dailyNotifications") == PermissionState.GRANTED) {
            dailyNotificationPermission(call); return;
        }
        requestPermissionForAlias("dailyNotifications", call, "dailyNotificationPermission");
    }
    @PermissionCallback private void dailyNotificationPermission(PluginCall call) {
        call.resolve(new JSObject().put("granted", androidx.core.app.NotificationManagerCompat.from(getContext()).areNotificationsEnabled()));
    }

    String apiKey() throws Exception {
        return MarketClient.apiKey(getContext());
    }
    @PluginMethod public void keyStatus(PluginCall call) { background(call, () -> call.resolve(new JSObject().put("configured", apiKey() != null))); }
    @PluginMethod public void saveApiKey(PluginCall call) { background(call, () -> {
        String value = call.getString("apiKey");
        if (value == null || value.trim().length() < 8 || value.length() > 4096 || value.contains("\n") || value.contains("\r")) throw new IllegalArgumentException();
        if (!getContext().getSharedPreferences("stockai-secrets", 0).edit().putString("jquants", Base64.encodeToString(encrypt(value.trim()), Base64.NO_WRAP)).commit()) throw new IOException();
        call.resolve();
    }); }
    @PluginMethod public void clearApiKey(PluginCall call) { background(call, () -> {
        automation().stop();
        if (!getContext().getSharedPreferences("stockai-secrets", 0).edit().remove("jquants").commit()) throw new IOException();
        call.resolve();
    }); }

    @PluginMethod public void exportBackup(PluginCall call) {
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/octet-stream").addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE, "StockAI-backup.stockaib");
        startActivityForResult(call, intent, "backupCreated");
    }
    @ActivityCallback private void backupCreated(PluginCall call, ActivityResult result) {
        if (call == null) return;
        if (result.getResultCode() != android.app.Activity.RESULT_OK || result.getData() == null || result.getData().getData() == null) { call.reject("バックアップ保存を取り消しました。"); return; }
        Uri uri = result.getData().getData();
        background(call, () -> {
            completeBackup(call, owner().exportBackup(call.getString("password"),
                () -> getContext().getContentResolver().openOutputStream(uri, "wt")));
        });
    }
    @PluginMethod public void importBackup(PluginCall call) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("application/octet-stream").addCategory(Intent.CATEGORY_OPENABLE);
        startActivityForResult(call, intent, "backupSelected");
    }
    @PluginMethod public void importModel(PluginCall call) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("application/json").addCategory(Intent.CATEGORY_OPENABLE);
        startActivityForResult(call, intent, "modelSelected");
    }
    @ActivityCallback private void modelSelected(PluginCall call, ActivityResult result) {
        if (call == null) return;
        if (result.getResultCode() != android.app.Activity.RESULT_OK || result.getData() == null || result.getData().getData() == null) { call.reject("モデル取込を取り消しました。"); return; }
        Uri uri = result.getData().getData();
        background(call, () -> {
            byte[] content = read(getContext().getContentResolver().openInputStream(uri), 64 * 1024 * 1024);
            call.resolve(new JSObject().put("content", new String(content, StandardCharsets.UTF_8)));
        });
    }
    @ActivityCallback private void backupSelected(PluginCall call, ActivityResult result) {
        if (call == null) return;
        if (result.getResultCode() != android.app.Activity.RESULT_OK || result.getData() == null || result.getData().getData() == null) { call.reject("復元を取り消しました。"); return; }
        Uri uri = result.getData().getData();
        background(call, () -> {
            // The UI receives an opaque, generation-bound preview, never the
            // complete capsule. SQLite validation still precedes durable commit.
            completeBackup(call, owner().previewBackup(call.getString("password"),
                () -> getContext().getContentResolver().openInputStream(uri)));
        });
    }

    @PluginMethod public void discardBackup(PluginCall call) { background(call, () -> {
        completeBackup(call, owner().discardBackup(call.getString("token")));
    }); }

    @PluginMethod public void restoreBackup(PluginCall call) { background(call, () -> {
        owner().readViews.clear();
        if (!Boolean.TRUE.equals(call.getBoolean("confirmed"))) throw new IllegalArgumentException();
        completeBackup(call, owner().restoreBackup(call.getString("token")));
    }); }

    static HttpURLConnection connection(String url) throws Exception {
        URL target = new URL(url);
        if (!target.getProtocol().equals("https")) throw new SecurityException();
        HttpURLConnection conn = (HttpURLConnection) target.openConnection();
        conn.setConnectTimeout(15000); conn.setReadTimeout(60000); conn.setInstanceFollowRedirects(false);
        conn.setRequestProperty("User-Agent", "StockAI-Android"); return conn;
    }

    MarketDownload marketDownload() { return marketDownload(false); }
    MarketDownload marketDownload(boolean membership) { return new MarketClient(getContext(), db).download(membership); }
    @PluginMethod public void fetchMarket(PluginCall call) { network(call, () -> {
        call.resolve(new JSObject(marketDownload().fetch(call.getString("date")).toString()));
    }); }
    @PluginMethod public void acknowledgeMarket(PluginCall call) { network(call, () -> {
        marketDownload().acknowledge(call.getString("date"), call.getString("acquisitionId"));
        call.resolve();
    }); }
    @PluginMethod public void restartMarket(PluginCall call) { network(call, () -> {
        marketDownload().restart(call.getString("date")); call.resolve();
    }); }
    @PluginMethod public void fetchMembership(PluginCall call) { network(call, () -> {
        call.resolve(new JSObject(marketDownload(true).fetch(call.getString("date")).toString()));
    }); }
    @PluginMethod public void acknowledgeMembership(PluginCall call) { network(call, () -> {
        marketDownload(true).acknowledge(call.getString("date"), call.getString("acquisitionId")); call.resolve();
    }); }
    @PluginMethod public void restartMembership(PluginCall call) { network(call, () -> {
        marketDownload(true).restart(call.getString("date")); call.resolve();
    }); }
    static byte[] read(InputStream stream, long limit) throws Exception {
        try (InputStream input = stream; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[32768]; long count = 0; int length;
            while ((length = input.read(buffer)) != -1) { count += length; if (count > limit) throw new IOException("response limit"); output.write(buffer, 0, length); }
            return output.toByteArray();
        }
    }
    static JSONObject json(String url) throws Exception {
        HttpURLConnection conn = null;
        for (int hop = 0; hop < 5; hop++) {
            conn = connection(url);
            int status = conn.getResponseCode();
            if (status == 200) break;
            if (status != 301 && status != 302 && status != 307 && status != 308) { conn.disconnect(); throw new IOException(); }
            URL next = new URL(new URL(url), conn.getHeaderField("Location")); conn.disconnect(); conn = null;
            if (!next.getProtocol().equals("https") || !Arrays.asList("github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com").contains(next.getHost())) throw new SecurityException();
            url = next.toExternalForm();
        }
        if (conn == null) throw new IOException();
        try { if (conn.getResponseCode() != 200) throw new IOException(); return new JSONObject(new String(read(conn.getInputStream(), 1024 * 1024), StandardCharsets.UTF_8)); }
        finally { conn.disconnect(); }
    }
    long installedVersion() throws Exception {
        PackageInfo info = getContext().getPackageManager().getPackageInfo(getContext().getPackageName(), 0);
        return Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
    }

    @PluginMethod public void appInfo(PluginCall call) {
        try {
            String id = getContext().getPackageName();
            PackageInfo info = getContext().getPackageManager().getPackageInfo(id, 0);
            call.resolve(new JSObject().put("applicationId", id).put("versionName", info.versionName)
                .put("versionCode", installedVersion()));
        } catch (Exception error) { call.reject("アプリ情報を確認できませんでした。"); }
    }

    @PluginMethod public void checkUpdate(PluginCall call) { network(call, () -> {
        JSONObject release = json("https://api.github.com/repos/" + REPO + "/releases/latest");
        if (release.optBoolean("draft") || release.optBoolean("prerelease")) throw new SecurityException();
        String tag = release.getString("tag_name");
        if (!tag.matches("android-v[0-9]+\\.[0-9]+\\.[0-9]+")) throw new SecurityException();
        JSONObject manifest = json("https://github.com/" + REPO + "/releases/download/" + tag + "/update.json");
        // github.com redirects release assets; use the GitHub API asset endpoint
        // through the tightly constrained helper below instead of forwarding auth.
        validateManifest(manifest, tag);
        pendingUpdate = manifest;
        call.resolve(new JSObject(manifest.toString()).put("available", manifest.getLong("versionCode") > installedVersion()));
    }); }

    void validateManifest(JSONObject manifest, String tag) throws Exception {
        if (!manifest.getString("applicationId").equals(getContext().getPackageName()) ||
            !manifest.getString("sha256").matches("[0-9a-f]{64}") || manifest.getLong("size") <= 0 ||
            manifest.getLong("size") > 300 * 1024 * 1024 ||
            !manifest.getString("url").equals("https://github.com/" + REPO + "/releases/download/" + tag + "/StockAI.apk")) throw new SecurityException();
    }

    File download(JSONObject manifest) throws Exception {
        String url = manifest.getString("url"); HttpURLConnection conn = null;
        for (int redirects = 0; redirects < 5; redirects++) {
            conn = connection(url); int status = conn.getResponseCode();
            if (status == 200) break;
            if (status != 301 && status != 302 && status != 307 && status != 308) { conn.disconnect(); throw new IOException(); }
            URL next = new URL(new URL(url), conn.getHeaderField("Location")); conn.disconnect();
            if (!next.getProtocol().equals("https") || !Arrays.asList("github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com").contains(next.getHost())) throw new SecurityException();
            url = next.toExternalForm(); conn = null;
        }
        if (conn == null) throw new IOException();
        File directory = new File(getContext().getCacheDir(), "updates"); directory.mkdirs();
        File apk = new File(directory, "StockAI.apk"); apk.delete();
        MessageDigest digest = MessageDigest.getInstance("SHA-256"); long count = 0;
        try (InputStream input = conn.getInputStream(); FileOutputStream output = new FileOutputStream(apk)) {
            byte[] buffer = new byte[32768]; int length;
            while ((length = input.read(buffer)) != -1) {
                count += length; if (count > manifest.getLong("size")) throw new SecurityException();
                digest.update(buffer, 0, length); output.write(buffer, 0, length);
            }
            output.getFD().sync();
        } catch (Exception error) { apk.delete(); throw error; } finally { conn.disconnect(); }
        StringBuilder hash = new StringBuilder(); for (byte value : digest.digest()) hash.append(String.format("%02x", value & 255));
        if (count != manifest.getLong("size") || !hash.toString().equals(manifest.getString("sha256"))) { apk.delete(); throw new SecurityException(); }
        return apk;
    }

    @SuppressWarnings("deprecation")
    void verifyApk(File apk, long expectedVersion) throws Exception {
        PackageManager pm = getContext().getPackageManager();
        int flags = Build.VERSION.SDK_INT >= 28 ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
        PackageInfo incoming = pm.getPackageArchiveInfo(apk.getAbsolutePath(), flags);
        PackageInfo current = pm.getPackageInfo(getContext().getPackageName(), flags);
        if (incoming == null || !current.packageName.equals(incoming.packageName)) throw new SecurityException();
        long version = Build.VERSION.SDK_INT >= 28 ? incoming.getLongVersionCode() : incoming.versionCode;
        if (version != expectedVersion || version <= installedVersion()) throw new SecurityException();
        android.content.pm.Signature[] a = Build.VERSION.SDK_INT >= 28 ? incoming.signingInfo.getApkContentsSigners() : incoming.signatures;
        android.content.pm.Signature[] b = Build.VERSION.SDK_INT >= 28 ? current.signingInfo.getApkContentsSigners() : current.signatures;
        if (a.length != 1 || b.length != 1 || !MessageDigest.isEqual(a[0].toByteArray(), b[0].toByteArray())) throw new SecurityException();
    }

    @PluginMethod public void installUpdate(PluginCall call) { network(call, () -> {
        if (pendingUpdate == null || call.getInt("versionCode", 0) != pendingUpdate.getLong("versionCode")) throw new SecurityException();
        if (Build.VERSION.SDK_INT >= 26 && !getContext().getPackageManager().canRequestPackageInstalls()) {
            getActivity().runOnUiThread(() -> getActivity().startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getContext().getPackageName()))));
            call.resolve(new JSObject().put("needsPermission", true)); return;
        }
        File apk = download(pendingUpdate); verifyApk(apk, pendingUpdate.getLong("versionCode"));
        Uri uri = FileProvider.getUriForFile(getContext(), getContext().getPackageName() + ".fileprovider", apk);
        Intent intent = new Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        getActivity().runOnUiThread(() -> getActivity().startActivity(intent));
        call.resolve(new JSObject().put("needsPermission", false));
    }); }
}
