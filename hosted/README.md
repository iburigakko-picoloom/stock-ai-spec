# 株AI hosted companion

データ準備状況と安全停止理由を公開閲覧できるSites companionです。
実データを処理するlocalhost PWA / FastAPIや、local append-only台帳の代替ではありません。

## UI

ローカルPWAと同じ白・薄灰・青のデザインで、ホーム / 今日 / ランキング / 検証 / 設定を切り替えます。
設定は口座・資金 / AI・データ / 通知に分け、説明と安全確認を折りたたみます。
サイト未接続の金額は`—`、提案は`NO PROPOSAL`と表示します。研究の進捗は同期せず、古い取得期間や進捗数値を固定表示しません。
URL hashは画面選択のみで、private台帳への接続や保存権限を付与しません。

## Safety boundary

- 実注文、broker接続、自動売買を実装しない
- `JQUANTS_API_KEY`、`data/live`、model artifact、実口座CSVを保存・送信しない
- 不足データをfixture、前日提案、推測値で補わない
- Sites access policyはpublic。本人別の確認状態を保存する操作だけChatGPT認証を要求する
- D1へ保存するのは認証済みuser別の安全境界確認状態だけ

## Local verification

```text
npm install
npm run lint
npm run build
npm audit --omit=dev
npm audit
```

Local preview uses the generated Sites development identity and a project-local D1 emulator:

```text
npm run dev -- --host 127.0.0.1
```
