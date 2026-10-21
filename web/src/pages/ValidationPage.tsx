import { type ReactNode, useState } from "react";
import { Metric, PageHeader, StatePanel, TabBar, dateTime, pct, yen } from "../components";
import { useApiData } from "../hooks";
import type { PaperSeriesPoint, PaperSummary } from "../types";

function PaperPerformanceChart({ series }: { series: PaperSeriesPoint[] }): ReactNode {
  if (series.length < 2) return <div className="chart-empty" role="status"><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><rect x="7" y="31" width="7" height="12" rx="2" /><rect x="21" y="19" width="7" height="24" rx="2" /><rect x="35" y="5" width="7" height="38" rx="2" /></svg><p>観測データが揃うと表示します</p><small>チャートに必要な観測が不足しています。1営業日Paperを2件以上記録すると表示します。</small></div>;
  const width = 320;
  const height = 140;
  const inset = 12;
  const values = [0, ...series.flatMap((item) => [item.proposal_return, item.benchmark_return])];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const span = Math.max(maximum - minimum, 0.0001);
  const x = (index: number): number => inset + index * ((width - inset * 2) / (series.length - 1));
  const y = (value: number): number => height - inset - ((value - minimum) / span) * (height - inset * 2);
  const points = (field: "proposal_return" | "benchmark_return"): string => series.map((item, index) => `${x(index)},${y(item[field])}`).join(" ");
  return <figure className="paper-chart">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="1営業日Paperの累積提案リターンとTOPIX比較">
      <line x1={inset} y1={y(0)} x2={width - inset} y2={y(0)} className="paper-chart__zero" />
      <polyline points={points("benchmark_return")} className="paper-chart__benchmark" />
      <polyline points={points("proposal_return")} className="paper-chart__proposal" />
    </svg>
    <figcaption><span><i className="legend legend--proposal" />提案戦略</span><span><i className="legend legend--benchmark" />TOPIX</span><small>{series[0].observed_at.slice(0, 10)}〜{series.at(-1)?.observed_at.slice(0, 10)}</small></figcaption>
  </figure>;
}

export function ValidationPage(): ReactNode {
  const [mode, setMode] = useState("paper");
  const { data, error, loading } = useApiData<PaperSummary & { blockingReason?: string }>(`/api/v1/validation?mode=${mode}`);
  const observed = (data?.observations ?? 0) > 0;
  const weekly = data?.weekly_readouts ?? [];
  const monthly = data?.monthly_readouts ?? [];
  return (
    <div className="page">
      <PageHeader eyebrow="提案と実績を振り返る" title="検証" />
      <TabBar label="検証の種類" options={[["paper", "提案Paper"], ["live", "実運用"], ["historical", "過去検証"]]} value={mode} onChange={setMode} panelId="validation-panel" />
      <div id="validation-panel" role="tabpanel" aria-labelledby={`validation-panel-${mode}`}>
      {loading ? <StatePanel title="検証記録を読み込んでいます" /> : error ? <StatePanel tone="error" title="検証記録を取得できません" detail={error} /> : data?.blockingReason ? <StatePanel title={data.blockingReason} /> : mode === "paper" && data ? <>
        <section className="validation-hero">
          <span>提案戦略（1営業日・記録済み将来観測）</span>
          <strong>{pct(observed ? data.proposal_return : null)}</strong>
          {observed ? <small>TOPIX {pct(data.benchmark_return)} / 超過 {pct(data.excess_return)}</small> : <small>Paperの観測はまだありません</small>}
        </section>
        <section className="section">
          <div className="section-heading"><div><span>FORWARD PAPER</span><h2>累積推移</h2></div></div>
          <PaperPerformanceChart series={data.series ?? []} />
        </section>
        <section className="section">
          <div className="metric-grid metric-grid--2">
            <Metric label="TOPIXとの差" value={pct(observed ? data.excess_return : null)} />
            <Metric label="最大ドローダウン" value={pct(observed ? data.maximum_drawdown : null)} />
            <Metric label="平均コスト誤差" value={yen(observed ? data.mean_cost_error : null)} />
            <Metric label="平均税影響誤差" value={yen(observed ? data.mean_tax_error : null)} />
          </div>
        </section>
        <details className="section metadata-details">
          <summary>モデル診断の詳細</summary>
          <div className="section-heading">
            <div><span>MODEL MONITOR</span><h2>Champion / Challenger</h2></div>
          </div>
          <dl className="summary-list">
            <div><dt>Champion版 / 観測数</dt><dd>{data.champion_version ?? "—"} / {data.champion_observations ?? "—"}件</dd></div>
            <div><dt>Champion 平均絶対誤差</dt><dd>{pct(data.champion_mean_absolute_error)}</dd></div>
            <div><dt>Challenger版 / 比較数</dt><dd>{data.challenger_version ?? "—"} / {data.challenger_observations ?? "—"}件</dd></div>
            <div><dt>Challenger 平均絶対誤差</dt><dd>{pct(data.challenger_mean_absolute_error)}</dd></div>
            <div><dt>Challenger 勝率</dt><dd>{pct(data.challenger_better_rate)}</dd></div>
            <div><dt>ドリフト判定</dt><dd>{data.drift_status === "INSUFFICIENT_OBSERVATIONS" ? "観測不足" : data.drift_status === "STABLE" ? "安定" : data.drift_status === "DEGRADED" ? "誤差が増加" : "未確認"}</dd></div>
            <div><dt>直近/直前の誤差比</dt><dd>{data.drift_ratio == null ? "—" : `${data.drift_ratio.toFixed(2)}x`}</dd></div>
          </dl>
          <p className="explain">同じ現行モデル版の{data.drift_window ?? "—"}件ずつを比較します。Challenger比較は同じ組合せの分母だけです。自動的なモデル昇格には使いません。</p>
        </details>
        <details className="section metadata-details">
          <summary>週次・月次</summary>
          <div className="section-heading">
            <div><span>PERIODIC READOUT</span><h2>週次・月次</h2></div>
          </div>
          {weekly.length === 0 && monthly.length === 0 ? <StatePanel title="確定した将来観測はまだありません" detail="EOD観測を不変記録すると、週次・月次に集計します。" /> : <div className="readout-list">
            {[...weekly.slice(0, 3), ...monthly.slice(0, 3)].map((item) => <article key={`${item.period}-${item.period_key}`}>
              <div><strong>{item.period_key}</strong><span>{item.period === "weekly" ? "週次" : "月次"}・{item.observations}件</span></div>
              <div><b>{pct(item.proposal_return)}</b><small>超過 {pct(item.excess_return)}</small></div>
            </article>)}
          </div>}
        </details>
        <section className={`readiness ${data.is_decision_ready ? "readiness--ready" : ""}`}>
          <strong>{data.is_decision_ready ? "最低観測数に到達" : "観測継続中"}</strong>
          <span>{data.observations} / {data.minimum_observation_count ?? "—"}件 ・ 更新 {dateTime(data.updated_at)}</span>
          <p>最低件数への到達は収益性やChampion採用を意味しません。</p>
          {!data.model_monitoring_ready && <p>モデル版ごとの監視・比較件数はまだ不足しています。</p>}
        </section>
      </> : <StatePanel title="実運用データはまだありません" detail="実行結果を記録すると表示されます。" />}
      </div>
    </div>
  );
}
