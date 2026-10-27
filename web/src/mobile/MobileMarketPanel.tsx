import { useEffect, useRef, useState, type ReactNode } from "react";
import { apiGet, apiPost } from "../api";
import { acquireMembership, acquireRange, defaultPlan, type AcquisitionMode, type MarketPlan, type MarketStatus, type MembershipStatus, type UniversePolicy, type UniversePreview } from "./market";
import { KV } from "../Adopted";
import { dateTime } from "../components";
import { isAndroid } from "./native";
import { visibleReads } from "./visibleReads";

export function MobileMarketPanel({ configured, disabled, onBusy, onBackground }: {
  configured: boolean; disabled: boolean; onBusy: (value: boolean) => void; onBackground?: () => void;
}): ReactNode {
  const [status, setStatus] = useState<MarketStatus | null>(null);
  const [plan, setPlan] = useState<MarketPlan>(defaultPlan);
  const [planHasDraft, setPlanHasDraft] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [planReady, setPlanReady] = useState(false);
  const [statusReady, setStatusReady] = useState(false);
  const [membershipReady, setMembershipReady] = useState(false);
  const [policyReady, setPolicyReady] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState("");
  const [refreshDay, setRefreshDay] = useState("");
  const [selection, setSelection] = useState<UniversePreview | null>(null);
  const [membership, setMembership] = useState<MembershipStatus | null>(null);
  const [policy, setPolicy] = useState<UniversePolicy | null>(null);
  const [changingPolicy, setChangingPolicy] = useState(false);
  const stop = useRef(false);
  const planEdited = useRef(false);
  useEffect(() => {
    let active = true;
    setLoaded(false); setPlanReady(false); setStatusReady(false); setMembershipReady(false); setPolicyReady(false); setLoadFailed(false);
    const saved = () => apiGet<MarketStatus>("/api/v1/mobile/market").then(value => { if (active) { setStatus(value); setStatusReady(true); } });
    const range = () => apiGet<MarketPlan | null>("/api/v1/mobile/market/plan").then(value => {
      if (active) { if (value && !planEdited.current) setPlan(value); setPlanReady(true); }
    });
    const member = () => apiGet<MembershipStatus>("/api/v1/mobile/market/membership").then(value => { if (active) { setMembership(value); setMembershipReady(true); } });
    const mode = () => apiGet<UniversePolicy>("/api/v1/mobile/market/universe-policy").then(value => { if (active) { setPolicy(value); setPolicyReady(true); } });
    void visibleReads([saved, range, member, mode], () => active, isAndroid(), () => {
      setLoadFailed(true); setMessage("取得範囲と保存データを確認できません。アプリを再起動してください。");
    }).then(success => { if (active && success) setLoaded(true); });
    return () => { active = false; stop.current = true; };
  }, []);
  async function run(range: MarketPlan, mode: AcquisitionMode = "pending"): Promise<void> {
    stop.current = false; setRunning(true); onBusy(true); setSelection(null);
    try {
      const result = await acquireRange(range, (day, done, total, saved) => {
        setMessage(`${day}を${saved ? "保存しました" : "取得しています"}（${done} / ${total}日）。`);
        if (saved) setStatus(saved);
      }, () => stop.current, mode);
      setStatus(result.status);
      setMessage(result.stopped ? "取得を停止しました。取得済みの日付・ページから再開できます。" : "指定範囲を保存しました。予測と推奨株数の更新状況は別に確認します。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "取得を完了できません。続きから再開できます。");
    } finally { setRunning(false); onBusy(false); }
  }
  async function inspect(task: () => Promise<void>): Promise<void> {
    onBusy(true);
    try { await task(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "データを確認できません。"); }
    finally { onBusy(false); }
  }
  const hasSavedRange=(status?.completed_dates ?? []).some(day=>day>=plan.first_day && day<=plan.last_day);
  return <div className="subscreen advanced-domain" aria-label="市場データ"><div className="card stack"><section className="advanced-section">
    <h3 className="section-title">履歴データ</h3>
      <label>取得開始日<input className="input" type="date" disabled={disabled || running || !planReady} value={planReady || planHasDraft ? plan.first_day : ""} onChange={e => {planEdited.current=true; setPlanHasDraft(true); setPlan({ ...plan, first_day: e.target.value });}} /></label>
      <label>取得終了日<input className="input" type="date" disabled={disabled || running || !planReady} value={planReady || planHasDraft ? plan.last_day : ""} onChange={e => {planEdited.current=true; setPlanHasDraft(true); setPlan({ ...plan, last_day: e.target.value });}} /></label>
    <KV label="処理状況" value={running ? "取得中" : loaded ? "停止中" : loadFailed ? "確認できません" : "確認中"} /><KV label="最終保存日" value={statusReady && status ? status.latest_data_date ?? "未取得" : loadFailed ? "未確認" : "確認中"} />
    <div className="subactions"><button className="button" disabled={disabled || !configured || !loaded || running || hasSavedRange} onClick={() => void run(plan)}>履歴を取得</button><button className="button secondary" disabled={disabled || !configured || !loaded || running || !hasSavedRange} onClick={() => void run(plan)}>再開</button></div>
    <button className="button secondary" style={{marginTop:8,width:"100%"}} disabled={!running} onClick={() => { stop.current = true; setMessage("今の日付の保存が終わったら停止します。"); }}>この日付の取得後に停止</button>
    {onBackground && <button className="quiet-link" aria-label="バックグラウンド取得の設定へ" disabled={disabled || running || !configured} onClick={onBackground}>自動更新で取得 ›</button>}
    <p className="subhint">画面を開いて取得します。最大2年、保存済みの続きから再開します。</p>
    <p role="status" aria-live="polite">{message}</p>
    </section><section className="advanced-section"><h3 className="section-title">銘柄一覧</h3>
      <KV label="最終取得" value={!membershipReady || !membership ? loadFailed ? "未確認" : "確認中" : membership.latest_received_at ? dateTime(membership.latest_received_at,true) : "未取得"} /><KV label="11:30までの受領" value={membershipReady && membership?.eligible_received_at ? dateTime(membership.eligible_received_at,true) : "未確認"} />
      <div className="subactions">
        <button className="button button--secondary" disabled={disabled || running || !loaded || !configured} onClick={() => void inspect(async () => {
          const saved = await acquireMembership(); setMembership(saved); setSelection(null);
          setMessage(saved.available_at_cutoff ? saved.is_business_day ? "当日の銘柄一覧を確認しました。" : "カレンダーで当日の休場を確認しました。" : "11:30後の受領です。今日の数値予測へは使えません。");
        })}>当日の銘柄一覧を取得・再開</button>
        <button className="button button--secondary" disabled={disabled || running || !loaded || !configured} onClick={() => void inspect(async () => {
          const saved = await acquireMembership(true); setMembership(saved); setSelection(null);
          setMessage("銘柄一覧を取り直しました。11:30を過ぎて受領した情報は今日の数値予測へ使いません。");
        })}>当日の銘柄一覧を最初から再取得</button>
      </div></section><section className="advanced-section"><h3 className="section-title">訂正・指定日</h3>      <label>訂正を確認する日付<input className="input" type="date" disabled={disabled || running} value={refreshDay} onChange={e => setRefreshDay(e.target.value)} /></label>
<div className="button-stack">
        <button className="button button--secondary" disabled={disabled || running || !loaded || !configured || !refreshDay} onClick={() => void run({ first_day: refreshDay, last_day: refreshDay }, "corrections")}>この日付の訂正を取得・再開</button>
        <button className="button button--secondary" disabled={disabled || running || !loaded || !configured || !refreshDay} onClick={() => void run({ first_day: refreshDay, last_day: refreshDay }, "restart")}>この日付を最初から再取得</button>
      </div></section><section className="advanced-section"><h3 className="section-title">対象銘柄・特徴量</h3>      <label>予測対象<select className="input" value={policyReady ? policy?.mode ?? "" : ""} disabled={disabled || running || changingPolicy || !loaded || !policy} onChange={e => {
        const mode = e.target.value;
        setChangingPolicy(true);
        void inspect(async () => {
          try {
            setPolicy(await apiPost<UniversePolicy>("/api/v1/mobile/market/universe-policy", { mode }));
            setSelection(null); setMessage("次に作成する数値予測から対象方式を適用します。");
          } finally { setChangingPolicy(false); }
        });
      }}>{(!policyReady || !policy) && <option value="">未確認</option>}<option value="legacy300">従来300</option><option value="topix500-preview">TOPIX500</option></select></label>
      <p>{!policyReady || !policy ? loadFailed ? "予測対象を確認できません。" : "予測対象を確認中…" : policy.mode === "topix500-preview" ? "TOPIX500の規模3区分の全銘柄と全保有を対象にします。研究用で、実機確認中です。" : "時価総額300億円以上・売買代金上位300銘柄と全保有を対象にします。"}</p>
<div className="button-stack">
        <button className="button button--secondary" disabled={disabled || running || !loaded || !status?.latest_data_date} onClick={() => void inspect(async () => {
          setSelection(await apiGet<UniversePreview>("/api/v1/mobile/market/current-universe")); setMessage("対象抽出の受領記録を確認しました。");
        })}>候補と全保有の対象を確認</button>
        <button className="button button--secondary" disabled={disabled || running || !loaded || !status?.latest_data_date} onClick={() => void inspect(async () => {
          await apiPost("/api/v1/mobile/features/latest", {}); setMessage("保存データで特徴量を計算しました。モデル採用と推論の一致確認は別途必要です。");
        })}>保存データで特徴量を確認</button>
      </div>
      <p>検証に失敗し続ける場合は「最初から再取得」で取り直せます。</p>
      {selection && <div><p>抽出時点：{selection.as_of}／当日の銘柄一覧：{selection.membership_source_date ?? "未確認"}／最終株価日：{selection.latest_source_date ?? "不足"}</p>
        {selection.holdings_recorded === false && <p>保有の入力が未確認です。対象の保有銘柄を確定するには、口座・保有の入力が必要です。</p>}
        <p>{selection.membership_mode === "preselected" ? "TOPIX500区分の" : "条件内の上位"}{selection.new_candidates.length}社＋対象外の保有{selection.held_only.length}社＝評価対象{selection.decision_symbols.length}社</p>
        {selection.blocking_reasons.some(x => x.startsWith("current_membership_missing")) ? <p>11:30までに受領した当日の銘柄一覧がありません。全保有を対象に残しています。</p>
          : selection.blocking_reasons.includes("non_business_day") ? <p>当日は休場日です。新しい数値予測は作成しません。</p>
          : selection.blocking_reasons.includes("held_instrument_unsupported_or_not_listed") ? <p>対応する国内普通株として確認できない保有があります。銘柄と上場状況の確認が必要です。</p>
          : selection.membership_mode === "preselected" && selection.blocking_reasons.length > 0 ? <p>規模区分の受領記録を確認できません。</p>
          : selection.blocking_reasons.length > 0 && <p>必要な20営業日のカレンダー・株価・時価総額がそろっていません。全保有を対象に残しています。</p>}
        {selection.membership_mode === "preselected" && (selection.excluded?.length ?? 0) > 0 && <ul>{selection.excluded?.map((item, index) => <li key={`${item.symbol}-${index}`}>{item.symbol}：対応する国内普通株として確認できません。</li>)}</ul>}
        <p>全保有のうち条件外：{selection.held_only.join("、") || "なし"}。市場・業種の特徴量は全体の母集団から計算します。</p>
      </div>}
    </section>
  </div></div>;
}
