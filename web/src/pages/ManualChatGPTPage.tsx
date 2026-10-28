import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { PageHeader, StatePanel, dateTime } from "../components";
import { isAndroid } from "../mobile/native";
import { ConsultationReport, type ConsultationFindings } from "../ConsultationReport";
import { useApiData } from "../hooks";

interface Review {
  lines: { symbol: string; account: string; current_shares: number; target_shares: number; share_difference: number }[];
  estimated_cost_yen: string;
  estimated_cash_after: Record<string, string>;
  applied_to_ledger: false;
  answer?: { evidence_as_of: string; targets: { symbol: string; account: string; reason: string; sources: string[] }[]; unknowns: string[] };
}
interface ConsultationContext {prediction_as_of:string;securities:{symbol:string;shares:number|null;"5d":{rank:number|null;expected_return:number|null};"20d":{rank:number|null;expected_return:number|null}}[]}
interface SavedResearch { record_id: string; saved_at: string; original_json: string; answer?: { research?: ConsultationFindings };consultation?:ConsultationContext|null }
interface ManualStatus { ready: boolean; reason: string | null; selected_input: string | null; saved_input?: Exported | null; saved_input_reason?: string | null; answers: Review[]; account_labels?: Record<string, string>; research?: SavedResearch[];current_context?:ConsultationContext|null;current_shares?:Record<string,number> }
interface Exported { input_record_id: string; input_snapshot_id: string; expires_at: string; prompt: string; response_mode?: string }

