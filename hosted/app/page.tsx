import { getSafetyAcknowledgement } from '../db/operator-settings';
import { updateSafetyAcknowledgement } from './actions';
import { chatGPTSignInPath, chatGPTSignOutPath, getChatGPTUser } from './chatgpt-auth';
import Dashboard from './Dashboard';

export const dynamic = 'force-dynamic';

export default async function Home() {
  const user = await getChatGPTUser();
  const safety = user ? await getSafetyAcknowledgement(user.userId) : { acknowledged: false, updatedAt: null };
  return <Dashboard accountControl={
    <a className="accountLink" href={user ? chatGPTSignOutPath('/') : chatGPTSignInPath('/#settings')} target="_top">{user ? 'ログアウト' : 'ログイン'}</a>
  } safetyControl={
    <section className="card safetyControl">
      <h2>安全境界の確認</h2>
      <p>このサイトは実注文を行いません。口座・研究データはローカルに残ります。</p>
      <strong>{safety.acknowledged ? '確認済み' : '未確認'}</strong>
      {safety.updatedAt && <small>更新 {new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', dateStyle: 'short', timeStyle: 'short' }).format(new Date(safety.updatedAt))} JST</small>}
      {user ? <form action={updateSafetyAcknowledgement}>
        <input type="hidden" name="acknowledgement" value={safety.acknowledged ? 'revoked' : 'confirmed'} />
        <button className="button secondary" type="submit">{safety.acknowledged ? '確認を取り消す' : '内容を確認しました'}</button>
      </form> : <a className="button secondary" href={chatGPTSignInPath('/#settings')} target="_top">ログインして確認</a>}
      <small>保存するのは、この確認状態だけです。</small>
    </section>
  } />;
}
