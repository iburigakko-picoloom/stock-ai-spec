import Link from "next/link";
import { requireChatGPTUser } from "../chatgpt-auth";
import { loadPortfolio } from "@/lib/portfolio-store";
import PortfolioForm from "./portfolio-form";

export const dynamic = "force-dynamic";
export default async function PortfolioPage() {
  const user = await requireChatGPTUser("/portfolio");
  let saved = null;
  let unavailable = false;
  try { saved = await loadPortfolio(user.userId); } catch { unavailable = true; }
  return <main className="shell portfolio-shell">
    <header className="topbar"><Link className="brand" href="/"><span className="brand-mark">株</span><span>株AI<small>DAILY RESEARCH</small></span></Link><span className="private-badge">● 本人専用</span></header>
    <nav><Link href="/">← 日次リサーチ</Link></nav>
    <section className="hero"><div className="eyebrow">MY PORTFOLIO / 手動登録</div><h1>口座と保有を、<br/>ここに記録。</h1><p className="intro">「保有なし」から始められます。口座区分や銘柄はあとから追加・修正できます。分からない金額は空欄のままで大丈夫です。</p></section>
    <p className="notice">口座番号・パスワードは入力不要です。ここに記録しても注文や証券口座の変更は行いません。</p>
    {unavailable ? <section className="panel"><h2>保存内容を読み込めませんでした</h2><p>古い内容を上書きしないよう入力を止めています。時間をおいてページを再読み込みしてください。</p></section> : <PortfolioForm initial={saved}/>}
    <footer><span>本人専用の保存先に記録します。過去の記録は履歴として保持します。<br/>モデルの原予測とは別に保存します。</span></footer>
  </main>;
}
