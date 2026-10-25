import { dateTime } from "./components";

export interface ConsultationFindings {
  market_5d: string;
  market_20d: string;
  cash_rationale: string;
  companies?: { symbol: string; independent_research: string; impact_5d: string; impact_20d: string; numerical_comparison: string; action: string; rationale: string }[];
  sources?: { url: string; title: string; published_at: string | null; observed_at: string }[];
  unknowns?: string[];
}

export function ConsultationReport({ value }: { value: ConsultationFindings }) {
  return <>
    <p>5日：{value.market_5d}</p><p>20日：{value.market_20d}</p>
    <p>現金：{value.cash_rationale}</p>
    <details><summary>企業ごとの調査・出典</summary>
      {value.companies?.map(company => <section key={company.symbol}>
        <h3>{company.symbol}</h3><p>{company.rationale}</p>
        <p>独立調査：{company.independent_research}</p>
        <p>5日への影響：{company.impact_5d}</p><p>20日への影響：{company.impact_20d}</p>
        <p>数値との照合：{company.numerical_comparison}</p>
      </section>)}
      {value.sources?.map((source, i) => <p key={`${source.url}-${i}`}>
        <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
        <small> 公開 {source.published_at ? dateTime(source.published_at) : "日時未確認"}・確認 {dateTime(source.observed_at)} JST</small>
      </p>)}
      {!!value.unknowns?.length && <p>未確認：{value.unknowns.join(" / ")}</p>}
    </details>
  </>;
}
