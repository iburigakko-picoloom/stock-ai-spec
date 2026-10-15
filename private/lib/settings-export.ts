export type SettingsRow = {
  revisionId: string; ownerId: string; parentRevision: string; sequence: number; savedAt: string; payloadJson: string;
};
export async function settingsHash(value: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}
export async function exportSettings(row: SettingsRow) {
  const revisionJson = `{"owner":${JSON.stringify(row.ownerId)},"parent":${JSON.stringify(row.parentRevision === "initial" ? null : row.parentRevision)},"settings":${row.payloadJson}}`;
  if (await settingsHash(revisionJson) !== row.revisionId) throw new Error("settings revision content mismatch");
  const exportJson = JSON.stringify({ schema_version: "manual-personal-settings-export-v1", revision_id: row.revisionId,
    revision_sequence: row.sequence, saved_at: row.savedAt, revision_json: revisionJson });
  return { export_sha256: await settingsHash(exportJson), export_json: exportJson };
}
