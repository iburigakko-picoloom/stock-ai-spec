import { useState } from "react";
import type { AccountSettings, PersonalSettings, SavedPortfolio } from "./personal";

// Fill calculation assumptions only. Account facts and fee eligibility stay unconfirmed.
export function sbiStandardSettings(draft: PersonalSettings, now = new Date()): PersonalSettings {
  const today = new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
  return { ...draft,
    budget_basis: "maximum_total_equity_market_value",
    tax_year: draft.tax_year ?? Number(today.slice(0, 4)),
    cost_assumptions: { ...draft.cost_assumptions,
      full_spread_bps: draft.cost_assumptions.full_spread_bps ?? "10",
      slippage_bps: draft.cost_assumptions.slippage_bps ?? "5",
      impact_bps_at_full_adv: draft.cost_assumptions.impact_bps_at_full_adv ?? "25",
    },
    tax_assumptions: {
      effective_from: draft.tax_assumptions.effective_from ?? today,
      taxable_rate_percent: draft.tax_assumptions.taxable_rate_percent ?? "20.315",
      nisa_opportunity_cost_percent: draft.tax_assumptions.nisa_opportunity_cost_percent ?? "0",
    },
    research_conditions_reviewed: true,
  };
}

function Money({ label, value, onChange }: { label: string; value: string | null; onChange: (value: string | null) => void }) {
  return <label>{label}<input inputMode="decimal" value={value ?? ""} placeholder="円" onChange={e => onChange(e.target.value || null)} /></label>;
}

function OptionalMoney({ title, label, value, onChange }: { title: string; label: string; value: string | null; onChange: (value: string | null) => void }) {
  const [enter, setEnter] = useState(false);
  const mode = enter ? "amount" : value === null ? "" : Number(value) === 0 ? "none" : "amount";
  return <div><label>{title}<select value={mode} onChange={e => {
    setEnter(e.target.value === "amount"); onChange(e.target.value === "none" ? "0" : null);
  }}><option value="">選んでください</option><option value="none">なし</option><option value="amount">あり（金額を入力）</option></select></label>
    {mode === "amount" && <Money label={label} value={value} onChange={onChange} />}
  </div>;
}

function AccountQuestions({ source, item, change }: { source: SavedPortfolio["portfolio"]["accounts"][number]; item: AccountSettings; change: (value: Partial<AccountSettings>) => void }) {
  const [enterTax, setEnterTax] = useState(false);
  const zeroTax = item.realized_gain_ytd !== null && item.realized_loss_ytd !== null && Number(item.realized_gain_ytd) === 0 && Number(item.realized_loss_ytd) === 0;
  const taxMode = enterTax ? "amount" : zeroTax ? "none" : item.realized_gain_ytd !== null || item.realized_loss_ytd !== null ? "amount" : "";
  return <fieldset><legend>{source.name}</legend>
    <OptionalMoney title="注文用・出金用などに確保している現金" label="確保中の金額（円）" value={item.reserved_cash_yen} onChange={value => change({ reserved_cash_yen: value })} />
    <label>残高に未反映の売買・入出金や、未決済の取引<select value={item.pending_activity} onChange={e => change({ pending_activity: e.target.value as AccountSettings["pending_activity"] })}>
      <option value="unknown">選んでください</option><option value="none">なし</option><option value="pending">あり（反映・決済後に登録）</option>
    </select></label>
    {source.account_type === "nisa" ? <>
      <p className="setting-footnote">NISAは残り枠だけ入力します。課税用の損益は計算に使いません。</p>
      <Money label="今年の残り購入枠（円）" value={item.nisa_annual_capacity_user_input} onChange={value => change({ nisa_annual_capacity_user_input: value })} />
      <Money label="生涯の残り購入枠（円）" value={item.nisa_lifetime_capacity_user_input} onChange={value => change({ nisa_lifetime_capacity_user_input: value })} />
      {(item.realized_gain_ytd === null || item.realized_loss_ytd === null || item.loss_carryforward_user_input === null) && <button type="button" className="button button--secondary" onClick={() => change({
        realized_gain_ytd: item.realized_gain_ytd ?? "0", realized_loss_ytd: item.realized_loss_ytd ?? "0", loss_carryforward_user_input: item.loss_carryforward_user_input ?? "0",
      })}>NISAの課税計算を対象外にする</button>}
    </> : <>
      <label>今年の売却による利益・損失<select value={taxMode} onChange={e => {
        setEnterTax(e.target.value === "amount");
        change({ realized_gain_ytd: e.target.value === "none" ? "0" : null, realized_loss_ytd: e.target.value === "none" ? "0" : null });
      }}><option value="">選んでください</option><option value="none">0円（売却なし等）</option><option value="amount">金額を入力する</option></select></label>
      {taxMode === "amount" && <>
        <p className="setting-footnote">売却済みの損益です。保有中の含み損益は含めません。</p>
        <Money label="今年の売却益の合計（円）" value={item.realized_gain_ytd} onChange={value => change({ realized_gain_ytd: value })} />
        <Money label="今年の売却損の合計（正の円額）" value={item.realized_loss_ytd} onChange={value => change({ realized_loss_ytd: value })} />
      </>}
      <OptionalMoney title="前年以前から繰り越して使う損失" label="利用する繰越損失（円）" value={item.loss_carryforward_user_input} onChange={value => change({ loss_carryforward_user_input: value })} />
    </>}
  </fieldset>;
}

