import { env } from "cloudflare:workers";
import { and, desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { portfolioImports, portfolioVersions } from "@/db/schema";
import { portfolioInput } from "@/lib/portfolio";
import { canExportPortfolio, exportPortfolio, importAcknowledgment } from "@/lib/portfolio-export";

const headers = { "Cache-Control": "private, no-store" };
async function ownerFor(request: Request) {
  const owner = env.STOCK_AI_PORTFOLIO_OWNER_ID;
  return await canExportPortfolio(request, owner, env.STOCK_AI_PORTFOLIO_TOKEN_SHA256) ? owner : null;
}
export async function GET(request: Request) {
  const owner = await ownerFor(request);
  if (!owner) return Response.json({ error: "unauthorized" }, { status: 401, headers });
  try {
    const [row] = await getDb().select().from(portfolioVersions).where(eq(portfolioVersions.ownerId, owner))
      .orderBy(desc(portfolioVersions.sequence)).limit(1);
    if (!row) return Response.json({ error: "portfolio not recorded" }, { status: 404, headers });
    portfolioInput.parse(JSON.parse(row.payloadJson));
    return Response.json(await exportPortfolio(row), { headers });
  } catch { return Response.json({ error: "portfolio export unavailable" }, { status: 503, headers }); }
}
export async function POST(request: Request) {
  const owner = await ownerFor(request);
  if (!owner) return Response.json({ error: "unauthorized" }, { status: 401, headers });
  if (Number(request.headers.get("content-length") ?? 0) > 2_000)
    return Response.json({ error: "request too large" }, { status: 413, headers });
  let input;
  try {
    const raw = await request.text();
    if (raw.length > 2_000) return Response.json({ error: "request too large" }, { status: 413, headers });
    input = importAcknowledgment.parse(JSON.parse(raw));
  } catch { return Response.json({ error: "invalid acknowledgment" }, { status: 422, headers }); }
  try {
    const db = getDb();
    const [row] = await db.select().from(portfolioVersions)
      .where(and(eq(portfolioVersions.ownerId, owner), eq(portfolioVersions.revisionId, input.revision_id))).limit(1);
    if (!row) return Response.json({ error: "unknown revision" }, { status: 404, headers });
    const envelope = await exportPortfolio(row);
    if (envelope.export_sha256 !== input.export_sha256 || Date.parse(input.imported_at) < Date.parse(row.savedAt)
        || Date.parse(input.imported_at) > Date.now() + 60_000)
      return Response.json({ error: "acknowledgment mismatch" }, { status: 409, headers });
    await db.insert(portfolioImports).values({ ownerId: owner, revisionId: row.revisionId,
      exportSha256: envelope.export_sha256, importedAt: input.imported_at, acknowledgedAt: new Date().toISOString(),
    }).onConflictDoNothing();
    const [ack] = await db.select().from(portfolioImports)
      .where(and(eq(portfolioImports.ownerId, owner), eq(portfolioImports.revisionId, row.revisionId))).limit(1);
    if (!ack || ack.exportSha256 !== input.export_sha256 || Date.parse(ack.importedAt) !== Date.parse(input.imported_at))
      return Response.json({ error: "acknowledgment conflict" }, { status: 409, headers });
    return Response.json({ revision_id: row.revisionId, export_sha256: ack.exportSha256, acknowledged: true }, { headers });
  } catch { return Response.json({ error: "acknowledgment unavailable" }, { status: 503, headers }); }
}
