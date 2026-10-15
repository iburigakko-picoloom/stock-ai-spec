package jp.stockai.app;

import static org.junit.Assert.*;
import org.junit.Test;
import java.nio.charset.StandardCharsets;

public class BackupCryptoTest {
    @Test public void portableBackupSurvivesNewEncryptionContext() throws Exception {
        byte[] input = "保有・設定・履歴を保持する".getBytes(StandardCharsets.UTF_8);
        byte[] encrypted = BackupCrypto.encrypt("a-long-backup-password", input);
        assertArrayEquals(input, BackupCrypto.decrypt("a-long-backup-password", encrypted));
        assertFalse(java.util.Arrays.equals(encrypted, BackupCrypto.encrypt("a-long-backup-password", input)));
    }
    @Test public void wrongPasswordAndModifiedCiphertextAreRejected() throws Exception {
        byte[] encrypted = BackupCrypto.encrypt("a-long-backup-password", new byte[]{1,2,3});
        try { BackupCrypto.decrypt("incorrect-password", encrypted); fail("Wrong password accepted"); } catch (javax.crypto.AEADBadTagException expected) { }
        encrypted[encrypted.length - 1] ^= 1;
        try { BackupCrypto.decrypt("a-long-backup-password", encrypted); fail("Modified backup accepted"); } catch (javax.crypto.AEADBadTagException expected) { }
    }
    @Test public void truncatedBackupIsRejected() throws Exception {
        try { BackupCrypto.decrypt("a-long-backup-password", new byte[20]); fail("Truncated backup accepted"); } catch (SecurityException expected) { }
    }
}
