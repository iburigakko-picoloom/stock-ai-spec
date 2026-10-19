package jp.stockai.app;

import static org.junit.Assert.*;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.junit.Test;

public class PortableBackupTest {
    static final String PASSWORD = "synthetic-backup-password";
    interface Attempt { void run() throws Exception; }
    static void rejected(Attempt attempt) throws Exception {
        try { attempt.run(); fail("invalid backup accepted"); }
        catch (Exception expected) { /* assertion failures are not swallowed */ }
    }
    static byte[] legacy(String json) throws Exception {
        return BackupCrypto.encrypt(PASSWORD, json.getBytes(StandardCharsets.UTF_8));
    }
    static PortableBackup.Metadata read(byte[] bytes, StringBuilder value) throws Exception {
        return PortableBackup.read(PASSWORD, new ByteArrayInputStream(bytes), (index, fragment) -> {
            assertEquals(value.length() / PortableBackup.CHUNK_CHARACTERS, index);
            assertTrue(fragment.length() <= PortableBackup.CHUNK_CHARACTERS); value.append(fragment);
        });
    }

    @Test public void streamedWriterIsReadableByTheOriginalJceEnvelope() throws Exception {
        String payload = "A".repeat(2 * PortableBackup.CHUNK_CHARACTERS + 4);
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try (PortableBackup.Writer writer = new PortableBackup.Writer(PASSWORD, 42, payload.length(), output)) {
            // Valid older stores may use different individual chunk lengths.
            writer.append(payload.substring(0, 7));
            for (int offset = 7; offset < payload.length(); offset += PortableBackup.CHUNK_CHARACTERS)
                writer.append(payload.substring(offset, Math.min(offset + PortableBackup.CHUNK_CHARACTERS, payload.length())));
            writer.finish();
        }
        String expected = "{\"generation\":42,\"payload\":\"" + payload + "\"}";
        assertEquals(expected, new String(BackupCrypto.decrypt(PASSWORD, output.toByteArray()), StandardCharsets.UTF_8));
        StringBuilder restored = new StringBuilder();
        PortableBackup.Metadata metadata = read(output.toByteArray(), restored);
        assertEquals(42, metadata.generation); assertEquals(payload.length(), metadata.characters);
        assertEquals(payload, restored.toString());
    }

    @Test public void originalEnvelopeAndEscapedFieldsRemainPortable() throws Exception {
        byte[] encrypted = legacy(" { \"payl\\u006fad\": \"\\u0051Q\\u003d\\u003d\", \"generation\": 9007199254740991 } \n");
        StringBuilder restored = new StringBuilder();
        PortableBackup.Metadata metadata = read(encrypted, restored);
        assertEquals(9007199254740991L, metadata.generation); assertEquals(4, metadata.characters);
        assertEquals("QQ==", restored.toString());
        assertEquals(0, read(legacy("{\"generation\":0,\"payload\":\"\"}"), new StringBuilder()).characters);
    }

    @Test public void tagMustBeVerifiedAfterEarlierFragmentsWereQuarantined() throws Exception {
        String payload = "A".repeat(2 * PortableBackup.CHUNK_CHARACTERS + 4);
        byte[] encrypted = legacy("{\"generation\":1,\"payload\":\"" + payload + "\"}");
        encrypted[encrypted.length - 1] ^= 1;
        int[] fragments = {0};
        rejected(() -> PortableBackup.read(PASSWORD, new ByteArrayInputStream(encrypted),
            (index, fragment) -> fragments[0]++));
        assertTrue(fragments[0] > 0);
    }

    @Test public void wrongPasswordTruncatedTagAndTrailingCiphertextAreRejected() throws Exception {
        byte[] encrypted = legacy("{\"generation\":1,\"payload\":\"QQ==\"}");
        rejected(() -> PortableBackup.read("wrong-long-password", new ByteArrayInputStream(encrypted), (index, fragment) -> {}));
        rejected(() -> read(Arrays.copyOf(encrypted, encrypted.length - 1), new StringBuilder()));
        rejected(() -> read(Arrays.copyOf(encrypted, encrypted.length + 1), new StringBuilder()));
        rejected(() -> read(new byte[20], new StringBuilder()));
    }

    @Test public void malformedAndDuplicateFieldsNeverProduceAnAuthenticatedPreview() throws Exception {
        for (String json : new String[]{
            "{}", "{\"generation\":1}", "{\"generation\":1,\"generation\":2}",
            "{\"generation\":1,\"payload\":\"QQ==\",\"extra\":0}",
            "{\"generation\":1.0,\"payload\":\"QQ==\"}",
            "{\"generation\":-1,\"payload\":\"QQ==\"}",
            "{\"generation\":01,\"payload\":\"QQ==\"}",
            "{\"generation\":9007199254740992,\"payload\":\"QQ==\"}",
            "{\"generation\":1,\"payload\":\"あ\"}",
            "{\"generation\":1,\"payload\":\"QQ==\"} trailing",
        }) rejected(() -> read(legacy(json), new StringBuilder()));
    }

    @Test public void incompleteWriterAndOversizedOutputAreRejected() throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try (PortableBackup.Writer writer = new PortableBackup.Writer(PASSWORD, 0, 4, output)) {
            writer.append("QQ"); rejected(writer::finish);
        }
        rejected(() -> read(output.toByteArray(), new StringBuilder()));
        try {
            new PortableBackup.Writer(null, 0, BackupCrypto.MAX_ENVELOPE_BYTES, new ByteArrayOutputStream());
            fail("oversized backup accepted");
        } catch (IllegalArgumentException expected) { assertEquals("Backup exceeds restore limit", expected.getMessage()); }
    }

    @Test public void largeStreamHeaderDoesNotRequireAnInlinePayload() throws Exception {
        for (int length : new int[]{BackupCrypto.MAX_INLINE_ENVELOPE_BYTES + 4,
                PortableBackup.MAX_PAYLOAD_CHARACTERS}) {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            try (PortableBackup.Writer writer = new PortableBackup.Writer(PASSWORD,
                    PortableBackup.MAX_GENERATION, length, output)) {
                rejected(writer::finish); // An announced length never authenticates missing content.
            }
            assertTrue(output.size() < 4096);
            rejected(() -> read(output.toByteArray(), new StringBuilder()));
        }
        ByteArrayOutputStream untouched = new ByteArrayOutputStream();
        try {
            new PortableBackup.Writer(null, 0, PortableBackup.MAX_PAYLOAD_CHARACTERS + 1, untouched);
            fail("oversized state accepted");
        } catch (IllegalArgumentException expected) {
            assertEquals("Backup exceeds restore limit", expected.getMessage());
        }
        assertEquals(0, untouched.size());
    }
}
