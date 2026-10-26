# 採用版UIと既存機能の対応（2026-10-26）

参照：添付 `1-stock-ui-mock-offline.html` の `selectedVariants`（28指定＋設定トップ＝29画面）。公開URLは取得不可。HTMLはソースとして確認し、架空値・デモ状態遷移・比較/案切替を移植しない。設定トップは現行を保持する。

| 採用画面 | 既存の接続先・保存処理 | 採用する構成 |
| --- | --- | --- |
| ホーム B | HomePage / home API | 白い資産合計、現金/株式、保有一覧、資産管理 |
| 今日 A | TodayPage / today API | 市場・提案・本人判断への導線 |
| ランキング A | Rankings / mobile/ranking/5d・20d | 3モデル、検索、表、共通銘柄詳細 |
| 検証 A | ValidationPage / validation API | 主指標・推移・詳細分析。未観測は未観測 |
| 設定 | MobileDevicePanel | 現行トップを維持 |
| 銘柄詳細 A | StockDetailPage / stocks API | 数値予測・保有・提案・調査を区別 |
| 資産管理 A | HoldingsPage / CurrentAccountPanel | 初回登録・残高修正・履歴への入口 |
| 資産登録 B | InitialHoldings / MobilePersonalPanel | 一覧フォーム、初回台帳確認 |
| 入出金 B | CurrentAccountPanel cash | 現在残高の確認・差分保存。入出金額からの自動推定はしない |
| 保有修正 B | CurrentAccountPanel holdings | 現在保有・取得単価の確認と修正 |
| 修正履歴 A | current ledger / operations store | 保存済み台帳履歴。読み取り専用 /api/v1/portfolio/history を追加 |
| 取引記録 B | ExecutionPage / executions・apply-executions | 実約定入力・差分反映・同画面結果 |
| 取引履歴 B | decisions/{id}/executions | 保存済み約定。読み取り専用 /api/v1/executions を追加 |
| 判断確認 A | DecisionReviewPage / review・decisions | 株数変更・再計算・同画面保存結果 |
| ChatGPT相談 A | ManualChatGPTPage | 相談文・回答JSON・独立保存 |
| 相談履歴 B | ManualChatGPTPage / manual consultation | 保存済み相談の選択・詳細 |
| 運用条件 B | capital/risk / MobilePersonalPanel | 既存入力だけの簡潔なフォーム |
| 口座税手数料 B | MobilePersonalPanel | 口座別税・NISA・費用の既存設定 |
| データ更新 B | MobileMarketPanel / DailyControls | 実進捗・停止/再開・通知 |
| ChatGPT設定 B | ChatGPTPanel | 接続・許可・手動相談 |
| バックアップ B | MobileBackupPanel | 暗号化書出し・検証後復元 |
| アプリ情報 B | about / native update | 実際の更新状態・ライセンス |
| モデル管理 C | MobileModelPanel | モデル/計算の操作と確認、狭幅では1列 |
| データ修復 B | MobileMarketPanel | 履歴・指定日・訂正取得・特徴量 |
| 計算方式 B | MobilePersonalPanel / model settings | 既存方針の明示選択、無断変更なし |
| CSV取込 B | DataOperationsPage | preview・競合照合・確定保存 |
| 処理状況 B | DataOperationsPage / DailyPanel | 実ジョブ状態・停止理由 |
| 詳細分析 B | ValidationPage details | 実指標・モデル診断・週/月次 |
| 調査履歴 B | CompanyResearchPanel | 保存済み調査・中断/再開の実状態 |

## 接続上の確認点

- 20日順位は実予測のrank_score_20d（欠損を値予測で代用しない）、5日/20日値はexpectedReturn（比率→%）を使用。ChatGPT順は別タブで明示する。
- 原予測、ChatGPT回答、本人判断、約定は既存の別レコードを維持する。
- 判断保存は台帳を変更しない。約定記録と未反映約定の反映を区別し、失敗時に記録を重複送信しない。
- 残高のavailable_cashは既存契約を維持し、reserved_cashを資産へ加算しない。
- 設定トップ以外の装飾と説明用の折りたたみを簡素化。必要な情報や操作自体は削除しない。
- 画面復帰は保持されたstateとルート別スクロールを使用。画面テストのfixtureは製品APKに入れない。

## 実施結果

