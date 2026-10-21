import { type ReactNode, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PageHeader, StatePanel, TabBar, dateTime, yen } from "../components";
import { useApiData } from "../hooks";
import { MobileDevicePanel } from "../mobile/MobileDevicePanel";
import { isAndroid } from "../mobile/native";

interface AccountSetting {
  bucketId: string;
  accountId: string;
  accountType: string;
  withholdingMode: string;
  feePolicyId: string;
  taxPolicyId: string;
  taxYear: number | null;
  realizedGainYtd: string | null;
  realizedLossYtd: string | null;
  lossCarryforward: string | null;
  nisaAnnualCapacity: string | null;
  nisaLifetimeCapacity: string | null;
}

interface SettingsPayload {
  runtimeMode: string;
  runtime: { remoteAccess: string; orderSubmission: string };
  data: { jQuantsApiKeyConfigured: boolean; credentialValueExposed: false };
  capital: {
    availableCash: string | null;
    reservedCash: string | null;
    asOf: string | null;
    minimumCashRatio: string | null;
    dailyProposalLimit: string | null;
  };
  accounts: AccountSetting[];
  decisionPolicies: {
    decisionEngineVersion: string | null;
    costPolicyId: string | null;
    costPolicyVersion: string | null;
    taxPolicyId: string | null;
    taxPolicyVersion: string | null;
    roundLotShares: 100;
    maximumPositions: number | null;
    maximumSymbolWeight: string | null;
    maximumSectorWeight: string | null;
    maximumTurnoverRatio: string | null;
    maximumTradeAdvRatio: string | null;
    minimumImprovementYen: string | null;
    uncertaintyBufferYen: string | null;
  };
  notifications: { inApp: string; webPush: string };
  decision: { freezeTime: string; recommendedTradeTime: string; method: string };
  model: {
    morningChampion: string;
    trainedAt: string | null;
    trainingDataEnd: string | null;
    validationStatus: string;
    automaticPromotion: false;
  };
}

const sections = [
  { id: "capital", title: "資金", category: "account" },
  { id: "broker", title: "証券会社", category: "account" },
  { id: "accounts", title: "口座・税金", category: "account" },
  { id: "trading", title: "取引コスト・制約", category: "ai" },
  { id: "decision", title: "AI判断", category: "ai" },
  { id: "model", title: "モデル", category: "ai" },
] as const;

export function SettingsPage(): ReactNode {
  const { section } = useParams();
  // The editable native form must survive focus/visibility and polling refreshes.
  // Its own APIs load and save revisions; the read-only web settings poller does not own it.
  if (!section && isAndroid()) return <div className="page page--settings"><MobileDevicePanel /></div>;
  return <ReadOnlySettingsPage />;
}

