import { and, desc, eq } from "drizzle-orm";
import { getDb } from "../db";
import { portfolioImports, portfolioVersions } from "../db/schema";
import { portfolioInput, type SavedPortfolio } from "./portfolio";

export async function loadPortfolio(ownerId: string): Promise<SavedPortfolio | null> {
  const [row] = await getDb().select().from(portfolioVersions)
    .where(eq(portfolioVersions.ownerId, ownerId)).orderBy(desc(portfolioVersions.sequence)).limit(1);
  if (!row) return null;
  const [receipt] = await getDb().select().from(portfolioImports)
    .where(and(eq(portfolioImports.ownerId, ownerId), eq(portfolioImports.revisionId, row.revisionId))).limit(1);
  return { revision_id: row.revisionId, saved_at: row.savedAt, pc_imported_at: receipt?.importedAt ?? null,
    portfolio: portfolioInput.parse(JSON.parse(row.payloadJson)) };
}

export async function existingRevision(ownerId: string, revisionId: string) {
  const [row] = await getDb().select({ id: portfolioVersions.revisionId }).from(portfolioVersions)
    .where(and(eq(portfolioVersions.ownerId, ownerId), eq(portfolioVersions.revisionId, revisionId)));
  return Boolean(row);
}