export function ManualChatGPTPage(): ReactNode {
  const location=useLocation();
  const historyOnly = location.pathname.endsWith("/history");
  const [historyIndex, setHistoryIndex] = useState(0);
  const [historyKind,setHistoryKind]=useState("research");
  const [status, setStatus] = useState<ManualStatus | null>(null);
  const [privateUse, setPrivateUse] = useState(false);
  const [entitled, setEntitled] = useState(false);
  const [exported, setExported] = useState<Exported | null>(null);
  const [showPrompt,setShowPrompt]=useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const android = isAndroid();
  const ranking=useApiData<{asOf:string;rows:{symbol:string;companyName?:string;modelRank:number;expectedReturn:number|null}[];holdingSymbols?:string[];metrics?:Record<string,{return5d:number|null;return20d:number|null;rank20d:number|null}>}>("/api/v1/mobile/ranking/20d", { enabled: android && !historyOnly && status !== null });
  const percentage=(value:number|null|undefined)=>value==null ? "未算出" : `${value>0 ? "+" : ""}${(value*100).toFixed(1)}%`;
  const targets=status?.current_context?.securities ?? ranking.data?.rows?.map(row=>({symbol:row.symbol,shares:status?.current_shares?.[row.symbol] ?? null,"5d":{rank:null,expected_return:ranking.data?.metrics?.[row.symbol]?.return5d ?? null},"20d":{rank:null,expected_return:ranking.data?.metrics?.[row.symbol]?.return20d ?? row.expectedReturn}})) ?? [];
  const researchHistory=status?.research ?? [];
  const showResearch=researchHistory.length>0 && (historyKind === "research" || !status?.answers.length);
  useEffect(() => {
    if (!android) return;
    let active = true;
    void apiGet<ManualStatus>("/api/v1/mobile/chatgpt-manual/status")
      .then(value => {
        if (!active) return;
        setStatus(value);
        if (value.saved_input && value.saved_input.response_mode==="chatgpt-readable-report-v2") {
          setExported(value.saved_input);
          setShowPrompt(true);
          setMessage("保存済みの入力を再表示しました。有効期限と内容を確認して相談を続けられます。");
        } else {
          setExported(null);setShowPrompt(false);
        }
      })
      .catch(() => { if (active) setError("保存済み入力を確認できません。アプリを開き直してください。"); });
    return () => { active = false; };
  }, [android]);

  async function prepare(): Promise<void> {
    setBusy(true); setError(""); setMessage("");
    try {
      const prepared = await apiPost<Exported>("/api/v1/mobile/chatgpt-manual/export", {
        service: "manual_chatgpt", checked_at: new Date().toISOString(),
        personal_analysis_only: privateUse, training_disabled: privateUse,
        private_input: privateUse, private_output: privateUse, data_entitlement_confirmed: entitled,
      });
      if (prepared.response_mode!=="chatgpt-readable-report-v2") throw new Error("相談文を新しい形式で作り直してください。");
      setExported(prepared);
      setShowPrompt(true);
      setStatus(previous => previous && { ...previous, selected_input: prepared.input_record_id, saved_input: prepared, saved_input_reason: null });
      try {await navigator.clipboard.writeText(prepared.prompt);setMessage("相談文を作成・コピーしました。ChatGPTに貼り付けてください。");}
      catch {setMessage("入力を保存しました。「プロンプトをコピー」または文章の選択でコピーしてください。");}
    } catch (reason) { setError(reason instanceof Error ? reason.message : "入力を作成できませんでした。"); }
    finally { setBusy(false); }
  }
  async function copy(): Promise<void> {
    if (!exported) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const latest = await apiGet<ManualStatus>("/api/v1/mobile/chatgpt-manual/status");
      if (!latest.ready || !latest.saved_input || latest.saved_input.response_mode!=="chatgpt-readable-report-v2"
        || latest.saved_input.input_record_id !== exported.input_record_id
        || latest.saved_input.input_snapshot_id !== exported.input_snapshot_id
        || latest.saved_input.prompt !== exported.prompt) {
        setError(latest.reason ?? latest.saved_input_reason ?? "入力が更新されています。最新の照合後に入力を作り直してください。");
        return;
      }
      try { await navigator.clipboard.writeText(exported.prompt); setMessage("プロンプトをコピーしました。"); }
      catch { setError("コピーできません。入力欄の文章を選択してコピーしてください。"); }
    } catch { setError("最新の入力と送信許可を確認できず、コピーを中止しました。"); }
    finally { setBusy(false); }
  }
  return <div className="page manual-chatgpt">
    <PageHeader title={historyOnly ? "相談履歴" : "ChatGPTと相談"} backTo="/today" />
    {historyOnly && <><Link className="quiet-link" to="/today/chatgpt">新しい相談</Link><a className="button secondary" href="https://chatgpt.com/" target="_blank" rel="noreferrer">ChatGPTの会話履歴を開く</a></>}
    <div className="subscreen stack" hidden={historyOnly}>
    {!android ? <StatePanel title="Androidアプリで利用できます" detail="端末に保存した最新の原予測・口座・設定を使います。" />
      : !status ? <StatePanel title="保存済み入力を確認しています" />
      : <>
        {<section className="card"><p>相談文をコピーし、ChatGPTに貼り付けて送信してください。分析はChatGPTの会話で読み、そのまま質問を続けられます。アプリへの貼り戻しは不要です。</p></section>}
        {!status.ready && <StatePanel title="最新条件の照合が必要です" detail={status.reason ?? "最新の原予測・口座・設定を確認してから相談文を作成してください。"} />}
        <section className="card">
          <h3 className="section-title">利用条件</h3>
          <label className="row"><input type="checkbox" checked={privateUse && entitled} disabled={busy}
            onChange={event => {setPrivateUse(event.target.checked);setEntitled(event.target.checked);}} />本人分析のみ・学習利用オフ・入力と結果は非公開。J-Quants契約の利用範囲を確認しました</label>
          <p className="subhint">
            <a href="https://jpx-jquants.com/ja/help/usage" target="_blank" rel="noreferrer">J-Quantsの利用条件</a></p>
        </section><section className="card"><h3 className="section-title">対象 {targets.length}銘柄</h3><p className="small">上位20銘柄＋全保有 · {dateTime(status?.current_context?.prediction_as_of ?? ranking.data?.asOf,true)} 時点</p><div className="consultation-targets"><table className="subtable"><thead><tr><th>銘柄</th><th>保有</th><th>5日順位</th><th>20日順位</th><th>5日予測</th><th>20日予測</th></tr></thead><tbody>{targets.map(row=><tr key={row.symbol}><td><Link to={`/stocks/${row.symbol}`} state={{from:"/today/chatgpt"}}>{row.symbol} {ranking.data?.rows?.find(item=>item.symbol===row.symbol)?.companyName || ""}</Link></td><td>{row.shares ?? "未確認"}</td><td>{row["5d"].rank ?? "未算出"}</td><td>{row["20d"].rank ?? "未算出"}</td><td>{percentage(row["5d"].expected_return)}</td><td>{percentage(row["20d"].expected_return)}</td></tr>)}</tbody></table></div>{!targets.length && <p className="small muted">{ranking.loading ? "相談対象を確認しています…" : "相談対象を確認できません。最新の原予測を確認してください。"}</p>}</section>
        <section className="card stack"><h3 className="section-title">相談文</h3>
          <div className="button-stack"><button className="button button--primary" disabled={busy || !status.ready || !privateUse || !entitled}
            onClick={() => void prepare()}>作成・コピー</button><button className="button secondary" disabled={!exported} onClick={()=>setShowPrompt(true)}>内容を表示</button></div>
          {status.saved_input_reason && <p className="setting-footnote">{status.saved_input_reason}</p>}
          {exported && showPrompt && exported.response_mode==="chatgpt-readable-report-v2" && <>
            <p>入力の有効期限：{dateTime(exported.expires_at)}</p>
            <textarea className="csv-input" aria-label="ChatGPTへ渡す入力" readOnly value={exported.prompt} />
            <div className="button-stack"><button className="button button--secondary" disabled={busy} onClick={() => void copy()}>プロンプトをコピー</button></div>
          </>}
          <a className="button secondary" href="https://chatgpt.com/" target="_blank" rel="noreferrer">ChatGPTを開く</a>
        </section>

      </>}
    {message && <p role="status">{message}</p>}
    {error && <StatePanel tone="error" title="処理を完了できません" detail={error} />}

    </div>
    {!historyOnly && <Link className="quiet-link" to="/today/chatgpt/history">過去の相談記録</Link>}
    {historyOnly && !status?.answers.length && !researchHistory.length && <StatePanel title={status ? "保存した相談はまだありません" : "相談履歴を確認しています"} detail={error || undefined} />}
    {historyOnly && status && (!!status.answers.length || !!researchHistory.length) && <section className="subscreen stack"><div className="card"><h3 className="section-title">保存した相談</h3>
      <label>保存日時<select className="history-select" value={`${showResearch ? "research" : "answer"}:${historyIndex}`} onChange={e => {const [kind,index]=e.target.value.split(":");setHistoryKind(kind);setHistoryIndex(Number(index));}}>{researchHistory.map((item,i)=><option key={item.record_id} value={`research:${i}`}>{dateTime(item.saved_at,true)} · 調査結果</option>)}{status.answers.map((item, i) => <option key={`answer-${i}`} value={`answer:${i}`}>{item.answer ? dateTime(item.answer.evidence_as_of) : `保存済み提案 ${i + 1}`} · 検算済み</option>)}</select></label>
      </div>{showResearch && researchHistory.slice(historyIndex,historyIndex+1).map(item=><section className="card" key={item.record_id}><h3 className="section-title">相談結果</h3><p className="subhint">保存 {dateTime(item.saved_at,true)}</p>{item.answer?.research ? <ConsultationReport value={item.answer.research} savedShares={Object.fromEntries(item.consultation?.securities.map(row=>[row.symbol,row.shares]) ?? [])} currentShares={status.current_shares} /> : <pre className="research-text">{item.original_json}</pre>}</section>)}
      {!showResearch && status.answers.slice(historyIndex, historyIndex + 1).map((item, i) => <section className="card" key={i}>
        <h3 className="plain-section-title">{item.answer ? dateTime(item.answer.evidence_as_of) : `保存済み提案 ${i + 1}`}</h3>
        <p>保存時の提案です。現在の保有状態ではありません。</p>
        {item.lines.map(line => <p key={`${line.symbol}-${line.account}`}>
          {line.symbol} / {line.account}：{line.current_shares}株 → {line.target_shares}株
        </p>)}
        {item.answer?.targets.map(target => <p key={`${target.symbol}-${target.account}`}>{target.reason}</p>)}
      </section>)}
    </section>}
  </div>;
}
