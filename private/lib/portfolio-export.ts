import { z } from "zod";

const hash = z.string().regex(/^[0-9a-f]{64}$/);
export const importAcknowledgment = z.object({
  revision_id: hash, export_sha256: hash, imported_at: z.string().datetime({ offset: true }),
}).strict();
export async function contentHash(value: string) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, "0")).join("");
}

// The Site service credential is consumed by dispatch, not a visitor identity.
// A separate scoped proof plus a pinned per-Site owner protects this endpoint.
export async function canExportPortfolio(request: Request, owner: string | undefined, tokenHash: string | undefined) {
  const token = request.headers.get("X-Stock-AI-Portfolio-Access") ?? "";
  const origin = request.headers.get("origin");
  const visitor = request.headers.get("oai-authenticated-user-id");
  if (!owner || !tokenHash || !/^[0-9a-f]{64}$/.test(tokenHash) || !/^[0-9a-f]{64}$/.test(token)
      || (origin && origin !== new URL(request.url).origin) || (visitor && visitor !== owner)) return false;
  const observed = await contentHash(token);
  let difference = 0;
  for (let i = 0; i < 64; i++) difference |= observed.charCodeAt(i) ^ tokenHash.charCodeAt(i);
  return difference === 0;
}

export type ExportRow = {
  revisionId: string; sequence: number; ownerId: string; parentRevision: string; savedAt: string; payloadJson: string;
};
export async function exportPortfolio(row: ExportRow) {
  // Preserve the exact saved payload bytes, including JavaScript number spelling.
  const revisionJson = `{"owner":${JSON.stringify(row.ownerId)},"parent":${JSON.stringify(row.parentRevision === "initial" ? null : row.parentRevision)},"portfolio":${row.payloadJson}}`;
  if (await contentHash(revisionJson) !== row.revisionId) throw new Error("revision content mismatch");
  const exportJson = JSON.stringify({ schema_version: "manual-portfolio-export-v1",
    revision_id: row.revisionId, revision_sequence: row.sequence, saved_at: row.savedAt, revision_json: revisionJson });
  return { export_sha256: await contentHash(exportJson), export_json: exportJson };
}
