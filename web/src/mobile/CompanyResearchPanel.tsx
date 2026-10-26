import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiPost } from "../api";
import { dateTime } from "../components";
import type { StockDetail } from "../types";
import { ChatGPT, type ChatGPTStatus, type ResearchPass, type ResearchRunView } from "./chatgpt";
import { isAndroid } from "./native";
import { researchFailure, runResearch } from "./research";
import { ExternalPermissionPanel } from "./ExternalPermissionPanel";

const researchTime = (value: string | null): string => dateTime(value, true);

function Findings({ value }: { value: ResearchPass }) {
  return <div className="research-findings">
    <p className="research-text">{value.text}</p>
    <p className="research-sources">出典：{value.sources.map((source, index) => <span key={source.url}>
      {index > 0 && " ／ "}<a href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
      <small>{source.published_at ? `（公開 ${researchTime(source.published_at)} JST）` : "（公開日時未確認）"}</small>
    </span>)}</p>
    <small>調査完了 {researchTime(value.completed_at)} JST · {value.served_model}</small>
  </div>;
}

export function CompanyResearchPanel({
  symbol, forecast, runs = [], records = [], onChanged,
}: {
  symbol: string; forecast: StockDetail["forecast"];
  runs: StockDetail["researchRuns"]; records: StockDetail["chatgptResearch"];
  onChanged: () => void;
}) {
  const [status, setStatus] = useState<ChatGPTStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [local, setLocal] = useState<ResearchRunView | null>(null);
  const [historyId,setHistoryId]=useState("");
  const android = isAndroid();
  useEffect(() => {
    if (!android) return;
    let active = true;
    void ChatGPT.getStatus().then(value => { if (active) setStatus(value); })
      .catch(() => { if (active) setMessage("ChatGPTの連携状態は設定画面で確認してください。"); });
    return () => { active = false; };
  }, [android]);
  const allRuns = [...runs.filter(item => item.run.run_id !== local?.run.run_id), ...(local ? [local] : [])]
    .sort((a, b) => a.run.context.revision - b.run.context.revision);
  const running = allRuns.find(item => item.attempts.some(attempt => attempt.status === "running"));
  const selection = status?.selection;
  const matching = allRuns.filter(item => item.run.context.configuration.model === selection?.model
    && item.run.context.configuration.effort === selection?.effort).at(-1);
  const current = running ?? matching ?? allRuns.at(-1);
  const lastAttempt = current?.attempts.at(-1);
  const savedRecords = [...records, ...allRuns.flatMap(item => item.record ? [item.record] : [])];
  const latestRecord = savedRecords.find(record=>record.research_id === historyId) ?? allRuns.find(item=>item.run.run_id === historyId)?.record ?? matching?.record ?? savedRecords.sort((a, b) => Date.parse(a.comparison.completed_at) - Date.parse(b.comparison.completed_at)).at(-1);
  const partial = current?.record ? null : current?.passes.find(item => item.phase === "independent");
  const enabled = android && !!status?.planEnabled && !!selection?.model && !!forecast?.researchEligible
    && !forecast.isStale;

  async function perform(rerun = false) {
    if (!forecast) return;
    setBusy(true); setMessage("");
    try {
      let view = running;
      if (!view) {
        const actual = await ChatGPT.getStatus(); setStatus(actual);
        if (!actual.planEnabled || !actual.selection.model) throw new Error("設定画面でChatGPTと調査モデルを連携してください。");
        view = await apiPost<ResearchRunView>(`/api/v1/research/${forecast.snapshotId}/${symbol}/start`, {
          configuration: actual.selection,
          ...(rerun && matching ? { rerun_previous_id: matching.run.run_id } : {}),
        });
      }
      setLocal(view);
      const attempt = view.attempts.at(-1);
      const saved = await runResearch(view.run.run_id, {
        retry: !rerun && (attempt?.status === "failed" || attempt?.status === "interrupted"),
        progress: setMessage,
      });
      setLocal(saved); setMessage("独立調査と数値予測との照合を保存しました。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "調査を完了できませんでした。実行状況を確認してください。");
    } finally { setBusy(false); onChanged(); }
  }

  return <section className="section company-research" aria-labelledby="company-research-title">
    <div className="section-title"><div><span>COMPANY RESEARCH</span><h2 id="company-research-title">ChatGPTの見解</h2></div></div>
    {(allRuns.length>0 || savedRecords.length>0) && <label>調査日時<select value={historyId} onChange={e=>setHistoryId(e.target.value)}><option value="">現在の設定の最新結果</option>{allRuns.map(item=><option key={item.run.run_id} value={item.run.run_id}>第{item.run.context.revision}回 · {researchTime(item.run.context.research_as_of)} · {item.record ? "保存済み" : "未完了"}</option>)}{records.filter(record=>!allRuns.some(item=>item.record?.research_id === record.research_id)).map(record=><option key={record.research_id} value={record.research_id}>{researchTime(record.comparison.completed_at)} · 保存済み</option>)}</select></label>}
    <p className="explain">市場全体→企業調査→数値予測→全保有と候補の比較、の順に調べます。元の予測と台帳は変更しません。</p>
    {!forecast ? <p>照合する数値予測はまだありません。</p> : <>
      <p className="research-status">{running ? "調査実行中" : lastAttempt?.status === "failed" || lastAttempt?.status === "interrupted"
        ? "調査未完了" : current?.record || (!current && latestRecord) ? "調査と照合を保存済み" : partial ? "独立調査を保存済み・照合待ち" : "未調査"}</p>
      {lastAttempt?.error_code && <p className="explain">{researchFailure(lastAttempt.error_code)}</p>}
      {forecast.isStale && <p className="explain">過去の数値予測です。最新の予測を保存してから調査してください。</p>}
      {current && <small className="research-meta">調査設定 {current.run.context.configuration.model} · {current.run.context.configuration.effort}
        <br />調査対象時点 {researchTime(current.run.context.research_as_of)} JST</small>}
      {android && (!matching?.record || !!running) && <div className="research-actions">
        <button className="button button--primary" disabled={busy || (!running && !enabled)} onClick={() => void perform()}>
          {busy ? "調査を処理しています…" : running ? "実行状況を確認" : lastAttempt?.status === "failed" || lastAttempt?.status === "interrupted" ? "中断した段階を再試行" : partial ? "照合の続きを実行" : "ChatGPTで調査"}
        </button>
        {!status?.planEnabled || !selection?.model ? <Link className="button button--secondary" to="/settings">ChatGPTの連携設定</Link> : null}
      </div>}
      <p role="status" className="research-message">{message}</p>
      {android && <p className="setting-footnote">調査はChatGPTの利用枠を使います。同じ条件の保存済み結果は再利用します。</p>}
      {android && <ExternalPermissionPanel />}
    </>}
    {latestRecord && <>
      <p className="research-preview">{latestRecord.comparison.text.replace(/\s+/g, " ").slice(0, 180)}{latestRecord.comparison.text.length > 180 ? "…" : ""}</p>
      <section className="research-disclosure"><h3 className="plain-section-title">照合結果と出典を見る</h3><Findings value={latestRecord.comparison} /></section>
      <section className="research-disclosure"><h3 className="plain-section-title">数値予測を見る前の独立調査</h3><Findings value={latestRecord.independent} /></section>
    </>}
    {partial && <section className="research-disclosure"><h3 className="plain-section-title">保存済みの独立調査</h3><Findings value={partial} /></section>}
    {(allRuns.length > 0 || latestRecord) && <section className="research-disclosure">
      <h3 className="plain-section-title">調査履歴・再調査</h3>
      {allRuns.filter(item=>item.run.run_id === (historyId || allRuns.at(-1)?.run.run_id)).map(item => <section className="research-history" key={item.run.run_id}>
        <h3 className="plain-section-title">第{item.run.context.revision}回 · {researchTime(item.run.context.research_as_of)} JST<br />
          {item.run.context.configuration.model} · {item.run.context.configuration.effort} · {item.record ? "調査・照合済み" : "未完了"}</h3>
        {item.passes.map(value => <div key={value.pass_id}>
          <h3>{value.phase === "independent" ? "独立調査" : "数値予測との照合"}</h3><Findings value={value} />
        </div>)}
        {item.attempts.filter(attempt => attempt.error_code).map(attempt => <p key={attempt.attempt_id}>{researchTime(attempt.finished_at)} JST · {researchFailure(attempt.error_code)}</p>)}
      </section>)}
      {android && matching?.record && <div className="research-actions"><button className="button button--secondary" disabled={busy || !!running || !enabled}
        onClick={() => void perform(true)}>この設定で新たに再調査</button><p className="setting-footnote">利用枠を使って調べ直し、前の結果も残します。</p></div>}
    </section>}
  </section>;
}
