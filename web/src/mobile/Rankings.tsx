import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { PageHeader, StatePanel, TabBar, dateTime } from "../components";
import { useApiData } from "../hooks";
import { ConsultationReport, type ConsultationFindings } from "../ConsultationReport";
import { ReferenceAnalysis } from "./ReferenceAnalysis";

interface Ranked { symbol: string; companyName?: string; modelRank: number; score: number | null; expectedReturn: number | null }
interface Answer { order: { symbol: string; reason: string }[]; savedAt: string; researchId?: string; research?: ConsultationFindings }
interface Ranking { id: string; generatedAt: string; asOf: string; priceDate: string | null; rows: Ranked[]; total: number; answer: Answer | null; savedInput?: Exported | null; research?: Answer | null; holdingSymbols?: string[]; metrics?: Record<string, { return5d: number | null; return20d: number | null; rank20d: number | null }> }
interface Exported { id: string; rankingId?: string; prompt: string; expiresAt: string; canCopy?: boolean; responseMode?: string }

export function Rankings() {
  const [horizon, setHorizon] = useState("5d");
  return <div className="page"><PageHeader eyebrow="保存した最新の結果" title="ランキング" />
    <div className="screen-ranking"><p className="ranking-caption muted">数値モデル</p><div className="ranking-period" role="group" aria-label="ランキングモデル">{[["5d","5日","値予測"],["20d-value","20日","値予測"],["20d","20日","ランキング"]].map(([id,period,label])=><button key={id} className={horizon===id ? "active" : ""} aria-label={`${period}・${label}`} aria-pressed={horizon===id} onClick={()=>setHorizon(id)}>{period}<br />{label}</button>)}</div>
    <div id="saved-ranking"><RankingBody horizon={horizon} /></div></div>
  </div>;
}