- 資産管理・現金変更・残高履歴・取引履歴・相談履歴・調査履歴・CSV・処理状況・詳細分析の経路を既存の保存処理へ接続。
- 判断は同画面に保存結果を表示。約定は記録後、現在時点までの未反映分を反映。記録成功/反映失敗の再試行では約定POSTを再送しない。
- ランキング・保有・設定画面の状態を保持。ルート別スクロールと銘柄詳細の口座選択・戻り先を保持。
- Vitest 26ファイル191件、Pythonのランキング/API/照合/保有80件、ESLint・TypeScript・変更PythonのRuff成功。
- Playwright: 29対応画面を320/390px・100/150%文字で検査。Android 35 SystemWebViewでも320dp・100/150%で全経路を実表示、各画面上/中/下を端末キャプチャ。検索・モデル選択・スクロール復帰も成功。
- Android証拠: .demo-artifacts/ui-adopted-native-capture/（テスト専用データ・専用エミュレーター、本人の保存データは使用しない）。

## 既存機能に合わせた対応と確認範囲

- 初回資産登録と保有修正は同じ /holdings で、台帳の有無に応じて実フォームを切り替える。初回確定は既存の口座設定から行う。
- モックの入出金は現金残高の変更として既存の確認・保存を使用。履歴は初回登録・修正・約定反映を含む直近100台帳であり、分類を推測しない。
- 処理状況は既存APIにある進捗・実行情報のみ。モデル未採用、未算出、履歴なしの状態をダミーで埋めない。
- モックの見本と実データで必要なフォーム項目数は異なる。既存の口座・税・計算の確認項目を削除して見た目だけを一致させない。
- 本人のAndroid端末での更新・既存データ移行確認、実プロバイダー通信は未実施。エミュレーターの境界fixtureはAPKへ含めない。
- 確認用APKは .demo-artifacts/ui-adopted-20261026/ に既存署名で作成。署名/同梱物/ソース照合の結果は同ディレクトリのverified.jsonを参照。

## 2026-10-26 追補：見た目の不一致を修正（D260）

0.1.60の確認は機能の対応と横幅検査が中心で、採用HTMLの構成・寸法との比較が不足していた。ユーザーの「全然違う」という指摘により、上記の完了扱いを見直した。

- 添付HTMLをlocalhostで実表示し、選択済み29画面を390pxで描画して参照画像/DOMを保存。公開サイトの認証開始は自動承認に拒否されたため使わない。
- 旧CSSに追加した外観パッチを除去し、adopted.cssで本文13px、見出し22px、操作44px、ナビのアイコンと余白を定義。設定トップは従来のスタイルを保持する。
- ホームを残高1枚・保有一覧・取引記録へ、今日を市場見通し・提案元・変更一覧・サマリー・判断へ組み直した。計算根拠は専用の詳細画面へ接続する。
- 検証を成績/実運用の2入口・推移・週月次・詳細分析へ、銘柄詳細を実保有・3モデルの予測・提案/理由・調査の順へ組み直した。
- モデル管理は4セクション、設定配下は小さな区分、バックアップは書き出し/ファイル/復元確認、取引履歴は注文/約定の表へ変更。アプリ情報の版はAndroidのインストール情報から取得する。
- 初回登録では実際の現金入力を含め、登録済み台帳の再初期化はしない。保有訂正/約定入力は銘柄を選択し、他の入力を保持する。履歴の選択と設定下書きも復帰時に保持する。
- 保存済み相談は検算前の調査結果も履歴に表示。原予測・ChatGPT・判断・実約定と台帳の保存契約、モデル・計算方式の採用条件は維持する。
- Vitest192件、Python80件、ESLint/TypeScript成功。ブラウザー320/390px・100/150%とAndroid35の320dp・100/150%で29画面を実表示し検査。Androidでは各画面の上/中/下を端末キャプチャ。追加でランキング/設定/取引履歴の復帰・未登録時フォームを確認。
- 証拠: .demo-artifacts/ui-fidelity/。候補APK 0.1.61-candidate/code10061は .demo-artifacts/ui-fidelity-release/ に既存署名で作成し、同梱物・ソース照合を検査する。

モックの架空の成績・約定・進捗・対応していない設定を表示しないため、未登録/未算出の実状態や既存の税・費用項目は参照画像と異なる。本人端末の上書き更新・既存データ移行、実API通信は別途未確認。

## 2026-10-26 再修正：採用CSSとDOMへ直接接続（D261）

0.1.61も本人の外観受入を満たしていないため、手書きの近似スタイルによる実装を置き換えた。

- 採用HTMLの表示用CSSをmock-design.cssへ抽出。比較スタジオ・画面案切替・架空データ・デモ処理は製品へ入れない。adopted.cssはアプリ枠と実操作の接続用とし、ホーム/今日/ランキング/検証/銘柄詳細/各管理画面の採用クラス・構造を使う。
- 設定配下は番号付きのグループ、登録・訂正・取引は項目グループと変更プレビュー、履歴は選択と結果カード、データ修復は4区分に統一。調査履歴は保存結果を操作説明より先に表示する。設定トップは現行のまま。
- 判断画面の提案元切替は実際の数値提案/ChatGPT検算へ接続。原予測・比較入力・口座台帳の一致を確認し、原提案に対応する行だけを既存の再計算へ渡す。本人判断は別保存し、参照したChatGPT記録IDをnoteへ残す。銘柄詳細から戻っても提案元・採用状態を保持する。
- 現金の入出金/訂正と保有訂正は記録日・理由をハッシュ付きで台帳と原子的に保存。表示上の入出金も小数を正確に扱う。取引は既存の差分約定記録と未反映IDの適用を使い、累計値を差分約定として送らない。
- 相談履歴の保存時保有と現在保有、銘柄詳細の全原予測に対する順位、既存jobの実行記録を読み取る。順位headがなければ未算出とし、値予測で代用しない。固定条件を編集可能な新機能と偽らない。

