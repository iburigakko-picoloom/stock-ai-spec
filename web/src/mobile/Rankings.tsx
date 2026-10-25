import { useState } from "react";
import { apiGet, apiPost } from "../api";
import { PageHeader, StatePanel, TabBar, dateTime } from "../components";
import { useApiData } from "../hooks";
import { ReferenceAnalysis } from "./ReferenceAnalysis";

interface Ranked { symbol: string; companyName?: string; modelRank: number; score: number | null; expectedReturn: number | null }
interface Answer { order: { symbol: string; reason: string }[]; savedAt: string }
interface Ranking { id: string; generatedAt: string; asOf: string; priceDate: string | null; rows: Ranked[]; total: number; answer: Answer | null; savedInput?: Exported | null }
interface Exported { id: string; prompt: string; expiresAt: string }

export function Rankings() {
  const [horizon, setHorizon] = useState("20d");
  return <div className="page"><PageHeader eyebrow="保存した最新の結果" title="ランキング" />
    <TabBar label="ランキング期間" options={[["overall", "総合"], ["5d", "5日"], ["20d", "20日"], ["morning", "前場"]]} value={horizon} onChange={setHorizon} panelId="saved-ranking" />
    <div id="saved-ranking" role="tabpanel" aria-labelledby={`saved-ranking-${horizon}`}>{horizon === "overall" || horizon === "morning" ? <StatePanel title={`${horizon === "overall" ? "総合" : "前場"}ランキングは未導入です`} detail="現在は20日ランキングを利用できます。" /> : <RankingBody key={horizon} horizon={horizon} />}</div>
  </div>;
}

function RankingBody({ horizon }: { horizon: string }) {
  const path = `/api/v1/mobile/ranking/${horizon}`;
  const { data, error, loading, reload } = useApiData<Ranking>(path);
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("chatgpt");
  const [consulting, setConsulting] = useState(false);
  const [privateUse, setPrivateUse] = useState(false);
  const [entitled, setEntitled] = useState(false);
  const [prepared, setExported] = useState<Exported | null>(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function run(action: () => Promise<void>) {
    setBusy(true); setMessage("");
    try { await action(); } catch (e) { setMessage(e instanceof Error ? e.message : "処理を完了できませんでした。"); }
    finally { setBusy(false); }
  }
  const exported = prepared ?? data?.savedInput;
  const adjusted = horizon === "20d" && source === "chatgpt" && data?.answer;
  const rows = adjusted ? data.answer!.order.map(item => ({ ...data.rows.find(row => row.symbol === item.symbol)!, reason: item.reason })) : (data?.rows ?? []).map(row => ({ ...row, reason: "" }));
  const visible = rows.map((row, index) => ({ ...row, rank: index + 1 })).filter(row => `${row.symbol}${row.companyName ?? ""}`.toLowerCase().includes(search.trim().toLowerCase()));
  return <>
    {loading && <p role="status">{data ? "保存済みの順位を表示中・更新を確認しています…" : "ランキングを読み込んでいます…"}</p>}
    {error && <StatePanel tone="error" title="ランキングを読み込めません" detail={error} />}
    {data && !error && <>
      <p className="setting-footnote">{data.priceDate ? `株価 ${data.priceDate}・` : ""}更新 {dateTime(data.generatedAt, true)} JST</p>
      {horizon === "20d" && data.answer && <TabBar label="順位の種類" options={[["chatgpt", "ChatGPT"], ["model", "モデル"]]} value={source} onChange={setSource} panelId="ranking-source" />}
      <div id="ranking-source" role={data.answer ? "tabpanel" : undefined} aria-labelledby={data.answer ? `ranking-source-${source}` : undefined}><p>{horizon === "5d" ? "5日の予測リターン（補助情報）" : adjusted ? "ChatGPTの回答を反映した順位" : "モデルの予測順位"}・上位{rows.length}件</p>
        <label className="search"><span className="sr-only">銘柄名・コードで検索</span><input type="search" placeholder="上位50件から検索" value={search} onChange={e => setSearch(e.target.value)} /></label>
        {search.trim() && !visible.length && <p>検索に一致する銘柄がありません。</p>}
        <div className="ranking-list">{visible.map(row => <div className="ranking-row saved-ranking-row" key={row.symbol}>
          <strong className="rank-number">{horizon === "20d" ? `${row.rank}位` : "5日"}</strong><div><strong>{row.companyName || row.symbol}</strong>{row.companyName && row.companyName !== row.symbol && <small>{row.symbol}</small>}
            {adjusted && <small>モデル {row.modelRank}位</small>}{row.reason && <p>{row.reason}</p>}</div>
          <span>{row.expectedReturn === null ? "—" : `${(row.expectedReturn * 100).toFixed(2)}%`}<small>予測リターン</small></span>
        </div>)}</div>
      </div>
      {horizon === "20d" && <button className="button button--secondary" disabled={loading || busy || !rows.length} onClick={() => setConsulting(!consulting)}>ChatGPTと相談</button>}
    </>}
    {!loading && <ReferenceAnalysis hasSaved={!!data?.rows.length} disabled={busy} onSaved={() => { setExported(null); setAnswer(""); reload(); }} />}
    {consulting && data && !error && <section className="section">
      <h2>ランキングを相談する</h2><p>ランキングの上位50件までをコピーして相談し、回答JSONを貼り付けると順位に反映します。</p>
      <label className="checkbox"><input type="checkbox" checked={privateUse} onChange={e => setPrivateUse(e.target.checked)} />本人用・非公開で使い、ChatGPTの学習利用をオフにしています</label>
      <label className="checkbox"><input type="checkbox" checked={entitled} onChange={e => setEntitled(e.target.checked)} />データの利用条件を確認しました</label>
      <button className="button button--primary" disabled={busy || loading || !privateUse || !entitled} onClick={() => void run(async () => {
        setExported(await apiPost<Exported>(`${path}/export`, { service: "manual_chatgpt", checked_at: new Date().toISOString(), personal_analysis_only: privateUse, training_disabled: privateUse, private_input: privateUse, private_output: privateUse, data_entitlement_confirmed: entitled }));
      })}>相談文を作る</button>
      {exported && exported.id === data.id && <>
        <textarea className="csv-input" aria-label="ChatGPTへの相談文" readOnly value={exported.prompt} />
        <button className="button button--secondary" disabled={busy || loading} onClick={() => void run(async () => { const current = await apiGet<Ranking>(path); if (current?.id !== exported.id || current.savedInput?.prompt !== exported.prompt) throw new Error("ランキングか相談入力が更新されています。相談文を作り直してください。"); await navigator.clipboard.writeText(exported.prompt); setMessage("コピーしました。ChatGPTに貼り付けて相談してください。"); })}>相談文をコピー</button>
        <a className="button button--secondary" href="https://chatgpt.com/" target="_blank" rel="noreferrer">ChatGPTを開く</a>
        <label>回答JSON<textarea className="csv-input" value={answer} onChange={e => setAnswer(e.target.value)} /></label>
        <button className="button button--primary" disabled={busy || loading || !answer.trim()} onClick={() => void run(async () => {
          await apiPost(`${path}/answer`, { id: exported.id, answer }); setSource("chatgpt"); reload(); setMessage("回答をランキングに反映しました。");
        })}>回答をランキングに反映</button>
      </>}
    </section>}
    {message && <p role="status">{message}</p>}
  </>;
}
