import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { PageHeader, StatePanel, dateTime } from "../components";
import { isAndroid } from "../mobile/native";

interface Review {
  lines: { symbol: string; account: string; current_shares: number; target_shares: number; share_difference: number }[];
  estimated_cost_yen: string;
  estimated_cash_after: Record<string, string>;
  applied_to_ledger: false;
  answer?: { evidence_as_of: string; targets: { symbol: string; account: string; reason: string; sources: string[] }[]; unknowns: string[] };
}
interface ManualStatus { ready: boolean; reason: string | null; selected_input: string | null; answers: Review[]; account_labels?: Record<string, string> }
interface Exported { input_record_id: string; input_snapshot_id: string; expires_at: string; prompt: string }

export function ManualChatGPTPage(): ReactNode {
  const [status, setStatus] = useState<ManualStatus | null>(null);
  const [privateUse, setPrivateUse] = useState(false);
  const [entitled, setEntitled] = useState(false);
  const [exported, setExported] = useState<Exported | null>(null);
  const [answer, setAnswer] = useState("");
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const android = isAndroid();
  useEffect(() => {
    if (!android) return;
    let active = true;
    void apiGet<ManualStatus>("/api/v1/mobile/chatgpt-manual/status")
      .then(value => { if (active) setStatus(value); })
      .catch(() => { if (active) setError("保存済み入力を確認できません。アプリを開き直してください。"); });
    return () => { active = false; };
  }, [android]);

  async function prepare(): Promise<void> {
    setBusy(true); setError(""); setMessage(""); setReview(null);
    try {
      setExported(await apiPost<Exported>("/api/v1/mobile/chatgpt-manual/export", {
        service: "manual_chatgpt", checked_at: new Date().toISOString(),
        personal_analysis_only: privateUse, training_disabled: privateUse,
        private_input: privateUse, private_output: privateUse, data_entitlement_confirmed: entitled,
      }));
      setMessage("入力を保存しました。ChatGPTへコピーし、回答JSONを下へ貼り付けてください。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "入力を作成できませんでした。"); }
    finally { setBusy(false); }
  }
  async function copy(): Promise<void> {
    if (!exported) return;
    try { await navigator.clipboard.writeText(exported.prompt); setMessage("プロンプトをコピーしました。"); }
    catch { setError("コピーできません。入力欄の文章を選択してコピーしてください。"); }
  }
  async function importAnswer(): Promise<void> {
    setBusy(true); setError(""); setMessage(""); setReview(null);
    try {
      const saved = await apiPost<{ review: Review }>("/api/v1/mobile/chatgpt-manual/answer", {
        input_record_id: exported?.input_record_id ?? status?.selected_input, answer_json: answer,
      });
      setReview(saved.review);
      setMessage("制約を確認し、ChatGPT提案として保存しました。保有・現金・税台帳は更新していません。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "回答を検証できませんでした。"); }
    finally { setBusy(false); }
  }
  return <div className="page manual-chatgpt">
    <Link className="back-link" to="/today">← 今日へ戻る</Link>
    <PageHeader eyebrow="本人用の判断支援" title="ChatGPTと相談" />
    <p className="explain">上位20銘柄と全保有を渡して相談します。モデル・推論設定はChatGPT側で選びます。回答は提案として保存します。</p>
    {!android ? <StatePanel title="Androidアプリで利用できます" detail="端末に保存した最新の原予測・口座・設定を使います。" />
      : !status ? <StatePanel title="保存済み入力を確認しています" />
      : !status.ready ? <StatePanel title="入力の準備待ちです" detail={status.reason ?? "最新の原予測と本人入力を確認してください。"} /> : <>
        <section className="section">
          <h2>1. 入力を渡す</h2>
          <label className="checkbox"><input type="checkbox" checked={privateUse} disabled={busy}
            onChange={event => setPrivateUse(event.target.checked)} />本人の分析だけに使い、学習利用をオフ、会話と結果を非公開にしています</label>
          <label className="checkbox"><input type="checkbox" checked={entitled} disabled={busy}
            onChange={event => setEntitled(event.target.checked)} />使用するデータが現在のJ-Quants契約・取得範囲で利用できると確認しました</label>
          <p className="setting-footnote">共有link・結果の配信や公開・学習利用につながるfeedback送信は行わないでください。
            <a href="https://jpx-jquants.com/ja/help/usage" target="_blank" rel="noreferrer">J-Quantsの利用条件</a></p>
          <div className="button-stack"><button className="button button--primary" disabled={busy || !privateUse || !entitled}
            onClick={() => void prepare()}>プロンプトを作成</button></div>
          {exported && <>
            <p>入力の有効期限：{dateTime(exported.expires_at)}</p>
            <textarea className="csv-input" aria-label="ChatGPTへ渡す入力" readOnly value={exported.prompt} />
            <div className="button-stack"><button className="button button--secondary" disabled={busy} onClick={() => void copy()}>プロンプトをコピー</button></div>
          </>}
        </section>
        <section className="section">
          <h2>2. 回答を確認する</h2>
          <textarea className="csv-input" aria-label="ChatGPTの回答JSON" value={answer} disabled={busy}
            onChange={event => { setAnswer(event.target.value); setReview(null); }} placeholder="回答JSONをここに貼り付け" />
          <div className="button-stack"><button className="button button--primary" disabled={busy || !answer.trim() || !(exported || status.selected_input)}
            onClick={() => void importAnswer()}>回答を検証して保存</button></div>
        </section>
      </>}
    {message && <p role="status">{message}</p>}
    {error && <StatePanel tone="error" title="処理を完了できません" detail={error} />}
    {review && <section className="section"><h2>保存したChatGPT提案</h2>
      {review.lines.map(line => <div className="difference-row" key={`${line.symbol}-${line.account}`}>
        <span>{line.symbol} / {status?.account_labels?.[line.account] ?? line.account}</span><strong className="share-change"><span>{line.current_shares}株</span><span aria-hidden="true">→</span><span>{line.target_shares}株</span></strong>
      </div>)}
      <p>費用見込み {Number(review.estimated_cost_yen).toLocaleString("ja-JP")}円</p>
      <details><summary>理由と根拠</summary>
        {review.answer?.targets.map(target => <p key={`${target.symbol}-${target.account}`}>
          {target.symbol} / {target.account}：{target.reason}
          {target.sources.map(url => <a key={url} href={url} target="_blank" rel="noreferrer"> 出典</a>)}
        </p>)}
        <p>未確認：{review.answer?.unknowns.join(" / ") || "回答に記載なし"}</p>
        {review.answer && <p>回答の申告時点：{dateTime(review.answer.evidence_as_of)}</p>}
      </details>
      <p>実注文はご本人が行い、実際の約定を確認した後に記録してください。</p>
    </section>}
    {!!status?.answers.length && <details className="section"><summary>保存した相談履歴（直近20件）</summary>
      {status.answers.map((item, i) => <details key={i}>
        <summary>{item.answer ? dateTime(item.answer.evidence_as_of) : `保存済み提案 ${i + 1}`}</summary>
        <p>保存時の提案です。現在の保有状態ではありません。</p>
        {item.lines.map(line => <p key={`${line.symbol}-${line.account}`}>
          {line.symbol} / {line.account}：{line.current_shares}株 → {line.target_shares}株
        </p>)}
        {item.answer?.targets.map(target => <p key={`${target.symbol}-${target.account}`}>{target.reason}</p>)}
      </details>)}
    </details>}
  </div>;
}
