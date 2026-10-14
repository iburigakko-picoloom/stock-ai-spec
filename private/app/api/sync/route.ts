import { eq } from "drizzle-orm";
import { getDb } from "@/db";
import { snapshots } from "@/db/schema";
import { validateSync } from "@/lib/daily";

export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "private, no-store" };

// Only deployed behind the confirmed OWNER-PRIVATE Sites boundary. Dispatch
// authenticates and consumes OAI-Sites-Authorization before this Worker runs.
// This marker prevents accidental browser requests; it is not a secret.
function serviceRequest(request: Request) {
  if (request.headers.get("X-Stock-AI-Sync") !== "private-v1") return false;
  const origin = request.headers.get("origin");
  return !origin || origin === new URL(request.url).origin;
}
export async function POST(request: Request) {
  if (!serviceRequest(request)) return Response.json({ error: "sync marker required" }, { status: 403, headers });
  if (Number(request.headers.get("content-length") ?? 0) > 1_100_000)
    return Response.json({ error: "payload too large" }, { status: 413, headers });
  try {
    const text = await request.text();
    if (text.length > 1_100_000) return Response.json({ error: "payload too large" }, { status: 413, headers });
    const { request: input, payload } = await validateSync(JSON.parse(text));
    const db = getDb();
    await db.insert(snapshots).values({ snapshotId: input.snapshot_id,
      sourceSnapshotId: payload.source_snapshot_id, asOf: new Date(payload.as_of).toISOString(),
      receivedAt: new Date().toISOString(), payloadJson: input.payload_json,
    }).onConflictDoNothing();
    const [saved] = await db.select().from(snapshots).where(eq(snapshots.snapshotId, input.snapshot_id));
    if (!saved || saved.payloadJson !== input.payload_json)
      return Response.json({ error: "immutable snapshot conflict" }, { status: 409, headers });
    return Response.json({ snapshot_id: saved.snapshotId, received_at: saved.receivedAt, verified: true }, { headers });
  } catch {
    return Response.json({ error: "invalid snapshot or unavailable storage" }, { status: 422, headers });
  }
}
export async function GET(request: Request) {
  if (!serviceRequest(request)) return Response.json({ error: "sync marker required" }, { status: 403, headers });
  const id = new URL(request.url).searchParams.get("id");
  if (!id || !/^[0-9a-f]{64}$/.test(id)) return Response.json({ error: "snapshot ID required" }, { status: 400, headers });
  const [saved] = await getDb().select().from(snapshots).where(eq(snapshots.snapshotId, id));
  return saved ? Response.json({ snapshot_id: saved.snapshotId, payload_json: saved.payloadJson, received_at: saved.receivedAt }, { headers })
    : Response.json({ error: "not found" }, { status: 404, headers });
}
