'use client';

import { type ReactNode, useState, useSyncExternalStore } from 'react';

const navigation = [
  ['home', 'ホーム', 'M3 10 12 3l9 7v10H3Z M9 20v-7h6v7'],
  ['today', '今日', 'M8 3h8v4H8Z M8 5H5v16h14V5h-3 M8 12l2 2 5-5 M8 18h8'],
  ['ranking', 'ランキング', 'M4 20V12h4v8 M10 20V4h4v16 M16 20V8h4v12'],
  ['validation', '検証', 'M4 3v17h17 M7 15l4-5 4 3 5-7'],
  ['settings', '設定', 'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6'],
] as const;

function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener);
  return () => window.removeEventListener('hashchange', listener);
}
function currentPage() {
  const name = window.location.hash.slice(1);
  return navigation.some(([key]) => key === name) ? name : 'home';
}

function Tabs({ label, options, value, onChange, panelId }: {
  label: string; options: readonly string[]; value: string;
  onChange: (value: string) => void; panelId: string;
}) {
  return <div className="tabs" role="tablist" aria-label={label}>
    {options.map((title, index) => <button key={title} role="tab" type="button" id={panelId + '-' + index} aria-controls={panelId} aria-selected={title === value} tabIndex={title === value ? 0 : -1} onClick={() => onChange(title)} onKeyDown={(event) => {
      const next = event.key === 'ArrowRight' ? (index + 1) % options.length : event.key === 'ArrowLeft' ? (index - 1 + options.length) % options.length : event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : null;
      if (next === null) return;
      event.preventDefault();
      onChange(options[next]);
      event.currentTarget.parentElement?.querySelectorAll('button')[next]?.focus();
    }}>{title}</button>)}
  </div>;
}

function Empty({ title, detail }: { title: string; detail: string }) {
  return <section className="empty card" role="status"><span className="emptyMark" aria-hidden="true">—</span><h2>{title}</h2><p>{detail}</p></section>;
}

export default function Dashboard({ accountControl, safetyControl }: { accountControl: ReactNode; safetyControl: ReactNode }) {
  const page = useSyncExternalStore(subscribe, currentPage, () => 'home');
  const [rank, setRank] = useState('総合');
  const [validation, setValidation] = useState('提案Paper');
  const [settings, setSettings] = useState('口座・資金');
  const rankTabs = ['総合', '5日', '20日', '前場'];
  const validationTabs = ['提案Paper', '実運用', '過去検証'];
  const settingsTabs = ['口座・資金', 'AI・データ', '通知'];

  return <div className="shell">
    <a className="skipLink" href="#main">本文へ移動</a>
    <header className="topbar">
      <a className="brand" href="#home"><span className="brandMark" aria-hidden="true">株</span><strong>株AI</strong></a>
      <span className="manualOnly">自動発注なし</span>{accountControl}
    </header>
    <nav className="bottomNav" aria-label="メインナビゲーション">
      {navigation.map(([key, title, path]) => <a key={key} href={'#' + key} aria-current={page === key ? 'page' : undefined}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={path} /></svg><span>{title}</span>
      </a>)}
    </nav>
    <main className="content" id="main">
      <header className="pageHeader"><span>公開版</span><h1>{navigation.find(([key]) => key === page)?.[1]}</h1></header>
      <p className="connectionNotice">ローカルの実データは未接続です。</p>

      {page === 'home' && <>
        <section className="card balance" aria-label="実資産"><span>総資産</span><strong>—</strong><div className="metrics"><div><span>現金</span><b>—</b></div><div><span>株式</span><b>—</b></div></div></section>
        <a className="nextAction" href="#today">今日の提案を確認<span aria-hidden="true">→</span></a>
        <Empty title="保有データは未接続です" detail="保有株・口座情報は公開しません。" />
      </>}

      {page === 'today' && <>
        <section className="card proposal" aria-label="今日の提案"><span className="statusLabel">NO PROPOSAL</span><h2>提案はまだ表示できません</h2><p>実データ・採用モデルの接続待ちです。</p><a className="button secondary" href="#settings">接続状況を確認</a></section>
        <details className="details"><summary>提案を表示しない理由</summary><ul><li>ローカルの提案・口座台帳と未接続</li><li>このサイトに採用モデルを未登録</li><li>11:30の前場データが未接続</li></ul><p>前日の提案や架空の数値では補いません。</p></details>
      </>}

      {page === 'ranking' && <>
        <Tabs label="ランキング期間" options={rankTabs} value={rank} onChange={setRank} panelId="ranking-panel" />
        <div id="ranking-panel" role="tabpanel" aria-labelledby={'ranking-panel-' + rankTabs.indexOf(rank)}><Empty title={rank + 'ランキングは未接続です'} detail="認証済みの予測が接続されると表示します。" /></div>
        <p className="footnote">予測順位と売買の判断は別です。</p>
      </>}

      {page === 'validation' && <>
        <Tabs label="検証の種類" options={validationTabs} value={validation} onChange={setValidation} panelId="validation-panel" />
        <div id="validation-panel" role="tabpanel" aria-labelledby={'validation-panel-' + validationTabs.indexOf(validation)}><Empty title={validation + 'の記録は未接続です'} detail="未検証の成績を0%とは表示しません。" /></div>
      </>}

      {page === 'settings' && <>
        <Tabs label="設定の分類" options={settingsTabs} value={settings} onChange={setSettings} panelId="settings-panel" />
        <div id="settings-panel" role="tabpanel" aria-labelledby={'settings-panel-' + settingsTabs.indexOf(settings)}>
          {settings === '口座・資金' && <><section className="card"><dl className="statusList"><div><dt>資金・保有株</dt><dd>未接続</dd></div><div><dt>口座・税・NISA</dt><dd>未接続</dd></div></dl></section><p className="footnote">口座情報はこの公開サイトに入力しません。</p></>}
          {settings === 'AI・データ' && <><section className="card"><dl className="statusList"><div><dt>J-Quants V2 日足</dt><dd>ローカルのみ</dd></div><div><dt>研究データ・モデル</dt><dd>同期なし</dd></div><div><dt>前場データ</dt><dd>未接続</dd></div><div><dt>実注文</dt><dd>対象外</dd></div></dl></section><details className="details"><summary>公開範囲・安全設定</summary>{safetyControl}</details></>}
          {settings === '通知' && <Empty title="プッシュ通知は未設定です" detail="このサイトからの外部配信は行いません。" />}
        </div>
      </>}
    </main>
  </div>;
}
