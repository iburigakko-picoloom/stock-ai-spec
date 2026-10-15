import Link from "next/link";
import { requireChatGPTUser } from "../chatgpt-auth";
import { loadPortfolio } from "@/lib/portfolio-store";
import { loadSettings } from "@/lib/settings-store";
import SettingsForm from "./settings-form";

export const dynamic = "force-dynamic";
export default async function SettingsPage() {
  const user = await requireChatGPTUser("/settings");
  let portfolio = null, settings = null, unavailable = false;
  try { [portfolio, settings] = await Promise.all([loadPortfolio(user.userId), loadSettings(user.userId)]); }
  catch { unavailable = true; }
  return <main className="shell portfolio-shell">
    <header className="topbar"><Link className="brand" href="/"><span className="brand-mark">株</span><span>株AI<small>DAILY RESEARCH</small></span></Link><span className="private-badge">● 本人専用</span></header>
    <nav><Link href="/">日次リサーチ</Link><Link href="/portfolio">口座・保有</Link><span aria-current="page">比較の設定</span></nav>
    <section className="hero"><div className="eyebrow">PERSONAL SETTINGS / 比較の準備</div><h1>費用と税を、<br/>自分の条件に。</h1><p className="intro">口座に残る現金や損益、費用の条件を記録します。分からない項目は空欄で保存し、あとから見直せます。</p></section>
    {unavailable ? <section className="panel"><h2>保存内容を読み込めませんでした</h2><p>入力を止めています。時間をおいて再読み込みしてください。</p></section>
      : !portfolio ? <section className="panel"><h2>先に口座・保有を記録</h2><p>「保有なし」だけでも保存できます。</p><Link className="secondary-button" href="/portfolio">口座・保有へ</Link></section>
      : <SettingsForm initialPortfolio={portfolio} initialSettings={settings}/>}
    <footer><span>本人専用の保存先に記録します。過去の設定は履歴として保持します。<br/>入力の保存は注文や運用開始ではありません。</span></footer>
  </main>;
}
