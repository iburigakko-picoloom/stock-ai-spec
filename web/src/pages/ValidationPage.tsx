import { type ReactNode, useState } from "react";
import { Link, useLocation } from "react-router-dom";
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
  const detailed=useLocation().pathname === "/validation/details";
  const analysis=new URLSearchParams(useLocation().search).get("analysis");
  const [mode,setMode]=useState(detailed && ["models","historical"].includes(analysis ?? "") ? analysis! : "paper");
  const {data,error,loading}=useApiData<PaperSummary & {blockingReason?:string}>(`/api/v1/validation?mode=${mode === "models" ? "paper" : mode}`);
  const observed=(data?.observations ?? 0)>0;
  const weekly=data?.weekly_readouts ?? [], monthly=data?.monthly_readouts ?? [];
  const options=detailed ? [["paper","予測精度"],["models","モデル比較"],["historical","過去検証"]] as const : [["paper","提案成績"],["live","実運用成績"]] as const;
  return <div className="page validation-page"><PageHeader title={detailed ? "詳細分析" : "検証"} backTo={detailed ? "/validation" : undefined} />
    <TabBar label="検証の種類" options={options} value={mode} onChange={setMode} panelId="validation-panel" />
    <div id="validation-panel" role="tabpanel" aria-labelledby={`validation-panel-${mode}`}>
      {loading && data && <p role="status">前回の表示です・更新を確認中…</p>}
      {loading && !data ? <StatePanel title="検証記録を読み込んでいます" /> : error ? <StatePanel tone="error" title="検証記録を取得できません" detail={error} /> : data?.blockingReason ? <StatePanel title={data.blockingReason} /> : (mode === "paper" || mode === "models") && data ? <>
        {!detailed && <section className="mock-card validation-overview">
          <div className="link-row"><small>提案戦略・1営業日Paper</small><small>{dateTime(data.updated_at)} 更新</small></div>
          <div className="validation-hero"><strong>{pct(observed ? data.proposal_return : null)}</strong><small>期間リターン</small></div>
          <PaperPerformanceChart series={data.series ?? []} />
          <div className="metric-grid metric-grid--2"><Metric label="TOPIXとの差" value={pct(observed ? data.excess_return : null)} /><Metric label="最大下落率" value={pct(observed ? data.maximum_drawdown : null)} /></div>
          {!observed && <p className="setting-footnote">Paperの観測はまだありません。</p>}
        </section>}
        {!detailed && <section className="mock-card"><h2>週次・月次</h2>
          {weekly.length===0 && monthly.length===0 ? <p className="setting-footnote">確定した将来観測はまだありません</p> : <>{([["週次",weekly],["月次",monthly]] as const).map(([title,rows])=><div key={title}><h3>{title}</h3><table className="compact-table"><thead><tr><th>期間</th><th>リターン</th><th>TOPIXとの差</th></tr></thead><tbody>{rows.map(row=><tr key={row.period_key}><td>{row.period_key}<small> · {row.observations}件</small></td><td>{pct(row.proposal_return)}</td><td>{pct(row.excess_return)}</td></tr>)}</tbody></table></div>)}</>}
        </section>}
        {detailed && mode === "paper" && <section className="section"><h2>予測精度</h2><dl className="summary-list"><div><dt>観測件数</dt><dd>{data.observations}件</dd></div><div><dt>平均絶対誤差</dt><dd>{pct(data.champion_mean_absolute_error)}</dd></div><div><dt>費用予測誤差</dt><dd>{yen(observed ? data.mean_cost_error : null)}</dd></div><div><dt>税予測誤差</dt><dd>{yen(observed ? data.mean_tax_error : null)}</dd></div><div><dt>予測対象</dt><dd>記録済みの将来観測</dd></div></dl></section>}
        {detailed && mode === "models" && <section className="section"><h2>Champion / Challenger</h2><dl className="summary-list">
          <div><dt>Champion版 / 観測数</dt><dd>{data.champion_version ?? "—"} / {data.champion_observations ?? "—"}件</dd></div><div><dt>Champion 平均絶対誤差</dt><dd>{pct(data.champion_mean_absolute_error)}</dd></div>
          <div><dt>Challenger版 / 比較数</dt><dd>{data.challenger_version ?? "—"} / {data.challenger_observations ?? "—"}件</dd></div><div><dt>Challenger 平均絶対誤差</dt><dd>{pct(data.challenger_mean_absolute_error)}</dd></div><div><dt>Challenger 勝率</dt><dd>{pct(data.challenger_better_rate)}</dd></div>
          <div><dt>ドリフト判定</dt><dd>{data.drift_status === "INSUFFICIENT_OBSERVATIONS" ? "観測不足" : data.drift_status === "STABLE" ? "安定" : data.drift_status === "DEGRADED" ? "誤差が増加" : "未確認"}</dd></div><div><dt>直近/直前の誤差比</dt><dd>{data.drift_ratio == null ? "—" : `${data.drift_ratio.toFixed(2)}x`}</dd></div>
        </dl><p className="setting-footnote">同じ現行モデル版の{data.drift_window ?? "—"}件ずつを比較します。自動的なモデル昇格には使いません。</p></section>}
        {detailed && <p className="setting-footnote">{data.is_decision_ready ? "最低観測数に到達" : "観測継続中"} · {data.observations} / {data.minimum_observation_count ?? "—"}件{!data.model_monitoring_ready && " · モデル監視の比較件数は不足しています"}</p>}
      </> : <StatePanel title="実運用データはまだありません" detail="実行結果を記録すると表示されます。" />}
    </div>
    {!detailed && <section className="mock-card"><h2>詳細分析</h2><Link className="menu-link" to="/validation/details">予測精度 <span>›</span></Link><Link className="menu-link" to="/validation/details?analysis=models">モデル比較 <span>›</span></Link><Link className="menu-link" to="/validation/details?analysis=historical">過去検証 <span>›</span></Link></section>}
    <div className="link-row"><Link className="quiet-link" to="/settings?edit=model">モデル管理 ›</Link>{detailed && <Link className="quiet-link" to="/validation">振り返りに戻る</Link>}</div>
  </div>;
}