function RankingBody({ horizon }: { horizon: string }) {
  const valueOnly = horizon !== "20d";
  const path = `/api/v1/mobile/ranking/${horizon === "20d-value" ? "20d" : horizon}`;
  const { data, error, loading, reload } = useApiData<Ranking>(path);
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("model");
  const [heldOnly, setHeldOnly] = useState(false);
  const [consulting, setConsulting] = useState(false);
  const [legacy,setLegacy]=useState(false);
  const [privateUse, setPrivateUse] = useState(false);
  const [entitled, setEntitled] = useState(false);
  const [prepared, setExported] = useState<Exported | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function run(action: () => Promise<void>) {
    setBusy(true); setMessage("");
    try { await action(); } catch (e) { setMessage(e instanceof Error ? e.message : "処理を完了できませんでした。"); }
    finally { setBusy(false); }
  }
  const exported = prepared ?? data?.savedInput;
  const research = data?.research;
  const adjusted = legacy && horizon === "20d" && source === "chatgpt" && data?.answer;
  const rows = useMemo(() => {
    const result = adjusted ? data!.answer!.order.map(item => ({ ...data!.rows.find(row => row.symbol === item.symbol)!, reason: item.reason })) : (data?.rows ?? []).map(row => ({ ...row, reason: "" }));
    const metric = (row: Ranked): number | null => valueOnly ? row.expectedReturn : data?.metrics?.[row.symbol]?.rank20d ?? null;
    if (!adjusted) result.sort((a, b) => (metric(a) === null ? 1 : 0) - (metric(b) === null ? 1 : 0) || (metric(b) ?? 0) - (metric(a) ?? 0) || a.symbol.localeCompare(b.symbol));
    return result.map((row, index) => ({ ...row, rank: adjusted || metric(row) !== null ? `${index + 1}位` : "—" }));
  }, [adjusted, data, valueOnly]);
  const held = useMemo(() => new Set(data?.holdingSymbols ?? []), [data?.holdingSymbols]);
  const query = search.trim().toLowerCase();
  const visible = rows.filter(row => (!heldOnly || held.has(row.symbol)) && `${row.symbol}${row.companyName ?? ""}`.toLowerCase().includes(query));
  const percent = (value: number | null | undefined) => value == null ? "未算出" : `${value > 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
  return <>
    {loading && <p role="status">{data ? "保存済みの順位を表示中・更新を確認しています…" : "ランキングを読み込んでいます…"}</p>}
    {error && <StatePanel tone="error" title="ランキングを読み込めません" detail={error} />}
    {data && !error && <>
      {legacy && horizon === "20d" && data.answer && <TabBar label="保存済み順位の種類" options={[["chatgpt", "保存済みChatGPT"], ["model", "モデル"]]} value={source} onChange={setSource} panelId="ranking-source" />}
      <div id="ranking-source" role={legacy && !valueOnly && data.answer ? "tabpanel" : undefined} aria-labelledby={legacy && !valueOnly && data.answer ? `ranking-source-${source}` : undefined}>
        <p className="sr-only">{valueOnly ? `${horizon==="5d" ? "5" : "20"}日の予測リターンが高い順` : adjusted ? "ChatGPTの回答を反映した順位" : "モデルの予測順位"}</p>
        <form className="ranking-search-row" onSubmit={e=>{e.preventDefault();(e.currentTarget.querySelector("input") as HTMLInputElement)?.blur();}}><input className="ranking-search" aria-label="銘柄名・コードで検索" type="search" placeholder="銘柄名・コードで検索" value={search} onChange={e => setSearch(e.target.value)} /><button className="button secondary" type="submit">検索</button></form>
        <div className="ranking-filter"><label><input type="checkbox" checked={heldOnly} onChange={e => setHeldOnly(e.target.checked)} />保有銘柄のみ</label><span className="ranking-results-count">{visible.length} / {rows.length}銘柄</span></div>
        {!visible.length && <p>条件に一致する銘柄がありません。</p>}
        <div className="card ranking-table"><div className="ranking-table-head"><span>順位・銘柄</span><span className={horizon==="5d" || !valueOnly ? "is-period" : ""}>{valueOnly ? "5日値予測" : "順位スコア"}</span><span className={horizon==="20d-value" ? "is-period" : ""}>20日値予測</span></div>
        {visible.map(row => <Link to={`/stocks/${row.symbol}`} state={{ from: "/ranking" }} className="ranking-table-row" key={row.symbol}>
          <span className="ranking-company"><span className="ranking-position" aria-label={row.rank}>{row.rank.replace("位","")}</span><span><strong>{row.companyName || row.symbol}</strong>{row.companyName && <small>{row.symbol} {held.has(row.symbol) && <span className="ranking-held">保有</span>}</small>}{!row.companyName && held.has(row.symbol) && <small className="ranking-held">保有</small>}
            {adjusted && <small>モデル {row.modelRank}位</small>}{row.reason && <small>{row.reason}</small>}</span></span>
          <span className={`ranking-return ${horizon==="5d" || !valueOnly ? "is-period" : ""}`}>{valueOnly ? percent(data.metrics?.[row.symbol]?.return5d ?? (horizon === "5d" ? row.expectedReturn : null)) : data.metrics?.[row.symbol]?.rank20d?.toFixed(2) ?? "未算出"}</span>
          <span className={`ranking-return ${horizon==="20d-value" ? "is-period" : ""}`}>{percent(data.metrics?.[row.symbol]?.return20d ?? (horizon !== "5d" ? row.expectedReturn : null))}</span>
        </Link>)}</div><p className="small muted">{data.priceDate ? `${data.priceDate} 終値 · ` : ""}{dateTime(data.generatedAt, true)} 作成</p>
      </div>
      {horizon === "20d" && <><button className="button button--secondary" disabled={loading || busy || !rows.length} onClick={() => setConsulting(!consulting)}>ChatGPTと相談</button>{(data.savedInput || research || data.answer) && <button className="quiet-link" onClick={()=>{setLegacy(!legacy);setConsulting(true);}}>過去の相談記録</button>}</>}
    </>}
    {!loading && <ReferenceAnalysis hasSaved={!!data?.rows.length} disabled={busy} onSaved={() => { setExported(null); reload(); }} />}
    {horizon === "20d" && consulting && data && !error && <section className="section">
      <h2>ランキングを相談する</h2><p>上位20銘柄＋全保有を、市場の5日・20日見通しと一緒に相談します。相談文をコピーしてChatGPTへ貼り付け、分析はChatGPTの会話で読みます。アプリへの貼り戻しは不要です。</p>
      <label className="checkbox"><input type="checkbox" checked={privateUse} onChange={e => setPrivateUse(e.target.checked)} />本人用・非公開で使い、ChatGPTの学習利用をオフにしています</label>
      <label className="checkbox"><input type="checkbox" checked={entitled} onChange={e => setEntitled(e.target.checked)} />データの利用条件を確認しました</label>
      <button className="button button--primary" disabled={busy || loading || !privateUse || !entitled} onClick={() => void run(async () => {
        setExported(await apiPost<Exported>(`${path}/export`, { service: "manual_chatgpt", checked_at: new Date().toISOString(), personal_analysis_only: privateUse, training_disabled: privateUse, private_input: privateUse, private_output: privateUse, data_entitlement_confirmed: entitled }));
      })}>相談文を作る</button>
      {exported && (legacy || exported.responseMode==="chatgpt-readable-report-v1") && <>
        <textarea className="csv-input" aria-label="ChatGPTへの相談文" readOnly value={exported.prompt} />
        <button className="button button--secondary" disabled={busy || loading || exported.canCopy === false || exported.responseMode!=="chatgpt-readable-report-v1"} onClick={() => void run(async () => { const current = await apiGet<Ranking>(path); if (current?.id !== (exported.rankingId ?? exported.id) || current.savedInput?.prompt !== exported.prompt || current.savedInput?.canCopy === false || current.savedInput?.responseMode!=="chatgpt-readable-report-v1") throw new Error("ランキングか送信許可が更新されています。相談文を作り直してください。"); await navigator.clipboard.writeText(exported.prompt); setMessage("コピーしました。ChatGPTに貼り付けて相談してください。"); })}>相談文をコピー</button>
        <a className="button button--secondary" href="https://chatgpt.com/" target="_blank" rel="noreferrer">ChatGPTを開く</a>
      </>}
    </section>}
    {legacy && horizon === "20d" && research?.researchId && <section className="section">
      <h2>保存した調査結果</h2>
      <p className="setting-footnote">保存 {dateTime(research.savedAt)} JST</p>
      {research.research && <ConsultationReport value={research.research} />}
      <p className="small muted">保存済みの記録・閲覧用</p>
    </section>}
    {message && <p role="status">{message}</p>}
  </>;
}
