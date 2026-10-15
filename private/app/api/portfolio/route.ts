import { getChatGPTUser } from "../../chatgpt-auth";
import { portfolioSave } from "@/lib/portfolio";
import { loadPortfolio, existingRevision } from "@/lib/portfolio-store";
import { sha256 } from "@/lib/daily";
import { getDb } from "@/db";
import { portfolioVersions } from "@/db/schema";

export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "private, no-store" };
export async function GET() {
  const user = await getChatGPTUser();
  if (!user) return Response.json({ error: "サインインしてください" }, { status: 401, headers });
  try { return Response.json({ saved: await loadPortfolio(user.userId) }, { headers }); }
  catch { return Response.json({ error: "保存内容を読み込めませんでした" }, { status: 503, headers }); }
}
export async function POST(request: Request) {
  const user = await getChatGPTUser();
  if (!user) return Response.json({ error: "サインインしてください" }, { status: 401, headers });
  if (request.headers.get("origin") !== new URL(request.url).origin || request.headers.get("X-Stock-AI-Intent") !== "manual-record")
    return Response.json({ error: "入力画面から保存してください" }, { status: 403, headers });
  if (Number(request.headers.get("content-length") ?? 0) > 150_000)
    return Response.json({ error: "入力が大きすぎます" }, { status: 413, headers });
  let input;
  try {
    const raw = await request.text();
    if (raw.length > 150_000) return Response.json({ error: "入力が大きすぎます" }, { status: 413, headers });
    input = portfolioSave.safeParse(JSON.parse(raw));
  } catch { return Response.json({ error: "入力を確認してください" }, { status: 422, headers }); }
  if (!input.success) return Response.json({ error: input.error.issues[0].message }, { status: 422, headers });
  try {
    const { portfolio, expected_revision_id: parent } = input.data;
    const payloadJson = JSON.stringify(portfolio);
    const revision = await sha256(JSON.stringify({ owner: user.userId, parent, portfolio }));
    if (await existingRevision(user.userId, revision))
      return Response.json({ saved: await loadPortfolio(user.userId), replayed: true }, { headers });
    const current = await loadPortfolio(user.userId);
    if ((current?.revision_id ?? null) !== parent)
      return Response.json({ error: "別の画面で更新されています。保存内容を読み直してください。" }, { status: 409, headers });
    // Unique(owner,parent) is the atomic compare-and-set even for simultaneous requests.
    const inserted = await getDb().insert(portfolioVersions).values({ revisionId: revision,
      ownerId: user.userId, parentRevision: parent ?? "initial", savedAt: new Date().toISOString(), payloadJson,
    }).onConflictDoNothing().returning({ id: portfolioVersions.revisionId });
    if (!inserted.length && !await existingRevision(user.userId, revision))
      return Response.json({ error: "別の画面で更新されています。保存内容を読み直してください。" }, { status: 409, headers });
    return Response.json({ saved: await loadPortfolio(user.userId), replayed: !inserted.length }, { headers });
  } catch { return Response.json({ error: "保存できませんでした。入力内容は画面に残っています。" }, { status: 503, headers }); }
}
