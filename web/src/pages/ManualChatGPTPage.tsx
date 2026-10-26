import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { PageHeader, StatePanel, dateTime } from "../components";
import { isAndroid } from "../mobile/native";
import { ConsultationReport, type ConsultationFindings } from "../ConsultationReport";

interface Review {
  lines: { symbol: string; account: string; current_shares: number; target_shares: number; share_difference: number }[];
  estimated_cost_yen: string;
  estimated_cash_after: Record<string, string>;
  applied_to_ledger: false;
  answer?: { evidence_as_of: string; targets: { symbol: string; account: string; reason: string; sources: string[] }[]; unknowns: string[] };
}
interface SavedResearch { record_id: string; saved_at: string; original_json: string; answer?: { research?: ConsultationFindings } }
interface ManualStatus { ready: boolean; reason: string | null; selected_input: string | null; saved_input?: Exported | null; saved_input_reason?: string | null; answers: Review[]; account_labels?: Record<string, string>; research?: SavedResearch[] }
interface Exported { input_record_id: string; input_snapshot_id: string; expires_at: string; prompt: string }

export function ManualChatGPTPage(): ReactNode {
  const historyOnly = useLocation().pathname.endsWith("/history");
  const [historyIndex, setHistoryIndex] = useState(0);
  const [historyKind,setHistoryKind]=useState("research");
  const [status, setStatus] = useState<ManualStatus | null>(null);
  const [privateUse, setPrivateUse] = useState(false);
  const [entitled, setEntitled] = useState(false);
  const [exported, setExported] = useState<Exported | null>(null);
  const [answer, setAnswer] = useState("");
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [researchId, setResearchId] = useState<string | null>(null);
  const [findings, setFindings] = useState<ConsultationFindings | null>(null);
  const [error, setError] = useState("");
  const android = isAndroid();
  const researchHistory=status?.research ?? [];
  const showResearch=researchHistory.length>0 && (historyKind === "research" || !status?.answers.length);
  useEffect(() => {
    if (!android) return;
    let active = true;
    void apiGet<ManualStatus>("/api/v1/mobile/chatgpt-manual/status")
      .then(value => {
        if (!active) return;
        setStatus(value);
        setResearchId(value.research?.[0]?.record_id ?? null);
        setFindings(value.research?.[0]?.answer?.research ?? null);
        if (value.saved_input) {
          setExported(value.saved_input);
          setMessage("保存済みの入力を再表示しました。有効期限と内容を確認して相談を続けられます。");
        }
      })
      .catch(() => { if (active) setError("保存済み入力を確認できません。アプリを開き直してください。"); });
    return () => { active = false; };
  }, [android]);

  async function prepare(): Promise<void> {
    setBusy(true); setError(""); setMessage(""); setReview(null);
    try {
      const prepared = await apiPost<Exported>("/api/v1/mobile/chatgpt-manual/export", {
        service: "manual_chatgpt", checked_at: new Date().toISOString(),
        personal_analysis_only: privateUse, training_disabled: privateUse,
        private_input: privateUse, private_output: privateUse, data_entitlement_confirmed: entitled,
      });
      setExported(prepared);
      setStatus(previous => previous && { ...previous, selected_input: prepared.input_record_id, saved_input: prepared, saved_input_reason: null });
      setMessage("入力を保存しました。ChatGPTへコピーし、回答JSONを下へ貼り付けてください。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "入力を作成できませんでした。"); }
    finally { setBusy(false); }
  }
  async function copy(): Promise<void> {
    if (!exported) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const latest = await apiGet<ManualStatus>("/api/v1/mobile/chatgpt-manual/status");
      if (!latest.ready || !latest.saved_input
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
  async function importAnswer(): Promise<void> {
    setBusy(true); setError(""); setMessage(""); setReview(null);
    try {
      const saved = await apiPost<{ research_record_id: string; answer?: { research?: ConsultationFindings } }>("/api/v1/mobile/chatgpt-manual/research", {
        input_record_id: exported?.input_record_id ?? status?.selected_input, answer_json: answer,
      });
      setResearchId(saved.research_record_id);
      setFindings(saved.answer?.research ?? null);
      setMessage("調査結果を保存しました。最新の条件で検算できます。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "回答を検証できませんでした。"); }
    finally { setBusy(false); }
  }
  return <div className="page manual-chatgpt">
    <PageHeader title={historyOnly ? "相談履歴" : "ChatGPTと相談"} backTo="/today" />
    {historyOnly && <Link className="quiet-link" to="/today/chatgpt">新しい相談</Link>}
    <div hidden={historyOnly}>
    <p className="explain">上位20銘柄と全保有を渡して相談します。モデル・推論設定はChatGPT側で選びます。回答は提案として保存します。</p>
    {!android ? <StatePanel title="Androidアプリで利用できます" detail="端末に保存した最新の原予測・口座・設定を使います。" />
      : !status ? <StatePanel title="保存済み入力を確認しています" />
      : <>
        {!status.ready && <StatePanel title="最新条件の照合が必要です" detail={status.reason ?? "保存済みの相談への回答は受け取れます。"} />}
        <section className="section">
          <h2>利用条件</h2>
          <label className="checkbox"><input type="checkbox" checked={privateUse} disabled={busy}
            onChange={event => setPrivateUse(event.target.checked)} />本人の分析だけに使い、学習利用をオフ、会話と結果を非公開にしています</label>
          <label className="checkbox"><input type="checkbox" checked={entitled} disabled={busy}
            onChange={event => setEntitled(event.target.checked)} />使用するデータが現在のJ-Quants契約・取得範囲で利用できると確認しました</label>
          <p className="setting-footnote">共有link・結果の配信や公開・学習利用につながるfeedback送信は行わないでください。
            <a href="https://jpx-jquants.com/ja/help/usage" target="_blank" rel="noreferrer">J-Quantsの利用条件</a></p>
        </section><section className="section"><h2>相談文</h2>
          <div className="button-stack"><button className="button button--primary" disabled={busy || !status.ready || !privateUse || !entitled}
            onClick={() => void prepare()}>プロンプトを作成</button></div>
          {status.saved_input_reason && <p className="setting-footnote">{status.saved_input_reason}</p>}
          {exported && <>
            <p>入力の有効期限：{dateTime(exported.expires_at)}</p>
            <textarea className="csv-input" aria-label="ChatGPTへ渡す入力" readOnly value={exported.prompt} />
            <div className="button-stack"><button className="button button--secondary" disabled={busy} onClick={() => void copy()}>プロンプトをコピー</button></div>
          </>}
        </section>
        <section className="section">
          <h2>回答JSON</h2>
          <textarea className="csv-input" aria-label="ChatGPTの回答JSON" value={answer} disabled={busy}
            onChange={event => { setAnswer(event.target.value); setReview(null); }} placeholder="回答JSONをここに貼り付け" />
          <div className="button-stack"><button className="button button--primary" disabled={busy || !answer.trim() || !(exported || status.selected_input)}
            onClick={() => void importAnswer()}>調査結果を保存</button></div>
          {findings && <ConsultationReport value={findings} />}
          {researchId && <button className="button button--primary" disabled={busy} onClick={() => {
            setBusy(true); setError(""); setReview(null);
            void apiPost<{ review: Review }>("/api/v1/mobile/chatgpt-manual/review", { research_record_id: researchId })
              .then(value => { setReview(value.review); setMessage("最新の条件で株数・資金・費用を検算しました。台帳は変更していません。"); })
              .catch(reason => setError(`調査結果は保存済みです。${reason instanceof Error ? reason.message : "最新条件を照合してください。"}`))
              .finally(() => setBusy(false));
          }}>最新の条件で検算</button>}
        </section>
      </>}
    {message && <p role="status">{message}</p>}
    {error && <StatePanel tone="error" title="処理を完了できません" detail={error} />}
    {review && <section className="section"><h2>保存したChatGPT提案</h2>
      {review.lines.map(line => <div className="difference-row" key={`${line.symbol}-${line.account}`}>
        <span>{line.symbol} / {status?.account_labels?.[line.account] ?? line.account}</span><strong className="share-change"><span>{line.current_shares}株</span><span aria-hidden="true">→</span><span>{line.target_shares}株</span></strong>
      </div>)}
      <p>費用見込み {Number(review.estimated_cost_yen).toLocaleString("ja-JP")}円</p>
      <section><h3 className="plain-section-title">理由と根拠</h3>
        {review.answer?.targets.map(target => <p key={`${target.symbol}-${target.account}`}>
          {target.symbol} / {target.account}：{target.reason}
          {target.sources.map(url => <a key={url} href={url} target="_blank" rel="noreferrer"> 出典</a>)}
        </p>)}
        <p>未確認：{review.answer?.unknowns.join(" / ") || "回答に記載なし"}</p>
        {review.answer && <p>回答の申告時点：{dateTime(review.answer.evidence_as_of)}</p>}
      </section>
      <p>実注文はご本人が行い、実際の約定を確認した後に記録してください。</p>
    </section>}
    </div>
    {!historyOnly && <Link className="quiet-link" to="/today/chatgpt/history">相談履歴</Link>}
    {historyOnly && !status?.answers.length && !researchHistory.length && <StatePanel title={status ? "保存した相談はまだありません" : "相談履歴を確認しています"} detail={error || undefined} />}
    {historyOnly && status && (!!status.answers.length || !!researchHistory.length) && <section className="section"><h3 className="plain-section-title">保存した相談</h3>
      <label>保存日時<select className="history-select" value={`${showResearch ? "research" : "answer"}:${historyIndex}`} onChange={e => {const [kind,index]=e.target.value.split(":");setHistoryKind(kind);setHistoryIndex(Number(index));}}>{researchHistory.map((item,i)=><option key={item.record_id} value={`research:${i}`}>{dateTime(item.saved_at,true)} · 調査結果</option>)}{status.answers.map((item, i) => <option key={`answer-${i}`} value={`answer:${i}`}>{item.answer ? dateTime(item.answer.evidence_as_of) : `保存済み提案 ${i + 1}`} · 検算済み</option>)}</select></label>
      {showResearch && researchHistory.slice(historyIndex,historyIndex+1).map(item=><section key={item.record_id}><h2>相談結果</h2><p className="setting-footnote">保存 {dateTime(item.saved_at,true)} · 原予測・実保有とは別の記録です。</p>{item.answer?.research ? <ConsultationReport value={item.answer.research} /> : <pre className="research-text">{item.original_json}</pre>}</section>)}
      {!showResearch && status.answers.slice(historyIndex, historyIndex + 1).map((item, i) => <section key={i}>
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
