import { dateTime } from "./components";

export interface ConsultationFindings {
  market_5d: string;
  market_20d: string;
  cash_rationale: string;
  companies?: { symbol: string; independent_research: string; impact_5d: string; impact_20d: string; numerical_comparison: string; action: string; rationale: string }[];
  sources?: { url: string; title: string; published_at: string | null; observed_at: string }[];
  unknowns?: string[];
}

export function ConsultationReport({ value, savedShares, currentShares }: { value: ConsultationFindings; savedShares?:Record<string,number|null>;currentShares?:Record<string,number> }) {
  return <>
    <div className="subgrid"><div><strong>5営業日</strong><p>{value.market_5d}</p></div><div><strong>20営業日</strong><p>{value.market_20d}</p></div></div>
    <p>現金：{value.cash_rationale}</p>
    <section><h3 className="plain-section-title">企業ごとの調査・出典</h3><table className="subtable consultation-result-table"><thead><tr><th>銘柄・理由</th>{savedShares && <th>相談時保有</th>}{currentShares && <th>現在保有</th>}</tr></thead><tbody>
      {value.companies?.map(company => <tr key={company.symbol}><td><strong>{company.symbol}</strong><p>{company.rationale}</p><small>独立調査：{company.independent_research}<br />5日への影響：{company.impact_5d}<br />20日への影響：{company.impact_20d}<br />数値との照合：{company.numerical_comparison}</small></td>{savedShares && <td>{savedShares[company.symbol]==null ? "未記録" : `${savedShares[company.symbol]}株`}</td>}{currentShares && <td>{currentShares[company.symbol] ?? 0}株</td>}</tr>)}
      </tbody></table>
      {value.sources?.map((source, i) => <p key={`${source.url}-${i}`}>
        <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
        <small> 公開 {source.published_at ? dateTime(source.published_at) : "日時未確認"}・確認 {dateTime(source.observed_at)} JST</small>
      </p>)}
      {!!value.unknowns?.length && <p>未確認：{value.unknowns.join(" / ")}</p>}
    </section>
  </>;
}