export function SbiConditions({ profile, draft, change, onManual }: { profile: SavedPortfolio; draft: PersonalSettings; change: (value: PersonalSettings) => void; onManual: () => void }) {
  const year = Number(new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 4));
  const costs = draft.cost_assumptions;
  const assumptionsReady = draft.budget_basis && draft.tax_year && draft.research_conditions_reviewed &&
    [costs.full_spread_bps, costs.slippage_bps, costs.impact_bps_at_full_adv, ...Object.values(draft.tax_assumptions)].every(x => x !== null);
  return <>
    <div className="account-form-card"><h3>SBI証券のかんたん設定</h3>
      {!assumptionsReady ? <>
        <p className="setting-footnote">税率20.315%・価格のずれ等は標準値、NISA枠の追加費用は0。投資上限は保有株の時価合計です。研究用の比較条件を使います。入力済みの数値は保持します。</p>
        <button type="button" className="button button--primary" onClick={() => change(sbiStandardSettings(draft))}>標準の計算条件を使う</button>
      </> : <p className="setting-footnote">計算条件は設定済み。細かい数値の入力は不要です。</p>}
      <button type="button" className="settings-back" onClick={onManual}>計算条件の確認・変更 →</button>
    </div>
    <div className="account-form-card"><h3>手数料</h3>
      <label>国内株式の「ゼロ革命」<select value={costs.zero_commission_confirmed ? "free" : ""} onChange={e => {
        if (e.target.value === "manual") { onManual(); return; }
        change({ ...draft, cost_assumptions: { ...costs, commission_fixed_yen: e.target.value === "free" ? "0" : null,
          commission_bps: e.target.value === "free" ? "0" : null, minimum_commission_yen: e.target.value === "free" ? "0" : null, zero_commission_confirmed: e.target.value === "free" } });
      }}><option value="">未確認・無料以外</option><option value="free">無料を確認済み</option><option value="manual">無料以外を入力</option></select></label>
      <p className="setting-footnote">ネット取引・所定の書面すべての電子交付などが条件です。<a href="https://faq.sbisec.co.jp/answer/64f176ea8e582c2aa5655c2a/" target="_blank" rel="noreferrer">SBIの条件を確認</a></p>
    </div>
    <div className="account-form-card"><h3>残高の確認</h3>
      <label>口座・保有に入力した現金額<select value={draft.cash_basis ?? ""} onChange={e => change({ ...draft, cash_basis: e.target.value as PersonalSettings["cash_basis"] || null })}>
        <option value="">選んでください</option><option value="deployable_after_reserved">買付余力</option><option value="total_including_reserved">総現金</option>
      </select></label>
      <p className="setting-footnote">買付余力は確保分を除いた額、総現金は含む額です。複数口座への重複入力は不要です。</p>
      {draft.tax_year !== null && draft.tax_year !== year && <p role="alert">{draft.tax_year}年の損益が残っています。「計算条件の確認・変更」で対象年と損益を見直してください。</p>}
      {profile.portfolio.accounts.map(source => {
        const item = draft.accounts.find(x => x.account_id === source.id);
        return item ? <AccountQuestions key={source.id} source={source} item={item} change={value => change({ ...draft, accounts: draft.accounts.map(x => x.account_id === source.id ? { ...x, ...value } : x) })} /> : null;
      })}
    </div>
  </>;
}
