# StockAI Android APK

2026-10-16。D109〜D111が正本。既存React UIとPC版の計算moduleを端末へ同梱し、PC・クラウド計算の必須依存を外す。大規模な再学習はPCで行う。最終モデルは未採用で、現在は研究用。

## 保存地点と公開元

- Android化前の保存地点: `5b7aa4d6008e9e5e08291267f9bdc623428ac780`。
- GitHub mainは`0c9f88c`で69commit遅れ、remote-onlyは0。bundleと未commit差分を`.demo-artifacts/android-preflight`へ保全した。reset/pullで旧mainに戻していない。
- リポジトリ移転先: https://github.com/iburigakko-picoloom/stock-ai-spec （PUBLIC）。
- 初回配布: [StockAI 0.1.11（研究用）](https://github.com/iburigakko-picoloom/stock-ai-spec/releases/tag/android-v0.1.11)。[APK](https://github.com/iburigakko-picoloom/stock-ai-spec/releases/download/android-v0.1.11/StockAI.apk) / [SHA256SUMS](https://github.com/iburigakko-picoloom/stock-ai-spec/releases/download/android-v0.1.11/SHA256SUMS)。versionCode 10011、21,138,909 bytes、source `97f665f3055d2212882a6fc9b7e7224061bec912`。
- APK SHA-256: `bd86aeb312d4185a72c4a9c136aca2dce23e5db3fe0a640d5964d945bd868f9d`。公開ファイルをダウンロードし、update.json/SHA256SUMSとの一致、固定証明書、共有26 source/21依存のhashを確認済み。
- 最新配布: [StockAI 0.1.12（研究用）](https://github.com/iburigakko-picoloom/stock-ai-spec/releases/tag/android-v0.1.12)。[APK](https://github.com/iburigakko-picoloom/stock-ai-spec/releases/download/android-v0.1.12/StockAI.apk) / [SHA256SUMS](https://github.com/iburigakko-picoloom/stock-ai-spec/releases/download/android-v0.1.12/SHA256SUMS)。versionCode 10012、21,150,645 bytes、source `ab2d5ca9ecd7ec107e187f7c0697e053c3288316`。
- 最新APK SHA-256: `d3a31fc717a28bd2453eb5ca1f69df9398893404051e8c880bad44e997162fe0`。配布APKの実取得とサイズ/hash、固定署名のbuild報告、共有27 source/mobile adapter6件/21依存の一致を確認。署名鍵とappIdは初回から不変。認証不要の最新Release API/update.jsonも10012を返す。旧版からの実機更新は本人による確認待ち。

## 端末内の構成

計算はD122のapplication-owned窓口へ集約する。UIはnativeへローカルAPI要求を送り、同じAPK内の隔離WebView/Workerと1つの暗号化writerを共有する。画面側に別のPython状態・世代counterを作らない。POSTの応答はnative commit後、保存失敗時は未確定interpreterを破棄し、最後のdurable stateから再起動する。復元は元のdurable dataを保持したまま別hostで検証するが、同時に2つのWASM heapを保持しない。この共通化だけでOSのbackground実行・日次予約・通知が完成したとは扱わない。

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
.\gradlew.bat :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.notClass=jp.stockai.app.DailyLifecycleTest
```

runtimeのcore/lock/wheelを更新するときは、`mobile/runtime-packages.json`と`runtime-integrity.json`を同じ変更でレビューする。既存pinと異なるダウンロードは自動的に拒否する。テスト用の合成入力・モデルは`.demo-artifacts/android`にのみ生成し、APKに含めない。

CIでは通常のinstrumented試験の後に、専用test APKと`scripts/android_lifecycle_check.py`で実プロセス終了・画面オフ・kernel reboot・強制停止後の明示再起動を確認する。このcontrollerは使い捨てGitHub AVD/API35だけを許可し、debugアプリを初期化する。ローカルや実機では実行せず、拒否条件を外さない。通常の試験と異なり、no-restart instrumentationで準備し、検証コードを差し込む前に外側からnative ACKと暗号化保存の世代更新を観測する。

結果はActionsの`android-test-reports`にある`lifecycle-report.json`と各段階のテキストで確認する。合成の受領済み休日データを使うため、示せるのは予約・保存・同じ取得ID/受領時刻の再開である。実J-Quants通信、実アカウント調査、採用モデルの株数、Xiaomiの実行時刻や性能の証拠は別に必要。host側のSQLite観測コピーは成果物へアップロードしない。

通常CIは`--dispatch-ready`を明示し、90秒の自然観測後も未配送なら、画面を2秒起こしてから消灯し、通常の遅延alarm配送を許す。なお未配送の場合だけ、元WorkRequest UUIDの現行mappingを照合してOSの`run -s`を送る。初回照合時にRUNNING等でまだ未送信なら、同じ200秒のACK窓の中で10秒ごとに元処理を観測し、OSの再試行がENQUEUEDとなり`get-job-state`が単独の`ready`を返した場合だけ、その未使用の1回を送る。既に送信済み（拒否を含む）のphaseでは追加送信しない。既存のjob消失raceに対する同UUIDの再照合1回も維持する。全制約を満たす場合だけ実行し、`-f`・再enqueue・電力policyや時計の変更は使わない。結果の`delivery_policy`と各phaseの`delivery`で画面起動も確認し、制御配送の成功を自動起動時刻の受入と数えない。手動workflowの`lifecycle_delivery=unforced`では、介入なしの200秒試験をそのまま実行する。初回の無介入試験は予約とページを保持したままOSが保留し、200秒以内の完了を確認できなかった。続く`-s`だけの試験も、経過済みのTIMING_DELAYが未解除で拒否されている。

実装a9c615cの[CI 38983024280](https://github.com/iburigakko-picoloom/stock-ai-spec/actions/runs/38983024280)で、既存native55件と3段階のprepare/verify計6呼出しがpass。processでは画面起動＋`-s`、rebootでは解錠/消灯後に追加の配送介入なし、force-stopでは70秒の停止観測と明示再表示後に追加の配送介入なしで、同じWorkRequestの完了・取得ID・元の受領時刻・本人revision・未完cursorを確認した。3段階のACK観測時はいずれもAsleep、通知未許可。全自動の画面オフ起動時刻、実API、ChatGPTや採用モデルの計算、Xiaomiの性能は別の未完受入である。

6a86762の[CI 38984534524](https://github.com/iburigakko-picoloom/stock-ai-spec/actions/runs/38984534524)では、同じ3段階へ暗号化した調査記録も追加してpass。各段階の前に予約/完成応答/ACK記録を準備し、実際のプロセス消失後に共有ChatGPTClientへ再度渡して、中断扱い・元の応答と時刻・再送抑止・hash/model/effort変更の拒否を検証した。完成応答を回収してACKした後も、次のOS中断で記録を保持する。`research_recovery`の照合件数と元の予約ID/準備時世代を結果に含め、raw応答は含めない。資格情報のない合成受領の回復試験であり、実アカウントの通信・検索成功とは区別する。

## 全市場履歴の容量確認

D126の可逆column形式は、raw/正規化の元の値・型・byte/hash・受領時刻と訂正順を保持しながら、重複列をまとめる。旧形式も読め、exportごと最大5batchずつtransactionで移行する。nativeの128MiB文字上限とSQLite復元の256MiB/file上限は維持し、保存時にも復元可能なサイズを確認する。

リポジトリrootで、未使用の出力先を指定して再現する。

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -m scripts.mobile_capacity_check --output .demo-artifacts/mobile-capacity-local --symbols 5000 --sessions 520 --checkpoint 130 --initial-download
```

CIでも同じ検証を実施し、`mobile-storage-capacity`へsource hashes付きreportだけを保存する。合成の平日カレンダー・財務開示を使ったPCのingest/export/restoreであり、取得済み市場データ、学習、holdout、本人端末の保存内容には触れない。SQLiteやcapsuleはartifactへuploadしない。

ローカルの5,000銘柄・300営業日では55,754,616 base64文字、mobile.sqlite344,470,272bytes、300日の復元がpassした。旧形式は90営業日のcheckpointで137,959,496文字となり、native上限134,217,728文字を超えた。checkpointの容量比較であり、毎回のnative暗号化保存やXiaomiの速度/メモリ成功を意味しない。150万行の株価PIT読込のPCピークは改善後も約2.16GBで、全特徴量計算・150万行guardを超える継続履歴・実機の受入は残る。

最新特徴量は、同じ合成履歴を使って別に確認する。`--initial-download`は全履歴を仮の判定日11:00に受領し、その日の11:30で計算する専用fixture。祝日を含まない合成カレンダーであり、実APIの受領証拠にしない。元SQLiteのhash不変、source hashes、段階別件数、processのピークをreportへ残す。

```powershell
.venv/Scripts/python.exe -m scripts.mobile_feature_check --source .demo-artifacts/mobile-capacity-local --report .demo-artifacts/mobile-capacity-local/latest-features.json --mobile-pipeline
```

既定は600秒/3500MiBで、上限超過またはmemory観測失敗時は専用probeだけを終了する。自己processのthreadによる観測であり、GILを保持する処理の間は上限を超えてから停止する可能性がある。OSの強制memory capとは扱わない。既存reportを上書きせず、本人の保存内容やAPIへ接続しない。`--mobile-pipeline`はアプリと同じfeature_inputs→calculate、指定なしは直接ProductionDataBundle→latest、`--reference-history`は全期間transformから最後の行を選ぶ比較用。CIではmobile経路を使い、`mobile-storage-capacity`へ容量と特徴量のreportだけを保存する。モデル推論・株数生成・native暗号化commit・端末上の予測完成は別の受入である。

D127の最新計算は全履歴を指標へ渡した後に最新行だけ保持し、財務をgroup参照する。市場母集団、数式や41/51列、受領時刻を省略しない。D128ではバックアップの復元上限128MiBと既存69byte overheadを保存側にも適用し、復元不能な大きさのファイルを作る前に拒否する。暗号形式は変えない。

D129では全sourceのID確定後、計算で参照する列だけをDataFrameで渡す。元のrecords JSONと同じ小数精度・ISO時刻・型推定を列ごとに再現し、重複する文字列と日時の値を共有する。既存records経路は残す。source IDは従来と同じ順序のrow hashを10,000行ずつ連結して計算し、ID定義・元データ・全市場/業種母集団を変更しない。小規模PCとWASMでrecords/framesの完全一致と復元後の出所不変を確認し、大規模PC試験と区別する。

D130のアプリ経路はmaster/priceを日単位で読む。型確認の後、同じSQLite snapshotの全batchを完全検証して元の全出所IDを求め、必要な列だけを保持する。全量readerの150万行guardを増やさず、保持arrayの合計を768MiBに制限する。これは総RSSの上限ではない。初期台帳の価格も同じ最新確定日と元record hashから読み、確定済み台帳に対する初期価格の再読込を省く。現行の72時間本人確認は維持する。

合成5,000銘柄/520営業日・260万行のPC計測では、capsule96,870,524文字、SQLite76,980,224bytes、520日復元がpass。最終アプリ入力→5/20日各5,000銘柄の特徴量は581.23秒・ピーク3,384,135,680bytesでpassし、元DBも不変。上限600秒/3500MiBは維持した。実際のモデル一式・毎回native保存・OS配送・Xiaomiでの時間/メモリと、さらに長い継続履歴は別に受け入れる。privateモデルは同梱しない。

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

D153では、nativeから受け取る保存状態をPythonへ256KiBずつ渡して一時ZIPへ復号し、SQLiteを分割展開して全memberのintegrity確認後に復元する。全量base64文字列とSQLiteのdeserializeによる重複保持をnative入力経路から除く。暗号形式・世代競合/確定保存・容量/時間上限は維持する。0a5d342の全量Android試験はB1書出し/認証previewまで進み、復元時renderer crashで未完。新経路のPC一致だけで全量Android/実機受入を成功扱いにしない。

6b250b9の[CI39040635265](https://github.com/iburigakko-picoloom/stock-ai-spec/actions/runs/39040635265)で、同じ5,000銘柄/520日・96,781,956文字の合成SQLiteによる全量native/B1復元・計算環境再作成・全17table照合が145.577秒、Java heap192MiBで成功した。44同梱Python sourceのGit一致と入力不変も確認。OS再起動後の元予約ACKは同runで失敗し、全体failure/release skip。全量保存の成功をOS復旧、Xiaomiや実市場/承認モデルの受入へ読み替えない。

起動時に固定GitHubリポジトリの最新版を確認する。版と変更内容を表示し、本人のタップ後にAPKを取得する。HTTPSの許可host、サイズ、SHA-256、applicationId、増加versionCode、インストール済み署名との一致を検証し、Androidのインストール確認画面へ渡す。端末側の提供元許可が必要な場合は設定画面を開き、戻ってから再度更新を押す。通信失敗では既存アプリと保存内容を維持する。

端末バックアップは本人が選んだファイルへ、12文字以上のパスワードからPBKDF2-HMAC-SHA256/210000回で鍵を導出してAES256-GCMで暗号化する。APIキーは含めない。復元はファイル選択→復号→明示確認→別workerでSQLite/台帳検証→native保存確定の順。パスワードを忘れたバックアップは復元できない。

## データ・モデルの公開範囲

APKと公開Gitへ、APIキー、口座情報、取得市場データ、署名鍵、学習済みの私有modelを含めない。`prepare_mobile.py`はソースallowlistだけを梱包し、package auditで禁止pathを検査する。

[J-Quants公式FAQ](https://jpx-jquants.com/ja)は取得データそのものの配布と、投資分析結果の継続反復的な第三者配信を禁止している。学習済みmodelの公開を明示的に許可する根拠は今回確認できていないため、公開可とは判定しない。`model-policy.json`のapproved_modelsは空のまま。将来のモデルは、採用証拠・公開/本人専用取込の条件・PCと実機の推論一致・hashを確認してから登録する。

## 実機の受入試験

本人指定はXiaomi 14T Pro。本人の最新指示により、USBなしで端末を操作して結果を報告する方式で進める。USB接続はPCからのログ取得や操作を必要とするときの選択肢であり、導入・通常利用・アプリ更新の前提にしない。Android版は端末の設定で確認し、未報告の間は不明とする。[USBなしの実機確認手順](evidence/android-apk-20261015/xiaomi-manual-acceptance.md)に沿って段階的に確認する。

ブラウザー/WASMやCIのAndroidエミュレーターを実機成功と数えない。本人の報告と自動検証の結果を区別する。debug APKは`jp.stockai.app.debug`へ分離し、合成3MiB状態の再読込・競合拒否・途中障害rollback・欠落/改変拒否をエミュレーターで確認する。releaseの保有情報やKeystoreには触れない。本人が指定したテスト端末だけで、次を記録する。

[初回公開CI 38682133797](https://github.com/iburigakko-picoloom/stock-ai-spec/actions/runs/38682133797)は全job成功。Python 50+6件、React18件、外部通信遮断WASM、Java backup crypto、API35 emulator保存3件、Android lint/build、公式apksignerと固定certificate照合を通過。認証なしのGitHub最新Release APIとupdate.json取得も成功した。アプリの更新検知/安全download/Android確認への接続は実装済みだが、インストール済み実機での更新・データ維持は未確認である。

0.1.11の初回台帳・補足設定は未接続だった。0.1.12へ、端末内の補足設定保存と初回台帳のpreview/明示確定、home表示、共有比較の不足理由表示を追加した。既存の入力は共有の不変revisionへ移行し、旧入力tableは保持する。空欄はnull、無料手数料は明示確認、口座・保有の更新後は補足設定を見直す。初回台帳は全口座と保有・現金・税を確認して一度だけ確定し、以後の入力欄の編集では上書きしない。

保有株の初期評価には保存済みの未調整終値を使い、参照日を表示する。全保有の同一日価格がない場合や5日超経過した場合は停止する。約定能力・企業行動の実証には使わない。確認内容は15分で失効し、入力・設定・価格の変化で再確認を要求する。台帳と確認receiptは同じSQLite transactionで保存し、native保存が確定してからUIへ完了を返す。新しいstateも既存の暗号化backupへ含め、APIキーは引き続き除外する。

最新原予測/市場根拠と個人比較の全接続、実API403、採用model/配布条件、全市場長期履歴の端末能力は残る。APK公開を実予測の採用完了と扱わない。署名鍵を別媒体へ保管する作業も所有者による実施待ち。0.1.12の新画面は実機で未確認。

| 項目 | 確認内容 | 状態 |
| --- | --- | --- |
| 初回導入 | 署名済みRelease APKの導入・起動、初回オフライン起動 | 2026-10-16本人報告で確認 |
| 保存・再表示 | 「現在は保有なし」を保存→アプリを開き直して保持を確認 | 2026-10-16本人報告で確認 |
| 版更新 | 旧版に保有/設定/履歴を保存→新Release→Android確認→同じ内容を再表示 | 未実施 |
| 再起動 | 端末再起動後に保存内容とキー設定状態を確認 | 保存内容は2026-10-16本人報告で確認。APIキーの維持は未確認 |
| 保存/復元 | 暗号化backup、変更後の復元、誤password・改変拒否 | 書出し・復元・誤password拒否は2026-10-16本人報告で確認。改変ファイルの実機試験は未確認 |
| 通信失敗 | 機内モード、API403、不足履歴で旧予測の時刻を更新しない | 機内モードは2026-10-16本人報告で確認。実API403・予測時刻は未確認 |
| 端末内計算 | 実機の41/51特徴量・推論を同じPC入力と比較し、処理時間/RAMを測る | 未実施 |

実注文機能は追加しない。


### 日次処理の開始・停止（PR内、実機受入待ち）

OS受入controllerは、準備時のscheduler番号だけで配送を試みず、元WorkRequest UUID・現行generation・DailyWorker classをWorkManager DBの隔離コピーから照合する。実行直前に番号が消えた場合も同UUIDを再観測し、制約が未充足なら既存のACK観測窓で待つ。初回のrun -sをまだ送っていないphaseでは、元処理の通信中断・再試行を同じACK窓内で追い、backoffを自然に満たしてOSがreadyを返した場合だけ、その1回を配送する。既に試行済みなら追加しない。controller自身は別処理の予約・強制run・時計/電源policy変更を行わず、実行したrun -sと観測だけの結果を記録で区別する。元WorkInfoのSUCCEEDEDと暗号化state/受領/調査の一致を引き続き要求する。新しい照合の実OS成功はCIで確認し、自然配送時刻やXiaomi成功とは読み替えない。

原予測を暗号化保存したら一度実行を区切り、当日11:30の保存済み原予測を次の実行で使って株数を計算する。株数保存の後も別の実行でChatGPT調査へ進む。「原予測を保存済み・株数判定待ち」は途中段階。株数の本人入力・台帳・モデル・市場根拠の照合は省略しない。実行中にJSTの日付が変わった場合、前日の結果を新しい当日の完成として通知しない。

長い数値計算の直前には、WorkManagerのdataSync foreground開始を待つ。固定のprivate通知は口座や保有を含まない。Androidが開始を拒否した場合は計算せず、「Androidの計算待ち」と保存済み状態の確認を表示し、既存の日次上限付き再試行へ戻す。foregroundはAndroid16のjob quotaや定刻実行を保証しない。通知表示/実OS admission・継続は実機で別途確認する。API35のnative試験へ520日capsuleと同じ96,870,524文字のopaque ASCII保存・再open・競合拒否・全digest照合を追加し、phase/最大Java heap/秒だけをreportに残す。実SQLite capsule・WebView bridge・全取得日のcommitや実forecastとは区別する。

2026-10-17のdesktop検証では、実際の合成520日SQLite capsule96,870,524文字を配布版compute host/WASMへ初期化し、合成の保有なし入力をPOSTして別browser contextへ再読込した。nativeと同じCSP、520日と全受領記録、全mobile17tableのtyped-cell hash不変を確認。元DBはcopyして保持し、同梱mobile15 sourceの一致も確認した。51.68秒でpassしたが、native bridgeはmockでありJava/Keystore/実機の証拠ではない。最初のCDP巨大fulfill試作の接続終了も原本へ残し、loopback streamの試験harnessで切り分けた。原本は`.demo-artifacts/mobile-native-history-capsule-20261017`。実注文能力false、モデル採用0件を維持する。

口座・保有・初回台帳・補足設定・確認済みモデル一式とJ-Quants APIキーを用意して、今日または設定の「開始」を押す。通知はAndroidで許可でき、拒否しても保存は継続する。初回は保存済み取得範囲の開始日（未設定なら420日前）から昨日までを小分けに取得し、以後は未保存の差分を取得する。10:30〜11:30の当日一覧を優先し、締切内の根拠がない日は当日計算を完成扱いにしない。数値保存とChatGPT調査の状態は別。ChatGPT連携とモデル/推論量の設定があれば、上位20と全保有の独立調査・数値照合へ自動で進む。上限・認証切れ・通信/回答不成立は未完として保存し、調査画面で明示的に回復する。日ごとの条件を固定し、自動再調査で別の設定へ切り替えない。

OS予約のため定刻実行は保証されない。画面では対象日と実際の状態を確認する。停止は次のページ・処理の境界に効き、確定済みの取得と結果を残す。復元・APIキー削除時は自動処理を停止する。通常のプロセス停止や再起動はWorkManagerの永続予約で回復する設計だが、実機受入は未完。Androidで「強制停止」した場合はアプリを開く。API401/403は設定を直して「続きから再開」。一時失敗はJST1日3回までで、翌日を待つか停止後に本人が再開する。72時間以内の本人入力照合と採用ゲートは維持する。

D158では、OSがWorkerを中断した際に、そのWorkerが待つ端末内計算の要求だけを取り消す。待機中の要求は実行せず、実行中なら未確定の計算環境を破棄し、確定保存から次の要求へ進む。保存済み世代は戻さず、別画面の要求やChatGPTの復旧journalには適用しない。725b8fd/CI39079227108でnative82件とOS3段階、同APKの全量B1復元が139.772秒/192MiBで成功し全17tableを照合。後続4e5a11d/CI39081593387でもnative82件と元予約のOS3段階が世代5/8/11・pending0で成功したが、rebootは画面wake後の観測で、無介入の再開とは区別する。4e5a11dの独立全量B1工程、反復安定性とXiaomi受入は別途確認する。
