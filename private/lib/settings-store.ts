import { and, desc, eq } from "drizzle-orm";
import { getDb } from "../db";
import { personalSettingsVersions, portfolioVersions } from "../db/schema";
import { personalSettingsInput, type SavedSettings } from "./personal-settings";
import { exportSettings } from "./settings-export";

export async function latestSettingsRow(ownerId: string) {
  const [row] = await getDb().select().from(personalSettingsVersions)
    .where(eq(personalSettingsVersions.ownerId, ownerId)).orderBy(desc(personalSettingsVersions.sequence)).limit(1);
  if (!row) return null;
  await exportSettings(row);
  const value = personalSettingsInput.parse(JSON.parse(row.payloadJson));
  if (row.portfolioRevisionId !== value.portfolio_revision_id) throw new Error("settings portfolio reference mismatch");
  const [parent] = await getDb().select({ id: portfolioVersions.revisionId }).from(portfolioVersions)
    .where(and(eq(portfolioVersions.ownerId, ownerId), eq(portfolioVersions.revisionId, row.portfolioRevisionId))).limit(1);
  if (!parent) throw new Error("settings owner portfolio missing");
  return row;
}
export async function loadSettings(ownerId: string): Promise<SavedSettings | null> {
  const row = await latestSettingsRow(ownerId);
  return row ? { revision_id: row.revisionId, saved_at: row.savedAt, settings: personalSettingsInput.parse(JSON.parse(row.payloadJson)) } : null;
}
export async function existingSettingsRevision(ownerId: string, revisionId: string) {
  const [row] = await getDb().select({ id: personalSettingsVersions.revisionId }).from(personalSettingsVersions)
    .where(and(eq(personalSettingsVersions.ownerId, ownerId), eq(personalSettingsVersions.revisionId, revisionId))).limit(1);
  return Boolean(row);
}
