import { useApiData } from "../hooks";
import { yen } from "../components";

/** Read actual saved policy values. The mock's editable controls are not a new
 * contract for changing the decision engine. */
export function PolicySummary() {
  const {data,error,loading}=useApiData<{decisionPolicies?: {
    roundLotShares?: number; maximumPositions?: number|null;
    maximumSymbolWeight?: string|null; minimumImprovementYen?: string|null;
  }}>("/api/v1/settings");
  const policy=data?.decisionPolicies;
  return <section className="numbered-section"><small>03</small><h2>取引制約</h2>
    {loading ? <p>保存済みの計算条件を確認中…</p> : error ? <p role="alert">計算条件を取得できません。</p> : <dl className="summary-list">
      <div><dt>売買単位</dt><dd>{policy?.roundLotShares == null ? "未確認" : `${policy.roundLotShares}株`}</dd></div>
      <div><dt>最大保有銘柄数</dt><dd>{policy?.maximumPositions ?? "未設定"}</dd></div>
      <div><dt>1銘柄の集中上限</dt><dd>{policy?.maximumSymbolWeight == null ? "未設定" : `${Number(policy.maximumSymbolWeight)*100}%`}</dd></div>
      <div><dt>最低改善幅</dt><dd>{yen(policy?.minimumImprovementYen)}</dd></div>
    </dl>}
    <p className="setting-footnote">採用している計算条件の表示です。</p>
  </section>;
}
