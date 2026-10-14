import { and, desc, eq } from "drizzle-orm";
import { getDb } from "../db";
import { portfolioVersions } from "../db/schema";
import { portfolioInput, type SavedPortfolio } from "./portfolio";

export async function loadPortfolio(ownerId: string): Promise<SavedPortfolio | null> {
  const [row] = await getDb().select().from(portfolioVersions)
    .where(eq(portfolioVersions.ownerId, ownerId)).orderBy(desc(portfolioVersions.sequence)).limit(1);
  return row ? { revision_id: row.revisionId, saved_at: row.savedAt,
    portfolio: portfolioInput.parse(JSON.parse(row.payloadJson)) } : null;
}

export async function existingRevision(ownerId: string, revisionId: string) {
  const [row] = await getDb().select({ id: portfolioVersions.revisionId }).from(portfolioVersions)
    .where(and(eq(portfolioVersions.ownerId, ownerId), eq(portfolioVersions.revisionId, revisionId)));
  return Boolean(row);
}
