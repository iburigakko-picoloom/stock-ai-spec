import { getChatGPTUser } from "../../chatgpt-auth";
import { getDb } from "@/db";
import { personalSettingsVersions } from "@/db/schema";
import { settingsSave, validateSettingsPortfolio } from "@/lib/personal-settings";
import { existingSettingsRevision, loadSettings } from "@/lib/settings-store";
import { loadPortfolio } from "@/lib/portfolio-store";
import { settingsHash } from "@/lib/settings-export";

export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "private, no-store" };
export async function GET() {
  const user = await getChatGPTUser();
  if (!user) return Response.json({ error: "サインインしてください" }, { status: 401, headers });
  try {
    const [saved, portfolio] = await Promise.all([loadSettings(user.userId), loadPortfolio(user.userId)]);
    return Response.json({ saved, current_portfolio_revision_id: portfolio?.revision_id ?? null }, { headers });
  } catch { return Response.json({ error: "補足設定を読み込めませんでした" }, { status: 503, headers }); }
}
export async function POST(request: Request) {
  const user = await getChatGPTUser();
  if (!user) return Response.json({ error: "サインインしてください" }, { status: 401, headers });
  if (request.headers.get("origin") !== new URL(request.url).origin || request.headers.get("X-Stock-AI-Intent") !== "manual-record")
    return Response.json({ error: "入力画面から保存してください" }, { status: 403, headers });
  if (Number(request.headers.get("content-length") ?? 0) > 80_000)
    return Response.json({ error: "入力が大きすぎます" }, { status: 413, headers });
  let input;
  try {
    const text = await request.text();
    if (text.length > 80_000) return Response.json({ error: "入力が大きすぎます" }, { status: 413, headers });
    input = settingsSave.safeParse(JSON.parse(text));
  } catch { return Response.json({ error: "入力を確認してください" }, { status: 422, headers }); }
  if (!input.success) return Response.json({ error: input.error.issues[0].message }, { status: 422, headers });
  try {
    const { settings, expected_revision_id: parent } = input.data;
    const portfolio = await loadPortfolio(user.userId);
    if (!portfolio) return Response.json({ error: "先に口座・保有を保存してください" }, { status: 409, headers });
    const mismatch = validateSettingsPortfolio(settings, portfolio.revision_id, portfolio.portfolio);
    if (mismatch) return Response.json({ error: mismatch }, { status: 409, headers });
    const revision = await settingsHash(JSON.stringify({ owner: user.userId, parent, settings }));
    if (!await existingSettingsRevision(user.userId, revision)) {
      const current = await loadSettings(user.userId);
      if ((current?.revision_id ?? null) !== parent)
        return Response.json({ error: "補足設定が別の画面で更新されています。保存内容を読み直してください。" }, { status: 409, headers });
      const inserted = await getDb().insert(personalSettingsVersions).values({ revisionId: revision, ownerId: user.userId,
        parentRevision: parent ?? "initial", portfolioRevisionId: portfolio.revision_id,
        savedAt: new Date().toISOString(), payloadJson: JSON.stringify(settings),
      }).onConflictDoNothing().returning({ id: personalSettingsVersions.revisionId });
      if (!inserted.length && !await existingSettingsRevision(user.userId, revision))
        return Response.json({ error: "別の保存と重なりました。保存内容を読み直してください。" }, { status: 409, headers });
    }
    const latestPortfolio = await loadPortfolio(user.userId);
    return Response.json({ saved: await loadSettings(user.userId), current_portfolio_revision_id: latestPortfolio?.revision_id ?? null }, { headers });
  } catch { return Response.json({ error: "保存できませんでした。入力は画面に残っています。" }, { status: 503, headers }); }
}
