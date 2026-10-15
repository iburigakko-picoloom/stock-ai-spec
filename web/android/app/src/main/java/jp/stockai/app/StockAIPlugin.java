package jp.stockai.app;

import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import androidx.core.content.FileProvider;
import androidx.activity.result.ActivityResult;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.ActivityCallback;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.*;

@CapacitorPlugin(name = "StockAI")
public class StockAIPlugin extends Plugin {
    static final String REPO = "iburigakko-picoloom/stock-ai-spec";
    static final String KEY_ALIAS = "stockai-local-v1";
    final ExecutorService executor = Executors.newSingleThreadExecutor();
    final ExecutorService networkExecutor = Executors.newSingleThreadExecutor();
    SQLiteDatabase db;
    volatile JSONObject pendingUpdate;
    static final int STATE_CHUNK_CHARACTERS = 256 * 1024;
    static final int MAX_STATE_CHARACTERS = 128 * 1024 * 1024;
    static final String STATE_FORMAT = "stockai-state-chunks-v1:";

    static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder();
        for (byte value : bytes) result.append(String.format("%02x", value & 255));
        return result.toString();
    }

    byte[] encryptChunk(String text, long generation, int index) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        cipher.updateAAD(("state:" + generation + ":" + index).getBytes(StandardCharsets.US_ASCII));
        ByteArrayOutputStream output = new ByteArrayOutputStream(); output.write(cipher.getIV());
        output.write(cipher.doFinal(text.getBytes(StandardCharsets.UTF_8))); return output.toByteArray();
    }

    String decryptChunk(byte[] data, long generation, int index) throws Exception {
        if (data.length < 28 || data.length > STATE_CHUNK_CHARACTERS * 4 + 28) throw new SecurityException();
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Arrays.copyOfRange(data, 0, 12)));
        cipher.updateAAD(("state:" + generation + ":" + index).getBytes(StandardCharsets.US_ASCII));
        return new String(cipher.doFinal(data, 12, data.length - 12), StandardCharsets.UTF_8);
    }

    JSObject readStateData() throws Exception {
        JSObject result = new JSObject().put("generation", 0).put("payload", "");
        try (Cursor cursor = db.rawQuery("SELECT generation,payload FROM state WHERE id=1", null)) {
            if (cursor.moveToFirst()) {
                long generation = cursor.getLong(0);
                String envelope = decrypt(cursor.getBlob(1));
                String payload = envelope;
                if (envelope.startsWith(STATE_FORMAT)) {
                    JSONObject metadata = new JSONObject(envelope.substring(STATE_FORMAT.length()));
                    int length = metadata.getInt("length"), count = metadata.getInt("chunks");
                    if (length < 0 || length > MAX_STATE_CHARACTERS || count != (length + STATE_CHUNK_CHARACTERS - 1) / STATE_CHUNK_CHARACTERS) throw new SecurityException();
                    StringBuilder content = new StringBuilder(length); MessageDigest digest = MessageDigest.getInstance("SHA-256");
                    int index = 0;
                    try (Cursor chunks = db.rawQuery("SELECT piece,payload FROM state_chunks ORDER BY piece", null)) {
                        while (chunks.moveToNext()) {
                            if (chunks.getInt(0) != index || index >= count) throw new SecurityException();
                            String fragment = decryptChunk(chunks.getBlob(1), generation, index++);
                            if (fragment.length() > STATE_CHUNK_CHARACTERS) throw new SecurityException();
                            digest.update(fragment.getBytes(StandardCharsets.UTF_8)); content.append(fragment);
                        }
                    }
                    if (index != count || content.length() != length || !hex(digest.digest()).equals(metadata.getString("sha256"))) throw new SecurityException();
                    payload = content.toString();
                }
                result.put("generation", generation); result.put("payload", payload);
            }
        }
        return result;
    }

    @Override public void load() {
        db = getContext().openOrCreateDatabase("stockai-device.sqlite3", 0, null);
        initializeStateTables();
    }

    void initializeStateTables() {
        db.execSQL("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL, payload BLOB NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS state_chunks (piece INTEGER PRIMARY KEY, payload BLOB NOT NULL)");
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

    synchronized SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (!store.containsAlias(KEY_ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(KEY_ALIAS, null);
    }

    byte[] encrypt(String text) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        byte[] encrypted = cipher.doFinal(text.getBytes(StandardCharsets.UTF_8));
        ByteArrayOutputStream output = new ByteArrayOutputStream(); output.write(cipher.getIV()); output.write(encrypted); return output.toByteArray();
    }
    String decrypt(byte[] data) throws Exception {
        if (data.length < 28) throw new SecurityException();
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Arrays.copyOfRange(data, 0, 12)));
        return new String(cipher.doFinal(data, 12, data.length - 12), StandardCharsets.UTF_8);
    }

    @PluginMethod public void readState(PluginCall call) { background(call, () -> {
        call.resolve(readStateData());
    }); }

    long writeStateData(long generation, String payload) throws Exception {
        if (generation < 0 || payload == null || payload.length() > MAX_STATE_CHARACTERS) throw new IllegalArgumentException();
        db.beginTransaction();
        try {
            long current = 0;
            try (Cursor cursor = db.rawQuery("SELECT generation FROM state WHERE id=1", null)) { if (cursor.moveToFirst()) current = cursor.getLong(0); }
            if (current != generation) throw new IllegalStateException("state conflict");
            db.execSQL("DELETE FROM state_chunks");
            MessageDigest digest = MessageDigest.getInstance("SHA-256"); int index = 0;
            for (int offset = 0; offset < payload.length(); offset += STATE_CHUNK_CHARACTERS) {
                String fragment = payload.substring(offset, Math.min(offset + STATE_CHUNK_CHARACTERS, payload.length()));
                digest.update(fragment.getBytes(StandardCharsets.UTF_8));
                db.execSQL("INSERT INTO state_chunks(piece,payload) VALUES(?,?)", new Object[]{index, encryptChunk(fragment, current + 1, index)});
                index++;
            }
            JSONObject metadata = new JSONObject().put("length", payload.length()).put("chunks", index).put("sha256", hex(digest.digest()));
            db.execSQL("INSERT OR REPLACE INTO state(id,generation,payload) VALUES(1,?,?)", new Object[]{current + 1, encrypt(STATE_FORMAT + metadata.toString())});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
        return generation + 1;
    }

    @PluginMethod public void writeState(PluginCall call) { background(call, () -> {
        Integer generation = call.getInt("generation");
        if (generation == null) throw new IllegalArgumentException();
        long saved = writeStateData(generation, call.getString("payload"));
        call.resolve(new JSObject().put("generation", saved));
    }); }

    String apiKey() throws Exception {
        String value = getContext().getSharedPreferences("stockai-secrets", 0).getString("jquants", null);
        return value == null ? null : decrypt(Base64.decode(value, Base64.NO_WRAP));
    }
    @PluginMethod public void keyStatus(PluginCall call) { background(call, () -> call.resolve(new JSObject().put("configured", apiKey() != null))); }
    @PluginMethod public void saveApiKey(PluginCall call) { background(call, () -> {
        String value = call.getString("apiKey");
        if (value == null || value.trim().length() < 8 || value.length() > 4096 || value.contains("\n") || value.contains("\r")) throw new IllegalArgumentException();
        if (!getContext().getSharedPreferences("stockai-secrets", 0).edit().putString("jquants", Base64.encodeToString(encrypt(value.trim()), Base64.NO_WRAP)).commit()) throw new IOException();
        call.resolve();
    }); }
    @PluginMethod public void clearApiKey(PluginCall call) { background(call, () -> {
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
            byte[] bytes = BackupCrypto.encrypt(call.getString("password"), readStateData().toString().getBytes(StandardCharsets.UTF_8));
            try (OutputStream stream = getContext().getContentResolver().openOutputStream(uri, "wt")) { if (stream == null) throw new IOException(); stream.write(bytes); stream.flush(); }
            call.resolve();
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
            byte[] content = read(getContext().getContentResolver().openInputStream(uri), 128 * 1024 * 1024);
            JSONObject value = new JSONObject(new String(BackupCrypto.decrypt(call.getString("password"), content), StandardCharsets.UTF_8));
            if (!value.has("payload") || value.length() != 2 || !value.has("generation")) throw new SecurityException();
            // Return a preview only. Restoring requires Python integrity checks
            // and an explicit later confirmation before a CAS durable write.
            call.resolve(new JSObject(value.toString()));
        });
    }

    static HttpURLConnection connection(String url) throws Exception {
        URL target = new URL(url);
        if (!target.getProtocol().equals("https")) throw new SecurityException();
        HttpURLConnection conn = (HttpURLConnection) target.openConnection();
        conn.setConnectTimeout(15000); conn.setReadTimeout(60000); conn.setInstanceFollowRedirects(false);
        conn.setRequestProperty("User-Agent", "StockAI-Android"); return conn;
    }

    long lastProviderRequest = 0;
    @PluginMethod public void fetchMarket(PluginCall call) { network(call, () -> {
        String day = call.getString("date"), credential = apiKey();
        if (day == null || !day.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}") || credential == null) throw new IllegalArgumentException();
        String[][] endpoints = {{"security_master", "/equities/master"}, {"daily_prices", "/equities/bars/daily"},
            {"trading_calendar", "/markets/calendar"}, {"topix", "/indices/bars/daily/topix"}, {"financial_summary", "/fins/summary"}};
        JSONObject datasets = new JSONObject();
        for (String[] endpoint : endpoints) {
            JSONArray records = new JSONArray(); String page = null;
            java.util.HashSet<String> seen = new java.util.HashSet<>();
            do {
                long delay = 12500 - (android.os.SystemClock.elapsedRealtime() - lastProviderRequest);
                if (lastProviderRequest != 0 && delay > 0) Thread.sleep(delay);
                String query = endpoint[0].equals("trading_calendar") ? "?from=" + day + "&to=" + java.time.LocalDate.parse(day).plusDays(21) : "?date=" + day;
                if (page != null) query += "&pagination_key=" + java.net.URLEncoder.encode(page, "UTF-8");
                HttpURLConnection conn = connection("https://api.jquants.com/v2" + endpoint[1] + query);
                conn.setRequestProperty("x-api-key", credential);
                try {
                    lastProviderRequest = android.os.SystemClock.elapsedRealtime(); int status = conn.getResponseCode();
                    if (status != 200) { call.resolve(new JSObject().put("date", day).put("status", status).put("failedDataset", endpoint[0])); return; }
                    JSONObject response = new JSONObject(new String(read(conn.getInputStream(), 20 * 1024 * 1024), StandardCharsets.UTF_8));
                    JSONArray values = response.getJSONArray("data");
                    for (int i = 0; i < values.length(); i++) records.put(values.getJSONObject(i));
                    page = response.optString("pagination_key", "");
                    if (page.isEmpty()) page = null;
                    if (page != null && (!seen.add(page) || seen.size() > 100)) throw new SecurityException();
                } finally { conn.disconnect(); }
            } while (page != null);
            datasets.put(endpoint[0], records);
        }
        java.text.SimpleDateFormat format = new java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", java.util.Locale.US);
        format.setTimeZone(java.util.TimeZone.getTimeZone("UTC"));
        call.resolve(new JSObject().put("date", day).put("received_at", format.format(new java.util.Date())).put("status", 200).put("datasets", datasets));
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
