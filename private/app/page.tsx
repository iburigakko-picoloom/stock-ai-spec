import { desc } from "drizzle-orm";
import Link from "next/link";
import { requireChatGPTUser, chatGPTSignOutPath } from "./chatgpt-auth";
import { getDb } from "@/db";
import { snapshots } from "@/db/schema";
import { cloudPayload, criterionLabels, type CloudPayload } from "@/lib/daily";

export const dynamic = "force-dynamic";
const fmtTime = (time: string | null) => time ? new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(time)) + " JST" : "未取得";
const percent = (value: number) => `${value > 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
const dateJst = (date: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
const assessment = { support: "支持", caution: "注意", defer: "保留" };

export default async function Home() {
  await requireChatGPTUser("/");
  let payload: CloudPayload | null = null;
  let receivedAt: string | null = null;
  let storageError = false;
  try {
    const [saved] = await getDb().select().from(snapshots).orderBy(desc(snapshots.asOf), desc(snapshots.receivedAt)).limit(1);
    if (saved) { payload = cloudPayload.parse(JSON.parse(saved.payloadJson)); receivedAt = saved.receivedAt; }
  } catch { storageError = true; }
  const stale = !payload || dateJst(new Date(payload.as_of)) !== dateJst(new Date());
  const forecasts = payload?.forecasts ?? [];
  return <main className="shell">
    <header className="topbar"><Link href="/" className="brand"><span className="brand-mark">株</span><span>株AI<small>DAILY RESEARCH</small></span></Link><span className="private-badge">● 本人専用</span></header>
    <nav aria-label="ページ内メニュー"><a href="#overview">概要</a><a href="#forecasts">原予測</a><a href="#research">企業調査</a><a href="#status">運用状況</a><Link href="/portfolio">口座・保有</Link><Link href="/settings">比較の設定</Link></nav>
    <section id="overview" className="hero">
      <div className="eyebrow">DAILY BRIEF / 日次版</div>
      <h1>判断の前に、<br/>予測と根拠を確認。</h1>
      <p className="intro">20日予測を軸に、5日予測を補足として確認します。調査結果は原予測と分けて保存します。</p>
      <div className="status-line"><span className={`status-pill ${forecasts.length ? "blue" : "amber"}`}>{storageError ? "保存先の確認が必要" : forecasts.length ? (stale ? "過去の原予測" : "原予測を保存済み") : "評価・接続の準備中"}</span><span>{payload?.mode === "owner_approved" ? "本人の採用確認済み" : payload?.mode === "paper" ? "ペーパー記録" : "研究モード"}</span></div>
    </section>
    <section className="metrics" aria-label="更新状況"><div><span>データ時点</span><strong>{fmtTime(payload?.data_as_of ?? null)}</strong></div><div><span>結果の生成</span><strong>{fmtTime(payload?.generated_at ?? null)}</strong></div><div><span>クラウド保存</span><strong>{fmtTime(receivedAt)}</strong></div></section>
    <section className="portfolio-link"><div><strong>口座・保有をアプリで入力</strong><p>「保有なし」から始められます。あとから追加・修正できます。</p></div><Link className="secondary-button" href="/portfolio">入力画面へ →</Link></section>
    {stale && payload?.kind === "predictions" && <aside className="notice" role="status">当日更新を確認できていません。保存済みの過去の原予測です。現在の売買判断として扱わないでください。</aside>}
    <section id="forecasts" className="panel"><div className="section-heading"><div className="section-number">01</div><div><h2>モデルの原予測</h2><p>候補上位20銘柄とすべての保有銘柄。1日予測は未提供です。</p></div></div>
      {!forecasts.length ? <div className="empty"><span className="empty-symbol">—</span><h3>まだ原予測はありません</h3><p>評価とモデルの確定後、PCで計算した日次結果がここに保存されます。保存後はPCが停止中でも確認できます。</p></div> : <div className="forecast-grid">{forecasts.map(item => <article className="forecast" key={item.symbol}><header><h3>{item.symbol}</h3><span>{item.holding ? "保有" : "候補"}</span></header><div className="primary-value"><span>20日予測</span><strong className={item.expected_return_20d >= 0 ? "positive" : "negative"}>{percent(item.expected_return_20d)}</strong></div><dl><div><dt>5日予測</dt><dd>{percent(item.expected_return_5d)}</dd></div><div><dt>1日予測</dt><dd>未提供</dd></div><div><dt>20日下振れ（{((payload?.downside_quantile_alpha ?? 0) * 100).toFixed(0)}%分位）</dt><dd>{percent(item.downside_quantile)}</dd></div><div><dt>20日で{percent(payload?.large_loss_threshold ?? 0)}以下の確率</dt><dd>{(item.large_loss_probability * 100).toFixed(1)}%</dd></div></dl></article>)}</div>}
      <p className="footnote">日次の調整後終値による研究用予測です。12:30の約定価格や利益を保証する値ではありません。順位は購入指示ではありません。</p>
    </section>
    <section id="research" className="panel"><div className="section-heading"><div className="section-number">02</div><div><h2>企業調査</h2><p>同じ7項目を確認し、「支持・注意・保留」を記録します。</p></div></div>
      <div className="criteria">{criterionLabels.map((label, i) => <span key={label}><b>{i + 1}</b>{label}</span>)}</div>
      {!payload?.research.length ? <p className="muted">調査記録はまだ同期されていません。未調査を好材料として扱いません。</p> : payload.research.map(item => <details className="research" key={item.research_id}><summary><strong>{item.symbol}</strong><span>{assessment[item.conclusion]}</span><small>{fmtTime(item.reviewed_at)}</small></summary>{item.findings.map((finding, i) => <div className="finding" key={finding.criterion}><h3>{criterionLabels[i]} <span>{assessment[finding.assessment]}</span></h3><p>{finding.note}</p>{finding.sources.map(source => <a key={source.url} href={source.url} target="_blank" rel="noreferrer noopener">{source.title} ↗</a>)}</div>)}</details>)}
    </section>
    <section id="status" className="panel"><div className="section-heading"><div className="section-number">03</div><div><h2>運用状況</h2><p>学習完了と、実用に向けた評価・採用を分けて確認します。</p></div></div>
      <div className="training"><span>候補モデルの学習</span><strong>{payload ? `${payload.training_completed} / ${payload.training_total}` : "未同期"}</strong></div>
      {payload && <progress aria-label="候補モデルの学習完了数" value={payload.training_completed} max={payload.training_total}/>}
      <h3>残っている条件</h3><ul className="blockers">{(payload ? (payload.blockers.length ? payload.blockers : ["保存された評価条件に未解決項目はありません。本人の採用判断と更新日時を確認してください。"]) : ["最新の評価・採用状況をPCから同期してください。"]).map(item => <li key={item}>{item}</li>)}</ul>
      <div className="provenance"><span>モデル版: {payload?.model_version ?? "未確定"}</span><span>特徴量版: {payload?.feature_version ?? "未確定"}</span></div>
      <p className="muted">資金・保有・税・取引コスト・リスク設定の確認前は、個人向けの推奨株数を出しません。モデル採用は評価結果を確認した本人が決定します。</p>
    </section>
    <footer><span>株AI · 本人専用の日次リサーチ<br/>実注文の送信機能はありません。</span><a href={chatGPTSignOutPath("/")} target="_top">サインアウト</a></footer>
  </main>;
}
