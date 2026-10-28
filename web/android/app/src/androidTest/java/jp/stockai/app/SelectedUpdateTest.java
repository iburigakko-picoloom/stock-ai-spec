package jp.stockai.app;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;

import androidx.test.core.app.ApplicationProvider;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.nio.file.Files;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class SelectedUpdateTest {
    @Test public void copyIsBoundedAndRejectsEmptyOrOversizedFiles() throws Exception {
        android.content.Context context = ApplicationProvider.getApplicationContext();
        File file = File.createTempFile("selected-update-test-", ".apk", context.getCacheDir());
        try {
            StockAIPlugin.copySelectedApk(new ByteArrayInputStream(new byte[]{1, 2, 3}), file, 3);
            assertArrayEquals(new byte[]{1, 2, 3}, Files.readAllBytes(file.toPath()));
            assertThrows(Exception.class, () -> StockAIPlugin.copySelectedApk(new ByteArrayInputStream(new byte[]{1, 2, 3, 4}), file, 3));
            assertFalse(file.exists());
            assertThrows(Exception.class, () -> StockAIPlugin.copySelectedApk(new ByteArrayInputStream(new byte[0]), file, 3));
            assertFalse(file.exists());
        } finally { file.delete(); }
    }

    @Test public void installedOrInvalidApkCannotBeUsedAsAnUpdate() throws Exception {
        android.content.Context context = ApplicationProvider.getApplicationContext();
        StockAIPlugin plugin = new StockAIPlugin() { @Override public android.content.Context getContext() { return context; } };
        File installed = new File(context.getApplicationInfo().sourceDir);
        long current = android.os.Build.VERSION.SDK_INT >= 28
            ? context.getPackageManager().getPackageInfo(context.getPackageName(), 0).getLongVersionCode()
            : context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionCode;
        assertThrows(SecurityException.class, () -> plugin.verifyApk(installed, current));
        File invalid = File.createTempFile("invalid-update-test-", ".apk", context.getCacheDir());
        try { assertThrows(SecurityException.class, () -> plugin.verifyApk(invalid, current + 1)); }
        finally { invalid.delete(); }
    }
}
