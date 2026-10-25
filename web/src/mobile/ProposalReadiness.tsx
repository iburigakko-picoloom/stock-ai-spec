import { Link } from "react-router-dom";
import { useApiData } from "../hooks";
import { isAndroid } from "./native";
import { gapLabel, type Readiness } from "./personal";

function unfinishedItems(data: Readiness): string[] {
  const shortLabels: Record<string, string> = {
    available_cash_yen: "現金残高", average_acquisition_price_yen: "取得単価",
    investment_budget_yen: "投資上限", maximum_drawdown_percent: "許容下落率",
    held_prices_missing: "保有株の価格", held_prices_stale: "保有株の価格更新",
    held_prices_invalid: "保有株の価格確認", LEDGER_MISSING: "残高の確定",
    FORECAST_MISSING: "最新予測", MARKET_MISSING: "市場データ",
    SETTINGS_MISSING: "補足設定", MANUAL_INPUT_MISSING: "口座・保有の登録",
    personal_settings: "補足設定", manual_input: "口座・保有の登録",
    cost_assumptions: "取引コスト", tax_assumptions: "税の計算条件",
  };
  const codes = [...data.input_gaps,
    ...(!data.comparison.ledger_portfolio_id ? [...data.initial_ledger.blocking_reasons, "LEDGER_MISSING"] : []),
    ...data.comparison.blocking_reasons.map(item => item.code),
  ].map(code => code.startsWith("INPUT_MISSING_") ? code.slice(14).toLowerCase() : code);
  return [...new Set(codes.filter(code =>
    !["ledger_already_initialized", "executions_already_recorded"].includes(code)
    && !(code === "SETTINGS_MISSING" && data.input_gaps.length > 0)
  ).map(code => shortLabels[code] ?? gapLabel(code)))];
}

export function proposalBlockLabel(reason: string | null): string {
  if (!reason) return "当日の提案はまだ作成されていません。";
  const labels: Record<string, string> = {
    ALPHA_CUTOFF_OPEN: "今日の予測は11:30以降に更新します。時刻までお待ちください。",
    PERSONAL_INPUTS_CHANGED: "登録内容が前回の計算後に変更されています。最新の登録内容で再計算が必要です。",
    PERSONAL_SETTINGS_AFTER_ALPHA_CUTOFF: "補足設定が判定時刻より後に更新されています。次の判定時刻に合うデータで再計算が必要です。",
    NUMERICAL_FORECAST_INCOMPLETE: "数値予測がまだ完成していません。分析に失敗した場合は、この画面に停止理由を表示します。",
    NUMERICAL_FORECAST_NOT_CURRENT_DAY: "保存済みの数値予測が今日の分ではありません。当日の予測の更新が必要です。",
    PERSONAL_INPUTS_INCOMPLETE: "口座・補足設定・初回台帳のいずれかが未完了です。登録内容の確認が必要です。",
    PERSONAL_INPUTS_DIFFER_FROM_NUMERICAL: "登録内容と数値予測に使った内容が一致しません。最新の登録内容で予測を更新してください。",
    PERSONAL_INPUTS_STALE_OR_AFTER_FORECAST: "口座・台帳の日時が予測の条件に合いません。登録日時と台帳の照合が必要です。",
    NUMERICAL_FORECAST_FROM_FUTURE: "予測の保存日時が端末の現在時刻より先です。端末の時計を確認してください。",
    CALIBRATED_MODEL_BUNDLE_UNAVAILABLE: "計算に必要なモデル一式を利用できません。モデル設定の読込・検証結果を確認してください。",
    MODEL_SELECTION_DIFFERS_FROM_NUMERICAL: "選択中のモデルと保存済み予測のモデルが異なります。選択中のモデルで予測を更新してください。",
  };
  return labels[reason] ?? `停止理由：${gapLabel(reason)}`;
}

function ReadinessDetails({ reason }: { reason: string | null }) {
  const { data, error, loading, reload } = useApiData<Readiness & { portfolio_revision_id?: string | null }>("/api/v1/mobile/personal/readiness");
  // Name unfinished items briefly; keep just one next action.
  const unfinished = data ? unfinishedItems(data) : [];
  const gap = data?.input_gaps[0];
  const priceGap = !data?.comparison.ledger_portfolio_id
    ? data?.initial_ledger.blocking_reasons.find(code => code.startsWith("held_prices_")) : undefined;
  let message = proposalBlockLabel(reason);
  let target = "model";
  let action = "予測の状況を確認";
  if (gap) {
    message = `${gapLabel(gap)}が未完了です。`;
    target = ["holdings_status", "average_acquisition_price_yen", "shares"].includes(gap) ? "holdings" : gap === "investment_budget_yen" ? "capital" : gap === "maximum_drawdown_percent" ? "risk" : "accounts";
    action = "不足している情報を入力";
  } else if (priceGap) {
    message = "残高の確定に必要な保有株の価格を確認できません。";
    target = "market"; action = "株価の取得状況を確認";
  } else if (data && !data.comparison.ledger_portfolio_id) {
    message = "入力は保存されていますが、残高の確定がまだです。";
    target = "accounts"; action = "残高を確認・確定する";
  } else if (data?.comparison.blocking_reasons.length && !reason) {
    const code = data.comparison.blocking_reasons[0].code;
    message = code === "FORECAST_MISSING" ? "提案に使える最新予測がまだありません。" : `${gapLabel(code)}が必要です。`;
    if (code === "MARKET_MISSING") { target = "market"; action = "市場データを確認"; }
    else if (/^(MANUAL|LEDGER|SETTINGS|INPUT_MISSING)/.test(code)) { target = "accounts"; action = "登録内容を確認"; }
  }
  const waiting = !gap && !priceGap && !!data?.comparison.ledger_portfolio_id && reason === "ALPHA_CUTOFF_OPEN";
  return <section className="section" aria-label="提案に必要な情報">
    <h2>{loading ? "登録内容を確認中" : error ? "状態を確認できません" : "提案を表示できない理由"}</h2>
    {loading ? <p role="status">最新の状態を読み込んでいます。</p>
      : error ? <><p role="alert">登録が消えたわけではありません。もう一度確認してください。</p><button className="button button--secondary" onClick={reload}>再確認</button></>
      : data && <>
        {data.portfolio_revision_id && <p className="explain">口座・保有は登録済みです。</p>}
        {unfinished.length > 0 && <p aria-label="未完了の項目"><strong>未完了：</strong>{unfinished.join("・")}</p>}
        <p>{message}</p>
        {!waiting && <Link className="button button--secondary" to={target === "holdings" ? "/holdings" : `/settings?edit=${target}`}>{action}</Link>}
      </>}
  </section>;
}

export function ProposalReadiness({ reason = null }: { reason?: string | null }) {
  return isAndroid() ? <ReadinessDetails reason={reason} /> : null;
}
