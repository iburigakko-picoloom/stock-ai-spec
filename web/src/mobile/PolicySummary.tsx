import { useApiData } from "../hooks";
import { currency as yen } from "../components";
import { Field, KV, SettingGroup } from "../Adopted";
import type { HomeResponse } from "../types";
import { isAndroid } from "./native";

export function AllocationReadout() {
  const {data}=useApiData<HomeResponse>(isAndroid() ? "/api/v1/home/ledger" : "/api/v1/home");
  return <><KV label="株式時価" value={yen(data?.portfolio?.equityValue)} /><KV label="現金（投資上限の対象外）" value={yen(data?.portfolio?.cashValue)} /></>;
}
export function MinimumCashField() {
  const {data}=useApiData<{capital?:{minimumCashRatio:string|null}}>("/api/v1/settings");
  return <Field label="最低現金（総資産比・%）"><input className="input" readOnly value={data?.capital?.minimumCashRatio==null ? "未設定" : Number(data.capital.minimumCashRatio)*100} /></Field>;
}
export function RiskPolicyFields() {
  const {data}=useApiData<{decisionPolicies?:{maximumPositions?:number|null;maximumSymbolWeight?:string|null}}>("/api/v1/settings");
  return <><Field label="最大保有銘柄数"><input className="input" readOnly value={data?.decisionPolicies?.maximumPositions ?? "未設定"} /></Field><Field label="1銘柄の集中上限（%）"><input className="input" readOnly value={data?.decisionPolicies?.maximumSymbolWeight==null ? "未設定" : Number(data.decisionPolicies.maximumSymbolWeight)*100} /></Field></>;
}

/** Read actual saved policy values. The mock's editable controls are not a new
 * contract for changing the decision engine. */
export function PolicySummary() {
  const {data,error,loading}=useApiData<{decisionPolicies?: {
    roundLotShares?: number; maximumPositions?: number|null;
    maximumSymbolWeight?: string|null; minimumImprovementYen?: string|null;
  }}>("/api/v1/settings");
  const policy=data?.decisionPolicies;
  return <SettingGroup number="03" title="取引制約">
    {loading ? <p>保存済みの計算条件を確認中…</p> : error ? <p role="alert">計算条件を取得できません。</p> : <>
      <Field label="売買単位"><input className="input" readOnly value={policy?.roundLotShares == null ? "未確認" : `${policy.roundLotShares}株`} /></Field>
      <Field label="最低改善幅"><input className="input" readOnly value={yen(policy?.minimumImprovementYen)} /></Field>
      <label className="row"><input type="checkbox" disabled checked={false} readOnly />空売りを許可</label><label className="row"><input type="checkbox" disabled checked={false} readOnly />信用取引を許可</label>
    </>}
    <p className="subhint">採用している計算条件の表示です。</p>
  </SettingGroup>;
}