検証：Vitest197件成功。関連Python120件成功に加え、判断元の接続変更後に手動相談13件を再確認（120件に含む）。Ruff、TypeScript、ESLint、mypy77モジュール、production build成功。配布用ビルドでブラウザー8ケース成功、29画面を320/390px・100/150%文字で確認。設定トップを除く28画面の105部品について、採用HTMLと文字・余白・角丸・枠など10項目を比較し差分0。Android35の実WebViewでも320dp・100/150%で全29画面と上/中/下の端末キャプチャ、状態保持を確認し6ケース成功。HTMLの比較ケースはブラウザー側で実行し、Android側は重複実行しない。

証拠は `.demo-artifacts/ui-fidelity/production-browser/`、`production-android/`、各試験ログ。無関係なPython整形を復元した4ファイルはAST一致を確認した。APK生成・署名・同梱物・配布の結果は `.demo-artifacts/ui-exact-release/` に記録する。本人端末の上書き更新と実プロバイダー通信は未確認。実注文なし。

### 署名版で検出した未登録ホームの修正

最終起動で資産未登録時だけ旧ホームの説明と自動処理が残る分岐を検出した。登録済みと同じ採用カード・残高・保有一覧を使い、未登録値は「—」のまま初回登録へ接続する。自動処理はヘッダーから既存のデータ更新画面で操作する。表示だけの初期残高は作らない。旧文言を前提としたUI試験を新しい構成・未算出値・登録先の確認へ更新した。

未登録分岐を加えた配布用ブラウザー9ケースとVitest197件が成功。Androidの再起動後にlocalhost転送が未設定で接続拒否となった初回検査は成功扱いにせず、転送を復元。追加確認では全画面表示は成功したが、初回フォームのブラウザー画像取得で接続が閉じたため、他のAndroid画像と同じ端末キャプチャへ統一。最終再実行は7成功・HTML比較の重複1件をskip。最終証拠は `.demo-artifacts/ui-fidelity/final-empty-browser/`、`verified-android-final/`、`vitest-verified.log`。配布前の初回APKと検出画像は `.demo-artifacts/ui-exact-release-before-empty-home/` に保全し、Driveの同じ本人用ファイルを修正版で置き換える。

### 最終APK・配布確認

source `0d9c5dd5493a943030f3a7d0e265edcb76c2cf56` の同署名0.1.62-candidate/code10062を生成・検査した。24,083,117 bytes、SHA256 `4adca1f9a0d20df809647a868bcffe43b1a37f7908516323de7a2e7823e60757`。配布用46assetsとソース/署名の一致、非debug、モデル/市場/秘密/試験データ非同梱を確認。専用read-only Android35の320dpで署名版をcold起動し、未登録ホームの新構成を実表示、インストール済みAPKのhashまで一致した。本人の台帳や鍵は使用していない。

