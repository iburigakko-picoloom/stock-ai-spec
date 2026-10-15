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
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
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
    SQLiteDatabase db;
    JSONObject pendingUpdate;

    @Override public void load() {
        db = getContext().openOrCreateDatabase("stockai-device.sqlite3", 0, null);
        db.execSQL("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL, payload BLOB NOT NULL)");
    }

    interface Work { void run() throws Exception; }
    void background(PluginCall call, Work work) {
        executor.execute(() -> { try { work.run(); } catch (Exception ignored) {
            // Exceptions can contain provider URLs, credentials or account data.
            call.reject("端末の処理に失敗しました。通信・権限・保存領域を確認してください。", "STOCKAI_OPERATION_FAILED");
        }});
    }

    SecretKey key() throws Exception {
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
        JSObject result = new JSObject().put("generation", 0).put("payload", "");
        try (Cursor cursor = db.rawQuery("SELECT generation,payload FROM state WHERE id=1", null)) {
            if (cursor.moveToFirst()) { result.put("generation", cursor.getLong(0)); result.put("payload", decrypt(cursor.getBlob(1))); }
        }
        call.resolve(result);
    }); }

    @PluginMethod public void writeState(PluginCall call) { background(call, () -> {
        Integer generation = call.getInt("generation"); String payload = call.getString("payload");
        if (generation == null || payload == null || payload.length() > 128 * 1024 * 1024) throw new IllegalArgumentException();
        byte[] encrypted = encrypt(payload);
        db.beginTransaction();
        try {
            long current = 0;
            try (Cursor cursor = db.rawQuery("SELECT generation FROM state WHERE id=1", null)) { if (cursor.moveToFirst()) current = cursor.getLong(0); }
            if (current != generation) throw new IllegalStateException("state conflict");
            db.execSQL("INSERT OR REPLACE INTO state(id,generation,payload) VALUES(1,?,?)", new Object[]{ current + 1, encrypted });
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
        call.resolve(new JSObject().put("generation", generation + 1));
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
    @PluginMethod public void clearApiKey(PluginCall call) {
        getContext().getSharedPreferences("stockai-secrets", 0).edit().remove("jquants").commit(); call.resolve();
    }

    static HttpURLConnection connection(String url) throws Exception {
        URL target = new URL(url);
        if (!target.getProtocol().equals("https")) throw new SecurityException();
        HttpURLConnection conn = (HttpURLConnection) target.openConnection();
        conn.setConnectTimeout(15000); conn.setReadTimeout(60000); conn.setInstanceFollowRedirects(false);
        conn.setRequestProperty("User-Agent", "StockAI-Android"); return conn;
    }
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

    @PluginMethod public void checkUpdate(PluginCall call) { background(call, () -> {
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

    @PluginMethod public void installUpdate(PluginCall call) { background(call, () -> {
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
