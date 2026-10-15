import { env } from "cloudflare:workers";
import { getChatGPTUser } from "../../../chatgpt-auth";
import { canExportPortfolio } from "@/lib/portfolio-export";
import { latestSettingsRow } from "@/lib/settings-store";
import { loadPortfolio } from "@/lib/portfolio-store";
import { exportSettings } from "@/lib/settings-export";

export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "private, no-store" };
export async function GET(request: Request) {
  const user = await getChatGPTUser();
  const owner = user?.userId ?? (await canExportPortfolio(request, env.STOCK_AI_PORTFOLIO_OWNER_ID,
    env.STOCK_AI_PORTFOLIO_TOKEN_SHA256) ? env.STOCK_AI_PORTFOLIO_OWNER_ID : null);
  if (!owner) return Response.json({ error: "サインインしてください" }, { status: 401, headers });
  try {
    const [row, portfolio] = await Promise.all([latestSettingsRow(owner), loadPortfolio(owner)]);
    if (!row) return Response.json({ error: "補足設定は未保存です" }, { status: 404, headers });
    if (!portfolio || row.portfolioRevisionId !== portfolio.revision_id)
      return Response.json({ error: "口座・保有が更新されています。補足設定を再確認して保存してください。" }, { status: 409, headers });
    return Response.json(await exportSettings(row), { headers: { ...headers,
      "Content-Disposition": 'attachment; filename="stock-ai-personal-settings.json"' } });
  } catch { return Response.json({ error: "補足設定を書き出せませんでした" }, { status: 503, headers }); }
}
