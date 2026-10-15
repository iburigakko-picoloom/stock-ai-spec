# StockAI Android APK

2026-10-15。D109が正本。既存React UIとPC版の計算moduleを端末へ同梱し、PC・クラウド計算の必須依存を外す。大規模な再学習はPCで行う。最終モデルは未採用で、現在は研究用。

## 保存地点と公開元

- Android化前の保存地点: `5b7aa4d6008e9e5e08291267f9bdc623428ac780`。
- GitHub mainは`0c9f88c`で69commit遅れ、remote-onlyは0。bundleと未commit差分を`.demo-artifacts/android-preflight`へ保全した。reset/pullで旧mainに戻していない。
- リポジトリ移転先: https://github.com/iburigakko-picoloom/stock-ai-spec （PUBLIC）。
- 初回配布: [StockAI 0.1.11（研究用）](https://github.com/iburigakko-picoloom/stock-ai-spec/releases/tag/android-v0.1.11)。[APK](https://github.com/iburigakko-picoloom/stock-ai-spec/releases/download/android-v0.1.11/StockAI.apk) / [SHA256SUMS](https://github.com/iburigakko-picoloom/stock-ai-spec/releases/download/android-v0.1.11/SHA256SUMS)。versionCode 10011、21,138,909 bytes、source `97f665f3055d2212882a6fc9b7e7224061bec912`。
- APK SHA-256: `bd86aeb312d4185a72c4a9c136aca2dce23e5db3fe0a640d5964d945bd868f9d`。公開ファイルをダウンロードし、update.json/SHA256SUMSとの一致、固定証明書、共有26 source/21依存のhashを確認済み。

## 端末内の構成

Capacitor8.5.3、Android8/API26以上、更新済みAndroid System WebViewを対象にする。Pyodide0.29.3の本体と21依存をSHA-256で固定し、すべてAPK内へ含める。初回起動時のCDN取得は不要。専用Web WorkerでPCの具体的な特徴量/費用/税/判断/台帳/APIを実行する。desktop ingestion facadeとfixture bootstrapだけをmobile namespaceへ置き換える。計算式は複製しない。現時点のPC/WASM一致試験は合成4銘柄・41/51列、小数7桁。実機での時間・RAM・大量データの能力は別途測定する。

APIキーはnative Android KeystoreのAES256-GCM鍵で暗号化し、JavaからJ-Quantsへだけ送信する。キー値の読出しAPI、ブラウザー保存、ログ記録は実装しない。口座/設定/台帳/市場データは端末の非公開SQLiteとKeystore暗号化した保存領域へ置く。保存の確定応答はnative SQLite transactionのcommit後。APK更新でapplicationId、署名、保存名を変更しない。自動OSバックアップは無効にする。

大きな暗号文をSQLiteの1行に置かず、256Ki文字の分割ごとに暗号化して保存する。GCMの認証情報へ世代番号と分割番号を含め、暗号化した見出しに全体hash/長さ/分割数を保存する。全分割と見出しは同じtransactionで確定する。分割欠落・改変・途中書込失敗・古い世代の書込を拒否する。現在の保存上限はbase64 state 128Mi文字、データ読出しはdatasetごと150万行。全市場の長期履歴がこの範囲と実機RAMへ収まるとは未確認で、上限・不足時は計算を止める。大量履歴の運用性能は実機検証事項である。

## 開発と検証

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/prepare_mobile.py --download
.\.venv\Scripts\python.exe -m scripts.generate_mobile_golden
cd web
npm ci
npm run typecheck
npm run lint
npm test
npm run build
npx playwright test --config playwright.mobile.config.ts
npx cap sync android
cd android
.\gradlew.bat :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest
# 起動済みの専用emulator/テスト端末がある場合だけ:
.\gradlew.bat :app:connectedDebugAndroidTest
```

runtimeのcore/lock/wheelを更新するときは、`mobile/runtime-packages.json`と`runtime-integrity.json`を同じ変更でレビューする。既存pinと異なるダウンロードは自動的に拒否する。テスト用の合成入力・モデルは`.demo-artifacts/android`にのみ生成し、APKに含めない。

## 自動署名配布

`.github/workflows/android-apk.yml`はmainのAndroid関連変更で起動する。PRは署名Secretsを利用せずテスト/ビルドする。React、PC/Python、通信遮断WASM一致、Androidコンパイル、暗号化backup、lintを通過後、mainでのみrelease鍵で署名し、ReleasesへAPK・`update.json`・`SHA256SUMS`・署名証明を公開する。draftへassetをすべてuploadしてから公開する。

versionCodeは`10000 + github.run_number`、versionNameは`0.1.<run_number>`。mainへの書戻しによる無限buildを避ける。公開したtag/APKを上書きせず、再実行が同じ版に衝突したら新しいworkflow runを開始する。既存の版より低いversionCodeは公開しない。

必要なActions Secretsは`ANDROID_KEYSTORE_BASE64`、`ANDROID_KEYSTORE_PASSWORD`、`ANDROID_KEY_ALIAS`、`ANDROID_KEY_PASSWORD`。`scripts/android_signing_setup.ps1 -RegisterGitHubSecrets`は初回だけ鍵を作り、同じ鍵を再利用する。値をstdinで渡し、秘密値を出力しない。公開できる証明書fingerprintだけを`mobile/signing-certificate.json`へ保存し、配布時に一致を検証する。

Windowsの証明書FriendlyNameだけではJavaのprivate-key bagの別名にならないことがある。setup scriptはGit for WindowsのOpenSSLで同じ鍵を`stockai`名のPKCS#12へ包み直し、中間pipeも暗号化する。変更前の暗号化ファイルを同じ非公開vaultへ保全し、証明書hashと署名検証の一致を確認してから置換/Secrets登録する。鍵や証明書の作り直しではない。公開証明書があるのに鍵がない場合は新規作成を拒否し、バックアップ復旧を求める。

## 署名鍵のバックアップ

1. `.demo-artifacts/android-signing/stockai-signing.p12`はパスワード暗号化済み。秘密鍵をGit/Release/チャットへ貼り付けない。
2. `credentials.dpapi`は現在のWindows本人アカウントだけが復号できる。これは別PCへ単純コピーしても復旧できない。
3. 本人のWindows上で下記を実行し、パスワード管理アプリへstorePassword/keyPassword/aliasを直接保存する。モデルやログへ値を渡さない。

```powershell
Add-Type -AssemblyName System.Security.Cryptography.ProtectedData
$protected = [IO.File]::ReadAllBytes('.demo-artifacts/android-signing/credentials.dpapi')
$clear = [Security.Cryptography.ProtectedData]::Unprotect($protected, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
[Text.Encoding]::UTF8.GetString($clear) | ConvertFrom-Json | Format-List
```

4. 暗号化p12を暗号化USB等へ2コピーし、パスワードは別の管理先に置く。Windowsが失われる前にこの手順を完了する。GitHub Secretsは値を読み戻せないのでバックアップの代わりにしない。
5. 復旧先で`keytool -list -storetype PKCS12 -keystore stockai-signing.p12`を実行し、公開fingerprintとの一致を確認してからSecretsへ戻す。新しい鍵へ置換すると既存APKを更新できない。

## アプリ内更新とデータ復元

起動時に固定GitHubリポジトリの最新版を確認する。版と変更内容を表示し、本人のタップ後にAPKを取得する。HTTPSの許可host、サイズ、SHA-256、applicationId、増加versionCode、インストール済み署名との一致を検証し、Androidのインストール確認画面へ渡す。端末側の提供元許可が必要な場合は設定画面を開き、戻ってから再度更新を押す。通信失敗では既存アプリと保存内容を維持する。

端末バックアップは本人が選んだファイルへ、12文字以上のパスワードからPBKDF2-HMAC-SHA256/210000回で鍵を導出してAES256-GCMで暗号化する。APIキーは含めない。復元はファイル選択→復号→明示確認→別workerでSQLite/台帳検証→native保存確定の順。パスワードを忘れたバックアップは復元できない。

## データ・モデルの公開範囲

APKと公開Gitへ、APIキー、口座情報、取得市場データ、署名鍵、学習済みの私有modelを含めない。`prepare_mobile.py`はソースallowlistだけを梱包し、package auditで禁止pathを検査する。

[J-Quants公式FAQ](https://jpx-jquants.com/ja)は取得データそのものの配布と、投資分析結果の継続反復的な第三者配信を禁止している。学習済みmodelの公開を明示的に許可する根拠は今回確認できていないため、公開可とは判定しない。`model-policy.json`のapproved_modelsは空のまま。将来のモデルは、採用証拠・公開/本人専用取込の条件・PCと実機の推論一致・hashを確認してから登録する。

## 実機の受入試験

本人指定はXiaomi 14T Pro。本人の最新指示により、USBなしで端末を操作して結果を報告する方式で進める。USB接続はPCからのログ取得や操作を必要とするときの選択肢であり、導入・通常利用・アプリ更新の前提にしない。Android版は端末の設定で確認し、未報告の間は不明とする。[USBなしの実機確認手順](evidence/android-apk-20261015/xiaomi-manual-acceptance.md)に沿って段階的に確認する。

ブラウザー/WASMやCIのAndroidエミュレーターを実機成功と数えない。本人の報告と自動検証の結果を区別する。debug APKは`jp.stockai.app.debug`へ分離し、合成3MiB状態の再読込・競合拒否・途中障害rollback・欠落/改変拒否をエミュレーターで確認する。releaseの保有情報やKeystoreには触れない。本人が指定したテスト端末だけで、次を記録する。

[初回公開CI 38682133797](https://github.com/iburigakko-picoloom/stock-ai-spec/actions/runs/38682133797)は全job成功。Python 50+6件、React18件、外部通信遮断WASM、Java backup crypto、API35 emulator保存3件、Android lint/build、公式apksignerと固定certificate照合を通過。認証なしのGitHub最新Release APIとupdate.json取得も成功した。アプリの更新検知/安全download/Android確認への接続は実装済みだが、インストール済み実機での更新・データ維持は未確認である。

初回台帳・補足設定と個人比較の全接続、実API403、採用model/配布条件、全市場長期履歴の端末能力は残る。APK公開を実予測の採用完了と扱わない。署名鍵を別媒体へ保管する作業も所有者による実施待ち。

| 項目 | 確認内容 | 状態 |
| --- | --- | --- |
| 初回導入 | 署名済みRelease APKの導入・起動、初回オフライン起動 | 導入・起動は2026-10-16本人報告で確認。オフラインは未確認 |
| 保存・再表示 | 「現在は保有なし」を保存→アプリを開き直して保持を確認 | 2026-10-16本人報告で確認 |
| 版更新 | 旧版に保有/設定/履歴を保存→新Release→Android確認→同じ内容を再表示 | 未実施 |
| 再起動 | 端末再起動後に保存内容とキー設定状態を確認 | 未実施 |
| 保存/復元 | 暗号化backup、変更後の復元、誤password・改変拒否 | 未実施 |
| 通信失敗 | 機内モード、API403、不足履歴で旧予測の時刻を更新しない | 未実施 |
| 端末内計算 | 実機の41/51特徴量・推論を同じPC入力と比較し、処理時間/RAMを測る | 未実施 |

実注文機能は追加しない。