function ReadOnlySettingsPage(): ReactNode {
  const { section } = useParams();
  const [category, setCategory] = useState("account");
  const { data, error, loading } = useApiData<SettingsPayload>("/api/v1/settings");
  const [notificationState, setNotificationState] = useState<string>(() => (
    typeof window.Notification === "undefined"
      ? "unsupported"
      : window.Notification.permission
  ));
  if (loading) return <StatePanel title="設定を読み込んでいます" />;
  if (error || !data) return <StatePanel tone="error" title="設定を取得できません" detail={error} />;

  async function requestNotification(): Promise<void> {
    if (typeof window.Notification === "undefined") {
      setNotificationState("unsupported");
      return;
    }
    setNotificationState(await window.Notification.requestPermission());
  }

  const currentSection = sections.find((item) => item.id === section);
  return (
    <div className="page">
      {section && <Link className="back-link" to="/settings">← 設定一覧へ</Link>}
      <PageHeader title={currentSection?.title || "設定"} />
      {!section && <TabBar label="設定の分類" options={[["account", "口座・資金"], ["ai", "AI・データ"], ["device", "通知"]]} value={category} onChange={setCategory} panelId="settings-panel" />}
      <div {...(!section ? { id: "settings-panel", role: "tabpanel", "aria-labelledby": `settings-panel-${category}` } : {})}>
      {!section && category !== "device" && <section className="settings-list">
        {sections.filter((item) => item.category === category).map((item) => <Link className="settings-row settings-row--link" to={`/settings/${item.id}`} key={item.id}><strong>{item.title}</strong><b aria-hidden="true">→</b></Link>)}
        {category === "ai" && <Link className="settings-row settings-row--link" to="/settings/data"><strong>データ・運用状態</strong><b aria-hidden="true">→</b></Link>}
      </section>}

      {section === "capital" && <section className="section"><dl className="status-list">
        <div><dt>運用対象資金</dt><dd>{yen(data.capital.availableCash)}</dd></div>
        <div><dt>予約現金</dt><dd>{yen(data.capital.reservedCash)}</dd></div>
        <div><dt>最低現金</dt><dd>{data.capital.minimumCashRatio ?? "未登録"}</dd></div>
        <div><dt>1日提案金額上限</dt><dd>{yen(data.capital.dailyProposalLimit)}</dd></div>
        <div><dt>保有更新時点</dt><dd>{dateTime(data.capital.asOf)}</dd></div>
      </dl></section>}
      {section === "broker" && <section className="section"><dl className="status-list">
        <div><dt>証券ログイン</dt><dd>未実装・対象外</dd></div>
        <div><dt>実注文送信</dt><dd>{data.runtime.orderSubmission}</dd></div>
        <div><dt>口座データ入力</dt><dd>手入力 / preview付きCSV</dd></div>
      </dl></section>}
      {section === "accounts" && <section className="section">{data.accounts.length === 0 ? <StatePanel title="口座bucketは未登録です" /> : data.accounts.map((item) => <article className="preview-panel" key={item.bucketId}>
        <h2>{item.bucketId}</h2><p>{item.accountType} / {item.withholdingMode}</p><small>fee {item.feePolicyId} / tax {item.taxPolicyId}</small>
        <dl className="status-list">
          <div><dt>税年</dt><dd>{item.taxYear ?? "—"}</dd></div>
          <div><dt>年内確定利益</dt><dd>{yen(item.realizedGainYtd)}</dd></div>
          <div><dt>年内確定損失</dt><dd>{yen(item.realizedLossYtd)}</dd></div>
          <div><dt>繰越損失</dt><dd>{yen(item.lossCarryforward)}</dd></div>
          <div><dt>NISA年間残枠</dt><dd>{yen(item.nisaAnnualCapacity)}</dd></div>
          <div><dt>NISA生涯残枠</dt><dd>{yen(item.nisaLifetimeCapacity)}</dd></div>
        </dl><p className="explain">税額・税効果は意思決定用の推定です。</p>
      </article>)}</section>}
      {section === "trading" && <section className="section"><dl className="status-list">
        <div><dt>売買単位</dt><dd>{data.decisionPolicies.roundLotShares}株</dd></div>
        <div><dt>最大保有</dt><dd>{data.decisionPolicies.maximumPositions ?? "未登録"}</dd></div>
        <div><dt>1銘柄上限</dt><dd>{data.decisionPolicies.maximumSymbolWeight ?? "未登録"}</dd></div>
        <div><dt>1業種上限</dt><dd>{data.decisionPolicies.maximumSectorWeight ?? "未登録"}</dd></div>
        <div><dt>最大Turnover</dt><dd>{data.decisionPolicies.maximumTurnoverRatio ?? "未登録"}</dd></div>
        <div><dt>流動性上限</dt><dd>{data.decisionPolicies.maximumTradeAdvRatio ?? "未登録"}</dd></div>
        <div><dt>最低改善閾値</dt><dd>{yen(data.decisionPolicies.minimumImprovementYen)}</dd></div>
        <div><dt>不確実性バッファ</dt><dd>{yen(data.decisionPolicies.uncertaintyBufferYen)}</dd></div>
        <div><dt>コストpolicy</dt><dd>{data.decisionPolicies.costPolicyId ?? "—"} / {data.decisionPolicies.costPolicyVersion ?? "—"}</dd></div>
        <div><dt>税policy</dt><dd>{data.decisionPolicies.taxPolicyId ?? "—"} / {data.decisionPolicies.taxPolicyVersion ?? "—"}</dd></div>
        <div><dt>変更判断</dt><dd>未再最適化株数は保存不可</dd></div>
      </dl></section>}
      {section === "decision" && <section className="section"><dl className="status-list">
        <div><dt>Decision Engine</dt><dd>{data.decisionPolicies.decisionEngineVersion ?? "—"}</dd></div>
        <div><dt>判断時刻</dt><dd>{data.decision.freezeTime}</dd></div>
        <div><dt>推奨取引時刻</dt><dd>{data.decision.recommendedTradeTime}</dd></div>
        <div><dt>提案方式</dt><dd>{data.decision.method}</dd></div>
      </dl></section>}
      {section === "model" && <section className="section"><dl className="status-list">
        <div><dt>Champion</dt><dd>{data.model.morningChampion}</dd></div>
        <div><dt>学習時刻</dt><dd>{dateTime(data.model.trainedAt)}</dd></div>
        <div><dt>学習データ最終日</dt><dd>{dateTime(data.model.trainingDataEnd)}</dd></div>
        <div><dt>検証状態</dt><dd>{data.model.validationStatus}</dd></div>
        <div><dt>自動model昇格</dt><dd>{data.model.automaticPromotion ? "有効" : "無効"}</dd></div>
      </dl></section>}

      {!section && category === "ai" && <details className="section metadata-details">
        <summary>運用状態の詳細</summary>
        <dl className="status-list">
          <div><dt>Runtime</dt><dd>{data.runtimeMode}</dd></div>
          <div><dt>J-Quants key</dt><dd>{data.data.jQuantsApiKeyConfigured ? "設定済み（値は非表示）" : "未継承"}</dd></div>
          <div><dt>Remote access</dt><dd>{data.runtime.remoteAccess}</dd></div>
          <div><dt>実注文</dt><dd>{data.runtime.orderSubmission}</dd></div>
        </dl>
      </details>}
      {!section && category === "device" && <section className="section">
        <div className="section-title"><div><span>NOTIFICATIONS</span><h2>端末通知</h2></div></div>
        <p className="explain">アプリ内通知のみ。外部へのプッシュ配信は未設定です。</p>
        <button className="button button--secondary" onClick={() => void requestNotification()}>この端末の通知権限を確認</button>
        <small className="setting-footnote">現在: {notificationState}</small>
      </section>}
      {section && !currentSection && <StatePanel tone="error" title="不明な設定項目です" />}
      </div>
    </div>
  );
}