[Driveの確認用APK](https://drive.google.com/file/d/17bEqBED99E8RRsRL2cDpKYU_chqA5bxf/view?usp=drivesdk) は既存非共有StockAI内の同一IDを修正版へ更新済み。親/サイズ/shared=falseを再読込確認。証拠は `.demo-artifacts/ui-exact-release/verified.json`、`signed-launch.json`、`signed-launch-home.png`、`drive-upload-status.json`。この配布記録以降の文書コミットとAPKのビルドsourceを区別する。本人端末の上書き更新/既存データ移行、実通信とCIは未確認。実注文なし。

## D262 — 設定本文を保ち、共通下部タブを揃える

本人の補足に従い、設定トップの本文はそのまま、共通ナビを他4タブと同じ採用デザインへ変更した。対象は `components.tsx` の共通アイコンと `adopted.css` のナビスタイルだけ。設定本文のCSSと入力/保存処理・タブの名前/行先・スクロール方式は変更しない。

Vitest197件、型/ESLint/build、配布用ブラウザー10ケース成功。追加の1ケースで全5タブのナビの寸法・余白・文字・アイコン・選択状態を比較し、320/390px・100/150%で一致を確認。実Android35/320dp・100/150%でも同じ比較と設定の実表示を確認。WebViewの小数を含む表示高さはvisualViewportで測定する。製品Python/nativeは前版と同一のため、それらの回帰証拠は0.1.62から再利用する。確認用APKと配布証拠は `.demo-artifacts/settings-nav-release/`。

同署名0.1.63-candidate/code10063を検査し、専用read-only Android35で署名版の設定トップと新しい共通タブを実表示。インストール済みAPK hashも一致した。source `8b28b817b578c3224b72b33a42a823707823c4d7`、24,083,141 bytes、SHA256 `048674018955c9931567808c510bdbef9467654ee06b78e4803d999e25e8eb05`。[Drive確認用APK](https://drive.google.com/file/d/1k7SiEWiil6b8CgK_x0pfckErVQTaxUdu/view?usp=drivesdk)は既存非共有StockAI内へ保存し、親/size/shared=falseを再読込確認。本人データを使用せず、本人Xiaomi更新/実通信/CIは未確認。証拠は同フォルダーのverified.json・signed-launch.json・signed-settings-second.png・drive-upload-status.json。

## D263 — 手動分析はChatGPTの会話で読む

本人の最新指定により、採用モックの新規相談の回答JSON欄/検算/アプリ内分析の部分は使用しない。新規相談は利用条件確認・実入力の作成/コピー・ChatGPTを開く流れとし、回答は本文/表/出典でChatGPT側へ表示する。過去の相談記録と以前の回答を保存/検算する導線は保全する。既存の自動連携・数値提案・本人判断・約定を変更せず、新しい外部分析をアプリが検算/保存した提案と称さない。

変更は共通の読み物用prompt関数、手動/ランキングのexport表示、ManualChatGPTPage/Rankings/Todayの案内。旧manual検証moduleは変更せず、入力検証・原本・バックアップと履歴を保持する。UI200件、Python104件、型/ESLint/Ruff/mypy77、配布用build成功。ブラウザー11ケースで29画面と新規相談コピー/外部リンク/回答欄なしを確認。証拠は `.demo-artifacts/chatgpt-readable-release/`。実際のChatGPTへは送信していない。

Android35/320dpでも新しい相談の作成/コピー/外部リンクと回答欄なしの1ケースが成功し、100/150%で実キャプチャ。クリップボードとデータは試験境界を使い、製品APKには含めない。署名版のcold起動はnativeコード不変の前版証拠と区別する。

同署名0.1.64-candidate/code10064、source `47886df05754b9ce797d8d3b521aefb83b637db7`、24,084,689 bytes、SHA256 `5a54150487ad8aaca6019d299cd516b754085023b375a228d0b3774d48f7b0d5`を検査し、[非共有Driveへ保存](https://drive.google.com/file/d/1K0xdPpXLGXGX9kostsKmIdms97VagX_p/view?usp=drivesdk)。親/size/shared=falseを再読込確認。署名/46assets/53Pythonの一致、秘密/市場/モデル/fixture非同梱を確認。本人端末更新・実ChatGPTの返答とCIは未確認で、nativeコードが不変のため署名版cold起動を今回実施済みとはしない。証拠は同リリースフォルダーのverified.jsonとdrive-upload-status.json。

## D264 — 読込と回答操作、本人メモの追加指定

採用HTMLのChatGPT案選択・回答フォーム/保存/検算/順位反映は使わず、保存済みの履歴閲覧だけを残す。原予測の数値提案と本人判断を維持し、外部の新規分析はChatGPTで読む。銘柄詳細に本人メモを追加し、実行結果入力を保存判断の小さい読取へ接続した。既存約定の差分反映・モデル・資産/税は変更しない。

ブラウザー13ケースで29画面/320・390px/文字100・150%を表示し、削除されたsource切替タブは比較対象にせず、対応する保存/取引ボタンを含めたモックの文字・余白・枠等の数値比較を維持した。Android35/320dpでは全29画面と新規相談/メモ/取引の4ケースを実表示。メモの文字数表示は拡大時もボタンと縦に並べる。現在の証拠/APK工程は `.demo-artifacts/record-memo-release/`。旧履歴まで削除する案は自動承認レビューに拒否されたため、旧データの閲覧を保った。

D264配布：0.1.65/code10065、source `5e660d96cd276f17e3472c3a4955e5e3e4bb1648`、24,086,073 bytes、SHA256 `974c6d6e2359022b6296ebb78b1496225594452ddd905adf8b2eaf5a39ddf64d`。署名版の専用AVD cold起動・ホーム表示と同一APK hashを確認。既存非共有Driveへ[本人用APK](https://drive.google.com/file/d/1dBYOS_pfgCirHq_Su7JlNKACP-4HNkrC/view?usp=drivesdk)を保存し、親/size/shared=falseを再確認した。旧版は保持。本人実機と実通信・CIは未確認。
