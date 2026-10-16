# Project Status

## 2026-10-17 — 開始から小分け取得・日次計算・通知を接続

- WorkManagerへ端末内の明示的な開始/停止とsession IDを保存。CONNECTEDでモバイル回線を許可し、重複した開始をunique workで抑止。各取得を最大4ページに区切り、次のsliceと15分周期の回復予約へ接続した。APIキーとprovider間隔をUI/nativeで共通化し、同じ単一計算ownerを使う。
- 当日10:30〜11:30の一覧取得を長期履歴より優先。受領を元の時刻で保存し、締切後の当日一覧不足は遅延・未完として扱う。完全な受領だけ共有検証へ渡し、native暗号化commit後にACKする。停止/復元/キー削除で旧sessionを無効化し、保存済みページと原予測は保持する。未知の一時失敗はJST1日3回まで、401/403は明示再開を待つ。
- 履歴の差分取得から、締切後の原予測・株数の2段階保存まで接続。通知拒否でも計算は続き、通知本文へ口座値を含めない。今日と設定へ開始/停止・対象日・遅延状態を追加。数値保存とChatGPT調査を分け、今回の自動処理で調査まで完了したとは表示しない。
- ローカルの既存フロント66件と新しい開始/停止・通知拒否の2件、TypeScript/ESLint/buildがpass。320/390px・文字150%で開始パネルも48px対象・12px間隔の実測に追加し2件pass。新しいnativeの小分け/ACK/停止/締切/予約/通知拒否試験はCI待ち。
- 前回文書fa6c603のrun38970802047はAndroid/verify成功、release skipを確認。今回のscheduler成功とは扱わない。ChatGPT自動調査、OS再起動・画面オフ・Xiaomi受入、実連携、承認モデル/実市場採用は残る。台帳継続利用の回答待ちで現行72時間の照合を維持。研究worker再開・私有学習・実注文・merge・APK公開なし。

## 2026-10-17 — 日次自動化に向けて計算と保存をアプリ全体で共通化

- Android UI内のPython Workerと世代counterを、application contextを持つ単一のnative計算窓口へ移動。同じdatabase pathのUI・native呼出しを直列化し、POSTは暗号化commit後にだけ応答する。保存失敗時の未確定メモリを破棄して再読込し、別handleからの世代変更も検出する。Activity消失で窓口を閉じる処理は置かない。
- APK専用の別HTTPS originへ計算ページを同梱。外部navigation・network fallback・file/content accessを止め、CSPでframeと接続を制限。APIキー・OAuth情報を渡さず、同じ共有Pythonを実行する。暗号化保存名・alias・旧形式・chunk/AAD/CASを維持し、見出しと分割の読出しを同じtransactionへ変更。復元時は旧hostを終了してから隔離検証し、2つのWASM heapを常駐させない。検証不合格なら元のdurable stateを維持する。
- ローカルのTypeScript/ESLint/build・フロント66件と、配布用計算ページをnativeと同じCSP・外部通信遮断で起動して保存する試験1件がpass。既存WASM/市場画面6件・調査画面2件、package監査もpass。Androidの実際の同梱Python、同時利用、owner再生成、復元不正、commit失敗、旧暗号文・別DB handleの整合も以下の修正後CIで確認した。
- 初回293d7cdのrun38966989599は、暗号処理の移動時に削除したArrays importが既存の更新redirect検証でも必要だったためAndroid compileに失敗。元のimportを復元する。runtimeテスト前の失敗であり、native計算の成功/失敗へ読み替えない。
- 修正d46815fのrun38967501219はcompile/lintを通過し、native31件中30件pass/1件fail。旧暗号・別handle整合の追加2件を含む保存試験はpassしたが、WebView124.0.6367.219で実際のinterpreter起動が4.45秒で失敗した。原本は`.demo-artifacts/native-owner-failure-38967501219`。単なるretryで済ませず、workerの起動段階と固定error種別だけを返す診断で切り分ける。口座値・Python trace・provider応答は出さない。
- 診断73bfb9cのrun38968897961で`interpreter_type_ASSETMASK_0`を確認。Python本体の要求が画面用asset handlerに届いていない。CapacitorのBridge/CapConfigも確認し、application-wide Worker loaderへ同じAPK handlerを接続し、Activity再作成でUI用serverへ上書きされないようにする。network/file/contentの禁止と不明URLの拒否は両方で維持する。
- 修正cd3e1f8の[run38969663415](https://github.com/iburigakko-picoloom/stock-ai-spec/actions/runs/38969663415)でAndroid/verify両job成功、release skip。native JUnit31件・失敗/error/skip0を原本で確認。新しい実WASM/競合/再起動/復元/保存失敗の1試験は66.169秒、単なるhealth mockではない。共有Python301件・追加platform6件、フロント66件、WASM/市場画面6件・新しい配布計算ページ1件・調査画面2件がpass。Ruff/mypy66 source（標準/win32）・TypeScript/ESLint/build・source781 files/私有ファイル0・package監査もpass。原本は`.demo-artifacts/native-compute-ci-38969663415`、`compute-owner-ci-verify.log`、`compute-owner-ci-jobs.json`。エミュレーター証拠でありXiaomi成功へ昇格しない。古い診断runはnative失敗証拠の取得後に、修正前verifyの重複待機を取消した。
- 前回最終78a3a2bのrun38963878464はAndroid/verify両job成功・release skip。共有Python301件・追加platform6件・フロント63件・WASM/画面6件・調査画面2件とnative27件（原本の失敗/error/skip0）を確認済み。今回の共通化がこの証拠を自動で引き継いだとは扱わない。
- 日次scheduler、画面オフ/OS停止・再起動後の再開、初期取得の自動接続・通知は未実装。承認モデル0件、実連携・Xiaomi受入・実市場NAV/採用/holdoutも未完。研究worker再開・私有学習・実注文・merge・APK公開なし。
- 次の利用設計として、初回確認後に台帳を継続利用するか、現行の72時間以内の本人確認を続けるかを本人へ確認中。回答までは現行のstale/future・保有/現金/税/NISA/約定照合を維持する。継続利用を選ぶ場合も、手入力を自動で再確認済みにせず、約定・入出金と台帳の履歴を正しく接続する必要がある。

## 2026-10-17 — 凍結した原予測・本人設定から株数を保存

- 手動の「当日の予測・株数を計算・保存」から、5/20日予測、本人設定・台帳・原予測の照合、HOLD/費用/税/制約を含む株数、共有の不変archiveと「今日」の表示まで接続。数値と株数は各段階でnative暗号化durable保存を待つ。原予測・残高・保有を提案で更新しない。
- 同じ数値計算時に固定した当日一覧、前営業日の未調整終値、20営業日の売買代金を正確なobservation IDとhashで読み出す。現在の一覧にない保有の情報も固定した過去の銘柄一覧から取得。PC/WASM比較でPandas dtypeを含むframe hashの実行環境差を確認したため、株数用の銘柄情報は元データの受領証拠を直接照合する。訂正や破損を古い予測へ混ぜない。
- 保存前の本人入力・補足設定・約定集合・選択原予測を同じSQL transactionで再確認し、提案・archive・方針・当日状態を一度に保存。計算intentの後/共有保存の後に停止しても、同じ数値と生成時刻から再開。起動時に未保存の提案を自動生成しない。数値/株数の選択履歴を保存し、失敗後に古い予測へfallbackしない。入力変更後の提案表示と直接reviewを止め、原記録は保持する。
- 対象株と保有が空なら、本人の現金・税・約定の整合を確認してCASH_ONLYとして正常完了。仮の銘柄予測・提案・残高変更を作らない。再試行や復元で生成時刻を更新せず、再確認時刻を分離。保存済みの本人判断を再試行で消さない。
- ローカル検証：関連Python298件、追加した元データ照合/破損試験を含む31件、最後に加えた選択復旧を含む予測/株数/backup36件がpass。Ruff・mypy66 source（標準/win32）、フロント63件・TypeScript/ESLint/build、全WASM/市場・本人設定画面6件、既存調査画面2件もpass。PC/WASMで137株の保有を37株へ縮小し、2候補を各100株へ変更する非ゼロ費用・売却税付きの保存結果と復元が一致。source監査772 files・private keys/models/market files0、package監査29共有source・model0もpass。
- 実装62a1069の[run38963100832](https://github.com/iburigakko-picoloom/stock-ai-spec/actions/runs/38963100832)でAndroid/verify両job成功、release skip。新規の株数15件・予測12件と台帳/API回帰を含む共有Python301件・追加platform6件、フロント63件、WASM/市場画面6件と調査画面2件がpass。native JUnit27件・失敗/error/skip0を原本で確認。source監査772 files・私有ファイル0。証拠は`.demo-artifacts/native-shares-ci-38963100832`、`share-publication-ci-verify.log`と`share-publication-ci-evidence.json`。
- 追加の画面整理では短い見出しと判定時点・株数状態を表に出し、計算時刻・参照情報を折りたたみへ移動。TypeScript/ESLint/build・フロント63件と320/390px・文字150%の2件を再確認し、320pxのモデル/株数パネル画像を目視確認した。リンクを含む48px対象と12px間隔を維持。
- 承認済みモデルは0件。通常の開始・毎営業日background・通知、実市場NAV/認証済み採用/holdout、実アカウントの検索・利用資格、Xiaomi実機と同署名更新は未完。研究worker再開・学習・実注文・main merge・APK公開なし。前回文書1a715ecのrun38957628011はAndroid/verify両job成功、release skipを確認。

## 2026-10-17 — 300社と全保有に対応する有限回の株数探索

- 全組合せを使う既存方式を維持し、明示的な研究方針`daily-decision-engine-v3-bounded`を追加。HOLD・通常単元で可能な全現金・流動性内の縮小案から株数調整と乗り換えを調べ、探索評価32,768回以内で結果と検討範囲・上限到達を保存する。全候補×口座を検討できなければ停止し、最適解の証明とは扱わない。
- 元の費用・価格影響・複数売却の税相殺・源泉徴収・NISA購入枠・投資上限・銘柄/業種集中・現金・流動性制約を再利用。試行時は元から未保有で目標0のキーだけを省き、最後は全対象で再検査する。100株変更時に端株を残し、137株→337株の上限も正しく扱う。選ばれた値の後処理で現金・制約を無視しない。
- 本人設定の旧方式を自動移行せず、方式変更時に条件の確認を解除。新規設定は未確認の有限回方式を選ぶ。旧提案のserializationに新しいnullを挿入せず、保存済みhash/backupを維持する。新方針の個人比較には探索実装のhashも含める。
- 小規模の全組合せ解、費用・税、NISA/同一銘柄の複数口座、流動性、端株、上限後の確認済み結果、巨大資金でも株数rangeを作らないことを検証。300社＋保有のPC結果と、非ゼロ費用・価格影響・売却税を含むWASM結果が一致した。PC上のheadless Edgeで探索約1.43秒、5,319評価のfixtureを`.demo-artifacts/android/bounded-parity-20261017.json`へ記録（実機ではない）。最終関連Python170件、Ruff/mypy66 source（標準/win32）、フロント59件とTypeScript/ESLint/buildがpass。WASM/市場・モデル・本人設定画面5件もpass。320px・文字150%の画像を目視し、選択肢の表記を収まる長さへ整理。
- 実装7f0b493の[run38956862746](https://github.com/iburigakko-picoloom/stock-ai-spec/actions/runs/38956862746)はAndroid/verify両job成功、release skip。共有Python256件と追加platform6件、フロント59件、WASM/レイアウト5件と既存調査画面2件がpass。native JUnit27件・失敗/error/skip0を原本で確認。公開source監査767 files・private keys/models/market files0。証拠は`.demo-artifacts/native-bounded-ci-38956862746`と`bounded-ci-verify.log`。実機・実モデル採用の証拠へ昇格しない。
- 承認済みモデルは0件。凍結市場根拠から原予測/本人設定を経て株数を不変保存する接続、通常の開始操作・日次background、実市場NAV/holdout・実アカウント・Xiaomi受入は引き続き未完。研究workerの再開・新たな学習・実注文なし。前回の文書commit452e6d3のrun38953827813は成功を確認。

## 2026-10-17 — 復元前のSQLite接続を明示的に終了

- CI履歴を再確認し、ab608e6のrun38946144536で旧入力の2回目復元に`database is locked`が発生していたことを確認。Android jobは成功したがverifyは127件pass/1件failであり、このrun全体を成功とは扱わない。
- Python SQLiteのtransaction contextだけでは接続が閉じないため、端末内の個人設定・市場・当日一覧・候補・モデル・原予測の接続を、commit/rollback後に必ずcloseする共通contextへ変更。backupのprobe・出力・入力接続も例外時にcloseする。保存schemaと原payloadは変えず、GCによる解放を待たない。
- 開いた接続すべてへの強参照を残したまま3回の復元と各画面の読取を行い、全接続が閉じていることを検証する回帰試験を追加。関連端末内Python92件、最終probe/出力接続修正後の対象2件、WASMの計算/復元2件がpass。実注文・実API・新たな学習やholdout開封なし。
- 実装55b480eの[run38952669553](https://github.com/iburigakko-picoloom/stock-ai-spec/actions/runs/38952669553)はAndroid/verify両job成功、release skip。共有Python156件、フロント58件、WASM/市場・モデル画面4件、既存調査画面2件、Ruff/mypy65 source（標準/win32）/TypeScript/ESLint/buildがpass。JUnit原本でnative27件（Protocol6・Session7・MarketDownload8・ResearchJournal3・StatePersistence3）、失敗/error/skip0。公開source監査763 files・private keys/models/market files0。証拠は`.demo-artifacts/native-bundle-ci-38952669553`と`storage-ci-verify.log`。実アカウント・実機受入・モデル採用の成功とは数えない。

## 2026-10-17 — 校正付きモデル一式と端末内の原予測保存

- private bundleへ5日/20日回帰・20日下振れ分位点・大幅下落確率の4head、凍結特徴量ID、学習/校正の時点、RMSE根拠、risk定義、同じモデル選択の本人レビューをまとめた。PCの作成コマンドは1ファイルと未承認pin案だけを作り、上書き・自己承認・新規学習・holdout開封を行わない。運用手順は`docs/MOBILE_MODEL_BUNDLE.md`。
- 完全一致する公開可能hashとレビュー/校正/PC/実機一致の根拠を確認してから全headを一括取込。空の推論入力でも木の全split/leaf/前処理を検証。明示的に選んだ一式が取消・破損・締切後の場合は古いモデルへ戻さない。壊れたキャッシュは同一pinファイルでだけ修復し、修復の実時刻と旧hashを保存する。時計が戻った修復は拒否する。
- 当日membership・前営業日までの広い市場母集団・候補/全保有・本人台帳を接続し、5/20日の原予測を共有PredictionSnapshotへ研究用として保存。履歴不足の新規候補は除外理由と元抽出票を残し、保有予測不足は全体を未完了にする。4/5文字の保有コードを残す。全現金で対象がない場合は仮銘柄・仮予測を作らない。
- 数値生成日時、11:30締切、実際の情報受領日時を分け、元head出力・source/feature hashを保存。計算intent→共有snapshot→完了markerの順で記録し、中断後は同じ数値と日時で再開。本人入力の競合を保存transaction内で再確認し、完了markerだけ失った保存を起動時に照合する。ChatGPT調査は既存の原予測を参照できるが数値・保有・約定を変更しない。
- 「一式を取り込む」「数値予測を計算・保存」を接続し、予測・不足候補・実時刻を折りたたみへ表示。時刻は年・秒・JST付きで揃え、元のISO時刻も保持。採用未完了と推奨株数未作成を明記。pin前の4head PC/端末照合は読取専用で、取込・承認・snapshot作成を行わない。
- ローカルの関連Python155件、修復/読取専用照合20件、5文字保有を含む抽出境界1件、既存台帳/API29件がpass。Ruff、strict mypy65 source（標準/win32）、TypeScript/ESLint/build、フロント58件がpass。WASMで41/51特徴量・3モデル種×3taskの9モデル・4head bundleがPC参照値と一致し、台帳の新interpreter復元も確認。320/390px・文字150%で48px対象/12px間隔/横溢れの2件、既存調査画面2件もpass。実装295b0acのrun38952171793でAndroid/verify両job成功、release skip。接続寿命修正後の最終結果は上の55b480eの記録を参照。
- 承認済みbundleは0件。紙運用レビューや取込だけで採用へ昇格せず、既存の認証済み評価/holdout/設定ゲートを維持。実市場NAV・株数/HOLD/費用/税との最終接続、300社に対応する探索、日次background/通知、実API/実アカウント、Xiaomi性能・更新受入は未完。既存の私有研究変更を含めず、実注文なし。全完成条件は継続中。

## 2026-10-17 — 当日の銘柄一覧を履歴と分離して11:30対象へ接続

- 公式master仕様で当日一覧を取得でき、休業日を指定すると翌営業日の一覧になることを確認。当日calendarとmasterだけのnative取得profileを追加し、日別履歴と別key/acquisitionでページ再開・ack・取り直しを行う。休業日はcalendarだけで終了し、翌営業日masterを混ぜない。
- 共有SQLiteへ当日一覧の不変receiptを別保存し、schema検証・受領時刻・page manifest・hashを確認してから保存。取得中ページは共有状態の暗号化durable保存後にだけackし、ack前の停止は同じreceiptを回収する。保存済みの締切前一覧を締切後に再利用し、締切後の新受領は別記録のまま数値対象から外す。backupで保持する。
- forward用の対象抽出を当日一覧へ接続し、前営業日の時価総額と直近20営業日売買代金で選ぶ。当日不在銘柄を新規候補から外し、全記録済み保有は残す。新コードの履歴を推定せず、当日一覧を過去の5dataset/特徴量へ混入させない。ホーム以外の詳細操作に取得・再開と取り直し、直近受領と締切内の利用対象時刻を表示する。
- Android Instantのnanosecond表現をPython datetimeがmicrosecondへ切り捨てる境界を修正。受領時刻を必要に応じて先のmicrosecondへ切り上げ、11:30:00.000000001を11:30:00へ遡及しない。元の時刻文字列と受領ページの証拠は保持する。
- 変更前の共有回帰126件、新しい境界を含む取得/当日一覧18件、フロント54件、WASM2件（PCの41/51特徴量・6モデル一致、台帳の新interpreter復元）とレイアウト2件がpass。時刻境界修正後の取得/当日一覧/台帳/backup58件もpass。35a4cf3のrun38944905693でAndroid/verify両jobが成功、releaseはskip。共有Python128件・フロント54件、native27件（追加membership2件を含む）・失敗/error/skip0を原本で確認した。WASM/市場画面4件と既存調査画面2件もCIでpass。証拠は`.demo-artifacts/native-membership-ci-38944905693`と`membership-ci-verify.log`。実API・実注文・私有モデル採用なし。
- 最終予測/株数接続の監査で、portable modelに校正RMSE・校正の受領時刻とrisk定義を渡す契約が未実装であり、既存のexact searchは300社の株数組合せで上限を超え得ることを確認。仮の不確実性や未審査の探索法への自動切替では埋めない。次の数値パイプライン工程で明示的な契約・探索方針を実装し、採用/NAV検証へ戻す必要がある。全完成条件は未完。

## 2026-10-17 — 履歴の範囲取得・ページ再開・300社の対象プレビュー

- J-Quantsの日別ページをnative SQLiteへ圧縮保存し、通信中断・403/429・process再生成後に同じcursorから再開する処理へ変更。calendarで休業日を確認できた場合は空価格を作らず他の取得を省略。ページごとの受領時刻・hash・行数を残し、共有DBの検証と暗号化durable保存後にだけ取得途中データをackする。保存成功後/ack前の停止も確定済みreceiptから回復する。明示的な取り直しは以前のページ証拠を保持して別acquisitionへ進む。
- 「履歴の取得を開始・再開」と日付単位の停止を接続。初期420日前〜昨日、1範囲最大2年、保存済み日をskip。範囲はbackupに保存し、訂正取得は元の初回範囲を変えない。API未設定・契約外・上限・保存失敗を区別。現在はforegroundの手動処理であり、画面消失後の自動継続・毎営業日worker・完了通知は未完。
- 時価総額は公式valuation endpointの百万円単位を使い、300億円=30,000百万円で判定。deprecatedなbars MktCapや推測株数へfallbackしない。受領済みcalendarで連続した直近20営業日を確定し、20日すべての売買代金が有効な普通株の上位300社を同順位コード順で抽出。条件外・未収録の全記録済み保有を残し、保有未入力も区別する。市場・業種の入力母集団は変更しない。
- 日別の完全snapshotから削除された行を古い版から復活させる問題を修正。同じ内容に戻るA→B→Aも別の受領として保存し、旧5datasetテーブルをtransaction内で移行する。11:30後の受領・訂正をcutoffへ遡及させない。対象抽出は前営業日の銘柄一覧によるプレビューで、当日membership・最終推論/株数への接続はまだ完了していない。
- Python関連113件pass（新規/変更した取得・対象抽出・台帳・backupを含む）。Ruff全件・mypy65 source（標準/win32）pass。TypeScript/ESLint/buildとフロント50件pass。headless Edgeで320/390px・文字150%の横溢れ/48px対象/操作間隔12pxを2件passし、320px画像を目視確認。ca0875cのrun38941623361はAndroid/verify両jobが成功、releaseはskip。取得の追加6件を含むnative25件・失敗0・error0・skip0をJUnit XMLで確認した。WASMとPCの特徴量・モデル一致、既存調査画面の試験もCI内でpass。証拠は`.demo-artifacts/native-market-ci-38941623361`。API実接続・実注文・private研究データの公開なし。Xiaomiの実測、モデル採用、日次自動化等の全完成条件は継続する。

## 2026-10-17 — ChatGPT再認証・更新・連携解除の復旧処理

- native sessionをKeystore暗号化の単一envelopeへ整理し、検証済みclient/subjectと回転tokenの保存を分離。旧credential形式は新形式へ移行し、更新後にplan scopeが外れても新refresh tokenを先に保存してから推論を停止する。同時consumerの二重refreshを抑止。
- 文書化されたterminal refresh errorの4xxコードだけで利用不能tokenを消去し、登録済みclient/subjectを保持。通信・5xxでは消去しない。再認証は同じclient/hostで行い、異なるsubjectや解除後に遅れて返った認証で置き換えない。
- 連携解除で新規推論を止め、実行中接続を切断し、端末tokenを消去してから公式discoveryのrevocation endpointで失効を試す。issuer/HTTPS同一originを検証し、一時失敗だけ最大2回。失効の確認有無を画面へ返す。認証取消後の未採用grantも可能な範囲で失効を試す。
- 接続済み状態から「ログインし直す」と中止が可能。期限切れ後のモデル・推論量と保存済み調査を維持し、利用資格・アプリ上限・一時障害・権限不足を分ける。raw provider messageを表示・記録せず、安定code等だけを暗号化保存する。
- フロントのtypecheck/ESLint/buildと39件の試験がpass。追加native7件（permission喪失時の回転、terminal/一時障害、同時refresh、logout、owner/遅延callback、旧形式移行、診断/endpoint）を含むrun38938128185はAndroid/verify両jobが成功。JUnit XMLで合計19件・失敗0・error0・skip0を確認した。実アカウントでのOAuth更新・失効、Xiaomi実機、バックグラウンド/初期一括取得等の完成条件は未完。実APIの推論・実注文なし。

## 2026-10-17 — ChatGPT調査の実行・回復・銘柄詳細を接続

- 本人がGitHubへのpush・PR作成を明示許可。検証済みのaf2a64f/f397f07をpushし、draft PR #2を作成・本chatへ添付。run38931259021でAndroid build/instrumentationと共有コード検証が成功、releaseはskip。main反映・APK公開は行っていない。以前の送信許可待ちは解消。
- 調査開始と段階ごとのattemptをSQLite schema5へ保存し、二重claimを抑止。同じ日・予測・設定は同じcontextを再利用し、明示的な再調査は新revisionとして保存。中断・上限・検索欠落等を未完了として残し、完了済みの独立調査を再送せず照合を続ける。
- Native側はrequest hash、選択モデル・推論量を固定し、検索だけを許可。HTTP送信前と回答受領後をKeystore暗号化journalへ保存し、JS側が消えても回答を回収できる。共有SQLiteの保存確定後も送信済みtombstoneを残す。実行状態の観測失敗だけで終了とせず、不在を確認した回復操作は遅れて来る旧callerを封じる。
- 銘柄詳細に元の5/20日予測、独立調査、照合、過去の調査全文・出典・設定を接続。未保有で売買提案外の予測対象も詳細を開ける。公開日時不明と数値締切後の調査時刻を分け、元の予測・株数は変えない。モデル文字列はHTMLとして実行しない。
- Ruff全件・strict mypy65 source（標準/win32）pass。共有API/台帳/backup/端末内dispatcherを含むPython122件、React/実行制御34件pass。headless Edgeで320/390px・文字150%の折りたたみ/出典/横溢れ/48px対象/操作間隔12pxを2件passし、320px画像を目視確認。通常権限でのlocalhost試験を使用し、外部サービスはfixtureで代替している。
- 4dee41dのrun38933654578はAndroidに存在しないJSONObject.keySetの使用でnative compile失敗。43c0649でAndroid対応の同一キー検査へ修正し、run38934414537はAndroidとverifyの両jobが成功、release skip。JUnit XMLを取得してProtocol6件・ResearchJournal3件・StatePersistence3件、合計12件/失敗0/skip0を確認。証拠は`.demo-artifacts/native-research-ci-38934414537`。実機互換や実アカウント成功とは数えない。
- 次の認証監査で、refresh後にplan scopeが外れた場合の回転token保存順、terminal refresh errorの判別とaccount/client mapping保持、接続済み状態からの再認証UI、remote session revokeの扱いを追加確認項目として特定。公式accounts/errors文書を再確認済み。まだ修正・実接続成功として扱わない。
- 実アカウントの許可・モデル・検索能力、Xiaomi実機、OSによる停止/再起動、日次自動調査は未確認。初期一括取得、時価総額/流動性対象抽出、採用モデル、最新株数までの完成条件も未完。APIだけで実用開始できるとは判定しない。実注文なし。

## 2026-10-17 — 独立調査の2段階保存と検証

- ChatGPTの独立企業調査と数値予測との照合を別の不変レコードとして保存する共有Python契約を追加。初段には銘柄・会社名・調査時点だけを渡し、数値順位・リターン・保有・口座入力を渡さない。照合は保存済み初段と元の予測に結び付け、元予測や推奨株数を変更しない。
- 選択モデル・推論量・プロンプト版・実際のモデル・実行時刻・出典URL・request/response hashを保存。検索引用だけから公開日時を推測しない。未完了・拒否・上限エラー・初段の検索/引用欠落を正常な調査結果として保存しない。
- SQLite schema4で段階ごとの保存、同一receiptの冪等性、再読込・backupでの参照整合を追加。元の数値と異なる再hash済みレコードも拒否。schema3のbackup復元と移行を検証し、モバイル用の明示source allowlistにも新モジュールを追加。
- Ruff全件pass、strict mypy65 source pass。新規調査契約20件を含む関連79件pass。最初のsandbox試験は既存backupのhardlink作成をOSに拒否されたため中断し、同じfixture範囲を通常権限で再実行して79件passを確認した。既存のStarlette deprecationと意図的な不正入力に対するPydantic serializer warningは残る。
- 実アカウントOAuth・Androidコンパイル・実検索・自動実行・失敗job状態の保存・画面接続は未完。公開リポジトリへのpush/draft PR作成は自動承認レビューが外部公開の明示許可未確認として拒否し、本人への許可質問は回答待ち。ローカル実装と検証を継続し、迂回送信していない。実API接続、実注文、秘密情報の公開なし。


## 2026-10-06 20:18 JST - D084 h20 51-feature final candidates started

- The user explicitly authorized the full h20 candidate scope on manatobook. D084 and authenticated feature-selection artifact13c8676f... fix51 features (V0 plusF6/F7/F10/F12), distinct from the previous77-feature Full Ablation. Same frozen Build/Dataset/V2 feature snapshot and holdout2026-03-04; existing h20 references have tuning end2024-08-13 and OOF start2024-09-12. All12 old h20 research reports use77 features; none is a same51-feature completed candidate, so none was relabeled/recomputed as an already-matching result.
- Created a strict native v2 campaign with exactly LightGBM/XGBoost/CatBoost x seeds17/29/43 (9),300iterations,tuning20trials/900s,500/60/60 walk-forward,120holdout,diagnostics on,ablations off, like h5 final candidates. Scientific source/lock stays genuine 8d82fa67a7f64186f42208f0632b799e13381c0d; all52 pinned source hashes verified. Separate native checkpoints bind actual frozen feature manifest83859e...; old77-feature and h5 history remain unchanged.
- Single sequential workerPID15736 started2026-10-06T11:15:37.715576+00:00; first h20-lightgbm-s17 RUNNING. Physical RAM before candidate6.639172GiB passed3.5GiB. Same3.5GiB guard is also enforced before every native fit. Source fixes each model to1 thread. No additional monitor/scheduler, automatic retry, external compute or OS/app/account changes. Failure/low-memory stop persists registry/campaign/worker state and leaves later candidates pending. Current launch evidence confirms process/input preparation; estimator-fit completion and whole9-candidate ETA are not yet measured.
- Research_only; locked final holdout remains unopened, realistic-cost/historical-vintage/live-adoption blockers unchanged. Future human checks remain morning/evening. Workspace stock-active-runtime.json points to current h20 runtime; each candidate checkpoint path is read from worker.json. Evidence: docs/evidence/h20-final-candidates-20261006/.



## 2026-10-05 19:23 JST - authorized seed43 resume, ranking fold4

- User explicitly authorized resuming the stopped seed43. Authenticated and preserved all16 native units (tuning7/regression6/ranking3); the interrupted ranking4 had no published artifact or resumable estimator state. Same checkpoint/provenance and unchanged scientific pin 8d82fa67a7f64186f42208f0632b799e13381c0d, config/41features/CPU1/300iterations/evaluation; native ResearchCheckpointStore resume reuses successful folds and restarts ranking4 at attempt2. Original single-attempt lock and original logs remain intact; pre-resume state backed up.
- Active workerPID16756, single logical worker, ranking4 RUNNING/attempt2 with unchanged evidence. First resumed pre-fit3.5GiB guard passed (4.690781GiB). Input authentication and checkpoint updated; actual estimator fit completion remains unconfirmed. No additional observer, scheduler or automatic restart; human checks remain morning/evening. Current runtime pointer: workspace stock-campaign-continuation/active-runtime.json.
- Research results remain8/9 and historical original7/9 until complete report/OOF/registry authentication. No holdout/live adoption, new horizon, feature or paid compute changes. Evidence: docs/evidence/campaign-continuation-20261004/seed43-authorized-resume-20261005.json.


## 2026-10-05 08:54 JST - seed43 first three native ranking folds completed

- Existing seed43 checkpoint records tuning7 + regression6 + ranking3 = 16 successful units, zero failed. Ranking fold4 is active. Native ranking scope-to-publication measurements: fold 1: 3.321h, fold 2: 3.923h, fold 3: 3.857h. These include preparation and publication; they are not pure estimator-fit benchmarks or a whole-run ETA. Full OOF authentication remains scheduled for terminal verification.
- All 17 recorded pre-fit guards passed at3.5GiB; latest measured headroom 4.484951GiB. Same original CPU1/300iterations/41features/input/config and single attempt; no restarts, new learning range or external compute. Scientific pin 8d82fa67a7f64186f42208f0632b799e13381c0d remains unchanged.
- Original planned research results remain8/9 until seed43 report/checkpoint/registry authentication completes. Historical manifest remains7/9; original failures and pins are preserved. Evidence: docs/evidence/campaign-continuation-20261004/ranking-1-3-complete-active-ranking-4.json, actual checkpoint and existing observer log.


## 2026-10-04 21:57 JST - seed43 regression complete; long ranking wait remains

- The same single seed43 attempt completed all six regression outer folds at21:43:03 JST. Tuning7 plus regression6 =13 successful checkpoint units, zero failed. Ranking fold1 started21:43:07; its guard passed with4.863506 GiB. CPU1,300iterations,original frozen input/config,3.5GiB guard and no restarts remain unchanged.
- Ranking is still computational work, not additional implementation. Prior genuine seed29 ranking6 on this PC took about5h25 from fit-preparation guard2026-10-03 10:33:55 JST to artifact publication15:59:08 JST. That reference used depth3/seed29/3,200,734 train rows; current ranking1 uses depth4/seed43/2,074,895 train rows. Do not apply the old time as current ETA or infer the whole remainder from regression speed. Current ranking completion, later six quantile/six large-loss folds and diagnostics remain unconfirmed.
- Existing observer continues metadata checks and15min process/RAM reads. Completion/stop verification is prepared; no new job, learner, paid computation, source/dtype/parameter/guard change or other app/OS/order action. Source evidence: docs/evidence/campaign-continuation-20261004/regression-complete-active-ranking.json plus the original first-fit-headroom and native checkpoint logs. Actual guard counts come from raw scratch records, not the observer's wrapped-array count.


## 2026-10-04 21:08 JST - seed43 real native fit confirmed

- First fit-preparation boundary passed at21:03:50.407 JST with3.867611 GiB available, guard3.5 GiB. Exact estimator.fit entry time was not instrumented. The first genuinely new CatBoost regression tuning unit completed at21:05:45.928 JST, proving actual native fit. Reauthenticated225,842 OOF rows, native provenance/no import, config b5f608c4..., split/seed43/ordered41features, Parquet and logical hashes.
- At21:08:27 JST checkpoint2e231ef0... had two SUCCEEDED tuning units, zero FAILED; both recorded fit guards passed (3.867611/4.332184 GiB), no Arrow cleanup requested. At21:08:23 JST nativePID19968 alive, availableRAM4.695229 GiB, working set2.807789 GiB, observed cumulative peak4.804001 GiB. This is not the exact full-run/native-only peak or a whole-campaign time estimate.
- Seed29 research registration is complete; combined authenticated original-plan results8/9. Historical original7/9/failure ledger remains preserved. Single seed43 attempt and existing observer continue with no restart. Current blockers: none observed for the active fit; final publication/all outer folds/diagnostics and remaining time unconfirmed. Research/live-adoption blockers remain unchanged.
- Evidence: docs/evidence/campaign-continuation-20261004/{first-native-fit-confirmed.json,first-native-current-snapshot.json}. The Windows observer serializes fit checks through an array wrapper, so its summary PassedFitGuards count is not a total; use the raw scratch *.fit-headroom.json for actual guard count/details, as done by this authenticated milestone. Process/RAM reads remain every15min plus boundaries; no second observer or learning worker.


## 2026-10-04 21:00 JST - seed29 research registration and single fresh seed43 attempt

- Seed29 recovery completed at 19:29:47 JST. At 20:57 JST, reauthenticated all seven legacy reports and the recovery report (5,310,120 OOF rows each), exact original per-batch config/41 ordered features/build lineage, full bundle identities and hashes. Recomputed the native94-to-8d equivalence proof against genuine frozen source; it is identical. Original16 artifact bytes remain unchanged.
- Register the recovery as research_only in the append-only canonical experiment registry. Preserve original h5.json bytes, twenty failed attempts, legacy seven report pins and recovery pin 8d82fa6. Create strict v2 h5-legacy-successes.json (seven genuine94 reports) and h5-continuation.json (seed29/43 genuine8d) under artifacts/campaigns/goal3-continuation/13c8676f...; continuation-link.json binds them to the original nine-batch plan. Authenticated research results: 8/9. The historical original manifest remains 7/9; do not report that old manifest itself as completed.
- Existing development-selection loading accepts multiple strict v2 campaign manifests with different genuine report pins. After seed43 succeeds, use both listed 5d manifests; retain the existing20d requirements separately. Do not open locked holdout, select/deploy a live model, or claim operational adoption.
- Seed43 launched once at 21:00:28 JST; preparation available RAM7.529 GiB, scratch disk208.354 GiB, zero stock workers before launch, all four old tasks Disabled. Native workerPID19968, launcherPID13936 represent one logical learner. Source/dependency lock still matches genuine8d. Original CPU1/300 iterations/seed43/41features/500-60-60 split/120holdout/20trials-900s/diagnostics retained. Fresh namespace2e231ef0...; no seed29 fold/prediction reuse.
- First real fit is not yet verified at this milestone. Guard stays3.5 GiB, no automatic restart. Observer reads progress metadata every30s and process/RAM at15min or first guard/terminal boundaries; it performs no worker actions. Completion time remains unestimated until native measurements exist.
- D094 records the strict pin-separated adoption route and checkpoint-helper mismatch. Evidence: docs/evidence/campaign-continuation-20261004; active records: workspace stock-campaign-continuation/runtime. Scientific src, training methods and dtype unchanged. Solver remains stopped; no20d expansion, other-app termination, new authorization/billing, OS change or order.


## 2026-10-03 10:40 JST — 株式の単独worker再開を実確認

- 10:29 JSTに起動。起動前空きRAM6.015 GiB。旧4 taskはDisabledのまま。genuine source pinはa68e8327914e265e6594e22e02f24bdbbfee39a5、新namespaceはc7f55e21...。元15単位を元94aab78から直接引き継ぎ、設定・データ・41特徴量・精度・seed29・CPU1・300反復を保持。
- 全入力を10:31:56 JSTに再認証。ranking fold6は10:32:32 JSTにRUNNINGへ更新。fit直前10:33:55 JSTの空きRAM3.668 GiBが3.5 GiB条件に合格。10:40:52 JSTに実PID11120生存と同fold実行中を一回確認。
- 確認時working set3.838 GiB、ここまでのpeak5.641 GiB、private commit3.646 GiB、OS空き2.753 GiB。実学習全体のpeak保証ではない。継続PID/CPU監視はしていない。
- 新しい完了foldはまだ0。元checkpoint/campaign hashは不変、h5元campaign7/9、seed43/h20 Final Candidate未起動。ranking6のみ旧ログから条件付き概算9〜12時間、全体完了日数は根拠不足で出さない。復旧実装は完了、残り計算と正式campaign統合は分ける。
- 根拠: docs/evidence/memory-recovery-20261003/active-resume-confirmation.json、first-fit-headroom.json、guarded-checkpoint-import.json。元コード同値72 pass、統合80 pass、本番認証2 pass、Ruff/strict mypy50 source pass。Classic以外のアプリ終了、OS変更、外部upload/課金/注文なし。

## 2026-10-03 — 保存進捗移行とfit直前RAM条件

- 09:59 JSTに旧11 outer fold + 4 tuning unitを新namespaceへimport/reloadし完全一致。Optuna4 terminal trialとduration/budgetを保持。元checkpoint/campaign hashは不変。新しいfitは0件。復旧peak working set1.444 GiB、private commit2.171 GiB。
- モデル行列構築後に不要な元特徴量配列を解放し、各fit直前に空き物理RAMを一度確認するopt-inを追加。不足ならnative fit前に止まる。連続PID/CPU監視やOS設定変更はしない。3.5 GiB条件の根拠は合成測定の保守的推計で、native上限の数学的保証ではない。
- 10:01 JST空きRAM6.085 GiB。guard付きで単独workerのみ再開する手順を検証中。実起動・新規完了は別の実測で報告する。D090、LOCAL_MEMORY_RECOVERY.md、capacity-budget.json参照。

## 2026-10-03 — 同値のファイル配列と全列認証によるメモリ削減

- 必要列のみの入力でも元の全列 byte/content hash を照合し、全 Build/V0/V1/V2/Dataset ID が09:25 JSTに一致した。認証 peak working set は1.134 GiB。元checkpointは未変更。
- 同じdtypeの作業配列をローカルファイルに保持し、不要なsource/tuning/fold/diagnostic配列を早く解放するopt-inを追加。元コードとの独立比較66 pass、変更後統合76 pass、本番PIT/build2 pass、Ruff/strict mypy50 source pass。数値・特徴量・split・seed・300 iterations・CPU1・評価・holdoutは不変。
- Classicのみ通常終了済み。09:36 JSTの空き物理RAMは5.572 GiB、ディスク約212 GiB。小規模合成測定は実データ最大foldのメモリ上限や残り時間の保証ではない。実学習はまだ起動しておらず、4 taskはDisabled。D089とLOCAL_MEMORY_RECOVERY.md参照。

## 2026-10-03 — メモリ局所修正と明示的checkpoint importを実装、RAM不足で起動保留

- 前処理3箇所とOOF/diagnosticsのfold選択を列単位のdtype-preserving copyへ変更。対象行、並び順、値、特徴量、モデルparameter、300 iterations、CPU 1 thread、holdout境界を変更していない。usableはdevelopment構築後に解放。
- 新しいcode_commit専用namespaceへの明示的import bridgeを追加。旧namespaceを読み取り認証し、データ/config/特徴量順/split/有効parameter/OOF hash一致と旧新code・依存lock・passing fixture証拠をlineageに保存。Optunaは元SQLiteを読み取りbackupし、trial内容・日時・duration・残りbudgetを継承。旧commit/hashを名乗らず、旧成果物・FAILED履歴を書き換えない。CLI --checkpoint-import-planは指定時だけ有効。
- 旧実装との独立した小規模parity 54 pass、bridge 16 pass、本体追加テスト66 pass、既存checkpoint/stage/provenance対象14 pass。Ruffとstrict mypy 49 source pass。巨大実データの学習peakや残り所要時間は未測定。
- 01:39 JSTの狭い実データ確認で、11 outer foldと4 tuning unit全15件のsplit位置hash/日付/特徴量/config/parameter evidenceを再導出して完全一致。保存OOFのbyte/content hashも認証し、旧manifest/progress hashは不変。Dataset bundle byte hashを確認したが、全列のlogical content IDは今回再計算していない。
- 01:34 JSTの単発メモリ確認は物理15.666 GiB、空き6.309 GiB。実列/行数から初期float64配列だけで最低7.771 GiB、後段8.802 GiB + float32 model input 0.523 GiB。非float列/index/CatBoost内部/認証一時領域は含まない。安全条件を満たさないため実データimport・resumeは行わず、StockAI-Goal3-CandidatesはDisabledのまま。
- 保存進捗はh5 Final Candidate 7/9、CatBoost29 regression1–6/ranking1–5保存、ranking6 FAILED、seed43 PENDING、h20 Final Candidate未初期化のまま。新source pinと明示的plan、十分なメモリを整えてから単発resumeを検証する。旧campaignの7件を新commitへ無断で混合しない。
- 検証根拠: workspace stock-memory-review/{thin-data-preflight.json,memory-preflight.json,parity-results.xml,bridge-results.xml,main-results.xml,main-regression-results.xml}。外部upload/VM/課金/注文/OS変更/他アプリ変更は行っていない。D088参照。

## 2026-10-03 — 前処理の列単位copyパッチを合成fixtureで検証、外部CPU移行は設計のみ

- 調査記録時刻: 2026-10-03 00:31 東京 (標準時)。同条件の再起動を行わず、候補taskの一時Disabledを維持。
- 初期usable / development / tuningの行選択を、値・列・dtypeを変えない列単位copyに置き換える未適用patchをworkspaceのstock-memory-reviewへ保存。本体src/runner/依存/研究条件/checkpointは今回未変更。
- 合成fixture38 pass（9.46秒）。89 float64列の行選択、欠損・extension dtype・index・hash・独立性を確認。LightGBM/CatBoostの小規模OOF・report ID・指標・境界・parameterは旧版と完全一致。既存checkpoint/stage対象13 pass（3.62秒）、overlay Ruffとstrict mypy 48 source pass。
- 一番大きいfloat64 blockを89列分から1列分へ分割できるが、総データ量は不変。後続fold/diagnosticsの深いcopyと実peakは未検証であり、実データ復旧を宣言しない。
- code_commitを含むnamespaceに対する未検証の互換変更を避け、本体適用・11foldの新namespace import/reload・resumeは保留。旧保存成果を削除/改変しない。
- docs/CLOUD_CPU_PILOT.mdをD087のexport manifest/path map/import bridge/許諾事項で更新。DO64/128 GiB・RunPod GPUの公式価格参考を記録し、起動許可や速度/残日数の見積もりとは扱わない。外部upload/VM/課金/他アプリ終了/OS変更/注文なし。

## 2026-10-03 00:06 JST — Final Candidateメモリ対策・復旧は未完了

- h5 Final Candidateは7/9 SUCCEEDED。CatBoost seed29はranking fold5まで保存済み、fold6はFAILED、seed43はPENDING。h20 Final Candidate campaignはまだ作成されていない。Full Ablation完了と混同しない。
- 元の失敗は2026-10-02 16:39 JSTまでに発生し、今回のSolver再開19:07 JSTより前。今回のSolver再開が元の失敗を起こしたとは判定しない。現在の大きなEdge割り当てと過去の失敗の因果も未確定。
- 完了11 outer foldのメタデータ・Parquet・内容hashを、既存認証関数でread-only検証した。Optuna 4 unitを含む15 SUCCEEDED unitを保持。モデルsource/dependencyは固定commit `94aab783dce5d01cf5ee153297891a42cfdfe53e`と同一、41/51特徴、seed、300 iterations、1 thread、tuning/validation/diagnostics条件とlocked holdoutは変更していない。
- 候補専用の自動再試行タスクを一時無効化し、子workerがない孤立candidate PowerShell wrapper1個だけを終了。独立の単発attempt19はデータ認証のreset-index copyで248 MiB allocationに失敗した。自動再試行や他アプリの終了は行っていない。
- D086に従い、candidate runnerの子プロセスだけに`PANDAS_COPY_ON_WRITE=1`を設定。対象テスト15 pass、sorted/unsorted/non-default-indexのhash parity 3 case pass、既存11 foldは新copy modeでも認証pass。全件float64/object blockの冗長copyを抑える。モデルsourceや入力の精度・特徴数を変更したものではない。
- 新設定の単発attempt20はデータ認証の従来エラー箇所を越えたが、後続準備で`Unable to allocate 2.64 GiB ... (89, 3985623) float64`となり23:59 JSTにFAILED。ranking fold6のattempt/statusは以前の2/FAILEDのままで、学習再開の検証は未達。失敗attempt19/20のログとcheckpointを保存した。
- メモリの単発確認は物理15.67 GiB/空き4.88 GiB、commit limit63.62 GiB/空き19.12 GiB。Edge utility process1個はprivate約13.96 GiBで、通常ブラウザ配下（headless/一時自動化profileではない）。ブラウザやその他のアプリは終了していない。実際の学習peak未測定なので安全に必要なRAM量は未確定。
- 復旧の残りは共有メモリの解放または明示的な追加対策判断後の単発resumeとcheckpoint進行確認。通常ブラウザの終了・OS/pagefile設定・有料resourceは今回実施しない。`StockAI-Goal3-Candidates`は一時Disabledのまま。失敗の再試行ループを再開しない。

## 2026-09-27 — Goal 3 Feature Selection固定

- 5日・20日のFull Ablationは各9/9、計18/18 batch `SUCCEEDED`。同一horizon内はLightGBM / XGBoost / CatBoost × seed 17 / 29 / 43。1日はD080判定どおりFinal Candidateから除外し、1日除外判定を変更していない。
- 認証済み18 report / OOFと既存1日判定だけを入力に、D075のstrictly-earlier tuning-period seed voteを実行。feature selection artifact `artifacts/selections/goal3-features/13c8676f84f24eaceaa2015395794cda0e1b2e249dfe5412640a31b6e8e9c81d/13c8676f84f24eaceaa2015395794cda0e1b2e249dfe5412640a31b6e8e9c81d.json`を不変保存し、Experiment Registryへidempotent追記。再読込認証で18 source report、horizon 5 / 20、`locked_holdout_accessed=false`を確認。
- 5日はF2 MACD 3/3 seedとF12 Candle / breakout 2/3 seedを採用し、V0を含む41特徴を固定。20日はF6 Volatility / downside 3/3、F7 Volume / money flow 3/3、F10 Relative / market context 2/3、F12 Candle / breakout 2/3を採用し、51特徴を固定。exact列と全F1〜F12 voteはartifactを正本とする。
- 18 reportのrealistic cost評価はすべて`BLOCKED_BY_DATA_CAPABILITY`。D080のmodel-family棄却全条件を満たせないため、5日・20日とも3 familyを`ABLATION_HOLD`としてFinal Candidate比較へ残す。これはChampion採用の判定ではない。
- D084に沿い、1日除外証拠hash付きの5日・20日選択を研究schema / CLI / 後続選択・holdout reportで受け入れる。従来の1 / 5 / 20日構成も維持する。研究workerの停止・再起動・重複実行はなく、locked holdoutは未開封。
- 選択source / artifact checkpointは`9f0f5a8ce04fd578822bf4b8b2f912a761f61a58`。`.venv`でRuff、strict mypy（48 source）、Python通常260 pass、coverage付き260 pass / 85.34%、web ESLint / TypeScript / Vitest 18 pass / build / Edge E2E 6 pass。既存Starlette deprecation warning 1件のみ。
- 固定artifactを使い、5日・20日の各3 family × 3 seedのFinal Candidate campaignを独立runnerへ委譲した。全候補完了までmodel / ensemble / hyperparameterを確定済みと扱わない。
- Final Candidate source pinは`94aab783dce5d01cf5ee153297891a42cfdfe53e`。最初のTask Scheduler起動は終了コード1で、引数`-RunDiagnostics:true`のWindows PowerShell 5.1 bool binding失敗を再現。手動の同等runner入口で`h5-lightgbm-s17`を一度だけ開始し、停止・再起動なしで継続中。
- D085のTask境界修正後、`StockAI-Goal3-Candidates`を同じsource pinとselectionで再登録。タスクの直近結果は`0`で、実行中runnerのexclusive lockを`LOCKED`として認識し重複workerを起動しなかった。Windows再起動後も同taskから同じmanifest / checkpointをresumeする。WinPS 5.1の日本語path入りSTARTED status・数値bool引数のread-only回帰test pass。今後の進捗確認はユーザー要求時だけ`runner/candidate-runner.ps1 -Action status`を1回実行し、継続監視しない。

## 2026-09-24 — Sites公開版のUI更新完了

- ユーザーの公開指示を受け、D083に従い既存Sites companionへUIを移植。同一URL `https://stock-ai-decision-support.manato0618.chatgpt.site`、public閲覧のままversion 3を公開。Sites deployment `appgdep_6ab3fbefd368819185dc93b0ae2650e0`は`succeeded`（2026-09-24 01:19 JST）。
- 公開source commit `e9d53ca44fdf978b42b2feb0f5d1dc9c64c82483`、保存version `appgprj_6a8db03cc2148191ab25ed902dd2b950~appgver_1912e3b101688191b5eadbf71cf40908`。同一commitのWorker/client成果物だけをarchive化して保存・公開した。
- ホーム / 今日 / ランキング / 検証 / 設定を切替可能。設定の分類タブ、折りたたみ説明、白・薄灰・青のUIを反映。公開版は実台帳と未接続のまま、金額は`—`、提案は`NO PROPOSAL`。古い取得期間・固定の進捗表示は撤去した。
- `hosted`のESLint、TypeScript noEmit、production buildをpass。ローカルHTTP 200・初期HTMLを確認。Edgeで360pxの5画面、設定タブ、直接hash遷移、横はみ出しなし、page error 0を確認。Sites本番の成功はnative deployment結果で確認した。
- Windowsの公式公開helperのnpm shim解決とGNU tarのdrive-letter解釈に失敗したため、既存npm CLIの直接入口と一時`TAR_OPTIONS=--force-local`で再実行。依存・lockfile・認証・DB schemaは変更せず、成功した検証とbuildを再利用した。
- 認証済み本人の安全確認だけを保存する仕組み、D1、既存OG画像は維持。APIキー、実口座・提案・約定台帳、J-Quants data、研究成果物をアップロードしていない。localhost APIへのproxy / tunnelなし。
- 研究コード・runner・worker・locked holdoutは未変更、進捗statusの取得や学習監視も行っていない。Registryの既存未commit追記は引き続き保持し、公開用checkpointには含めない。

## 2026-09-24 — PWAのUI整理（研究とは独立）

- ユーザーの追加要望に沿って`web/`だけを改善。下部5ナビをアイコン付きで統一し、設定を「口座・資金 / AI・データ / 通知」のタブで整理。ランキング・検証も共通タブへ統一した。
- 白・薄灰・青の簡素な画面へ変更。Todayは株数・変更量・取引後の推定現金を優先し、説明文・口座別の詳細・モデル情報は折りたたむ。Homeの金額表示と保有一覧も整理。D082に方針を記録。
- stale提案をTodayと直接review URLで遮断。Paper観測0件は未観測表示。空欄金額を0円へ変換せず、更新時刻はJST固定。実注文・採用モデル・提案計算の仕様は変更していない。
- `web`で`npm run lint` / `npm run typecheck` / `npm run test`（18 pass）/ `npm run build` / `npm run test:e2e`（Edge 6 pass）。既存の判断変更→保存→一部約定→翌日保有へのE2Eも維持。360 / 390 / 430 / 1280pxの5主要画面で横はみ出しなし。キーボードのタブ操作・stale遮断をブラウザでも確認。
- `web/test-results/ui-layout-UI-routes-stay-readable-at-*/`にfixture画面の確認用スクリーンショットを生成し、目視確認済み。表示用fixtureはテスト用一時DBのみで、実台帳へ入力していない。
- Python source、`pyproject.toml`、`uv.lock`はrunner固定source `d40d33c`との差分なし。runner・workerの停止／再起動／重複起動／監視は行っていない。Registryの既存未commit追記は保持し、UI checkpointへ含めない。Python全suiteは今回のfrontend-only変更では再実行していない。
- ローカルPWAをbuild済み。`hosted/`と公開サイトは今回更新・配信していない。実データ受入・研究・前場データ等の既存BLOCKED条件は未変更、locked holdout未評価、実注文なし。
- 研究の再開地点・手順は下の2026-09-20記録を参照。最新研究進捗はこのUI作業では取得していない。引き続きユーザーが進捗を要求した時だけread-only statusを1回実行する。

## 2026-09-20 02:09 JST — 20日Full Ablationの検証停止修正・独立runner再開

- 5日Full Ablationは9/9完了。20日v1は最初のh20-lightgbm-s17が学習前の期間検証（579日／必要580日）で10回失敗。遅い学習とは区別する。
- 正常なPython workerが存在しない安全境界でStockAI-Goal3-PhasedをDisable。workerの停止・重複起動はしていない。
- D081を結果前に固定。必要日数・seed数・研究条件を緩めずcausal timestampで境界を補正する。旧成果物を保持し20日v2へ移行する。
- 修正source commitは`d40d33c3020af5063b34321cf5444a8ef1a940b1`。20日v2 manifest/checkpoint/logを別namespaceで使用する。5日v1全9 report/OOFの内容hash認証は成功し、再学習しない。
- 実Datasetのdate / label_end / status列だけで構造preflightを実施。20日development 936日、修正後tuning 580日（2,151,856行、末尾2024-08-13）、outer境界2024-09-12（候補1,253,466行）。holdout境界2026-03-04は不変、target値・成績は参照していない。
- `.venv\\Scripts\\python.exe -m ruff check .` / `mypy src`（48 file）pass、`pytest -q` 258 pass、`pytest --cov -q` 258 pass / branch込み85.36%。runner隔離test 17 pass。未完了campaignをhistorical-completedとしてskipする試みも拒否。
- `web`のnpm lint / typecheck / test（6 pass）/ build / test:e2e（Microsoft Edge 1 pass）を全pass。既存Starlette deprecation warning 1件のみ。uvはこのshellのPATHにないため既存固定`.venv`を直接使用し依存更新なし。
- 同じStockAI-Goal3-PhasedをEnable/Start。起動確認でTask `Running`、新campaign `4b9ec00d4b844320480e4b865f9cce58e265f8e19de139d586d91b695777c6d8`、h20-lightgbm-s17 `RUNNING` / attempt 1 / 02:09:36 JST開始、後続8 batch `PENDING`を確認。開始直後のためデータ認証を含むbatch起動の確認であり、fold学習完了の確認ではない。
- source checkpoint `d40d33c`、全gate後のrunner pin checkpoint `d643a6e`。Registryの既存未commit追記は保持し今回のcode commitへ混ぜていない。
- 今後の進捗入口は`powershell -NoProfile -ExecutionPolicy Bypass -File runner/goal3-phase-runner.ps1 -Action status`をユーザー要求時に1回だけ実行。長時間処理はrunnerへ委譲し、継続監視なし。holdout未評価、実注文なし。

## 2026-09-09 — CPU cloud試運転の事前調査

- `docs/CLOUD_CPU_PILOT.md`に1台の試運転案、起動前gate、費用・終了条件を記録。クラウド作成・課金・転送・学習起動は未実施。
- SSH関連CLIは利用可能。固定Dataset Parquet単体は1,858,772,624 bytes。BuildのWindows絶対パス参照を確認し、Linuxへ単純コピーして実行可能とは扱わない。
- 次はユーザー所有アカウント・予算の確認と、隔離したdevelopment-only export/import・Linux互換検証。J-Quantsの本人専用cloud利用範囲も転送前に確認する。
- 今回は文書のみ変更。研究source / lock / local worker / campaign / checkpoint / Registryには書き込まず、holdout未開封。継続監視は行っていない。

## 2026-09-08 14:56 JST — 5日Full Ablation再開

- 1日screen全6 reportのmetadata/report identity、Parquet byte hash、OOF全内容hashを認証。XGBoost回帰は3 seedでRank IC 0.01023 / 0.01578 / 0.01190、各5/6 foldが正。CatBoost rankingは0.04193 / 0.04129 / 0.04463、正foldは5/6・5/6・6/6。
- 全reportのrealistic-cost評価がBLOCKED_BY_DATA_CAPABILITYのため、D077/D080の評価不能時除外ルールを適用。1日は今回のFull Ablation / Final Candidateから除外。追加価値なしを実証したのではなく必須証拠不足。他の増分gateは未評価をnullで保存し、測定失敗と混同しない。
- 判定はartifacts/decisions/goal3-one-day-screen-v1.json、監査入口はrunner/audit-one-day-screen.pyに保存。
- 既存StockAI-Goal3-Phasedを起動。開始確認1回でFIVE_DAY_ABLATION、h5-lightgbm-s17 RUNNING / ALIVE、campaign 3247a20775984f2676f63d1d3e8c86e64c036edda1060efb78965fcafe0c1843を確認。5日9 batch → 20日9 batchへ独立runnerが進む。
- 研究source/seed/特徴定義は不変、holdout未開封。進捗要求時のみread-only statusを1回実行し、継続監視しない。

更新日: 2026-09-05
状態: `GOAL3_INDEPENDENT_RESEARCH_RUNNING`

## Goal 1で実装したもの

### Repository / runtime

- Python 3.12 + `uv`、`src/` layout、strict mypy、Ruff、pytest、branch coverageを構成
- `.gitignore`と`.env.example`を追加し、credentialをsourceへ保存しない構成にした
- 非ASCIIのWindows pathでeditable `.pth`が壊れる場合の`--no-editable`手順をREADMEへ記録
- installed `stock-ai` console entry pointをtestで直接起動する

### Domain / state

- Security、Account、AccountBucket、Position、CashState、TaxState、MarketSnapshot、Prediction、PredictionUncertainty、TransactionCostEstimate、PortfolioState、TargetPosition、PortfolioProposal、ProposalAction、UserDecision、ExecutionRecordを不変型として実装
- 同一銘柄のNISA / 課税口座同時保有を`(symbol, account_bucket_id)`で分離
- AI提案、ユーザー判断、実約定、次状態を別recordとして保持
- 重複口座状態、矛盾したproposal/action/value、mixed model provenance、NaN/Inf、execution replay・時刻・status矛盾をfail closed
- 実約定費用を取得原価と実現損益へ反映し、税年境界でYTD状態をreset

### Point-in-time features

- `available_at <= as_of`を強制し、naive timestampと11:30時点の同日未完了barを拒否
- Feature Registry、FeatureSet V0（24特徴）/ V1 Core（58特徴）とdefinition / manifest hashを実装
- return、SMA/EMA、distance/slope、crossとcross後経過日数、MACD、RSI、Bollinger、ADX/+DI/-DI、ATR/NATR、volume、trading value、turnover、OBV、MFI、財務、TOPIX/sector relative、market volatility/breadthを実装
- sectorとbreadthをcandidate subsetから再計算せず、明示的PIT context入力から計算
- 必要capability、coverage、有限・正値条件が欠ける場合は`BLOCKED_BY_DATA_CAPABILITY`としてfail closed

### Baseline ML

- immutable Parquet + JSON dataset snapshot、feature manifest hash、1/5/20日target infrastructureを実装
- label endpointの`available_at`を保存し、snapshot cutoff時点で未成熟の将来labelをblankにする
- Goal 1 targetを「調整後終値間absolute returnのfixture研究proxy」と明記
- Momentum baseline、fold内imputation/scaling付きRidge baselineを実装
- expanding walk-forward、overlap purge、horizon以上のembargo、daily cross-sectional Rank IC、locked final holdoutを実装
- random split/shuffle APIを公開せず、0 validation foldは`BLOCKED_BY_VALIDATION`としてfail closed
- code commit/config/feature hashesを含むappend-only experiment recordを実装

### Cost / tax / Daily Portfolio Decision Engine

- commission、spread、slippage、market impactとhard ADV capを持つversioned Transaction Cost Engine
- NISA / 課税口座、源泉徴収方式、年内損益、繰越損失を扱う推定Tax Engine
- 推定税の経済効果、NISA機会費用、決済cash withholdingを別fieldに分離
- 同一bucketの複数売却を一括評価し、損失offset/refund capacityの重複利用を防止
- 現状HOLD反実仮想と全候補target portfolioを比較する上限付き離散optimizer
- available cash、minimum cash、symbol/sector、positions、turnover、liquidity、no-trade thresholdを実装
- 100株単位のtrade deltaを強制し、BUY / HOLD / REDUCE / SELL / SKIPを株数で出力
- policy effective date / bucket policy ID / market price / prediction provenanceを検証
- proposal ID、policy version、tax assumptions、current/recommended market value、人間向け理由を監査fieldとして保存
- 実注文送信機能は存在しない

### CLI

`stock-ai fixture-demo`で次を決定的に一巡する。

```text
fixture OHLCV / 財務 / TOPIX / sector / breadth
→ FeatureSet V1 Core 58特徴
→ point-in-time dataset snapshotと1/5/20日proxy label
→ Ridge predictionとpurged walk-forward validation
→ current portfolio / cash / tax state
→ cost / tax / whole-portfolio proposal
→ target sharesとBUY/HOLD/REDUCE/SELL/SKIP
→ manual execution fixture
→ next portfolio state
```

fixtureはproduction fallbackでも収益性の証拠でもなく、実注文は送信しない。

## Goal 2Aで実装したもの

### J-Quants V2 acquisition

- V2固定base URLと`x-api-key`認証の専用client
- credentialはlive起動時にprocess環境の`JQUANTS_API_KEY`からだけ読込
- V1 token、mail/password、refresh token、設定file、`.env`自動読込を非実装
- `pagination_key`全page取得、循環/page上限検出
- plan別逐次rate limit、`/fins/summary`個別limit、`Retry-After`、429/5xx/network bounded retry
- sanitized errorはstatusとendpointだけを持ち、headerとresponse bodyを含めない
- Free既定: 銘柄master、株価日足、財務summary
- Light明示選択: 営業日calendar、TOPIX日足

### Immutable storage / catalog

- raw / normalizedをcontent-addressed immutable Parquet objectとして保存
- Parquet + manifestを一時directoryで完成後、directory単位でatomic publish
- payload再取得をobject IDでdeduplicateし、訂正payloadを別versionとして保存
- Parquet SHA-256、payload hash、schema version、row数、品質結果をmanifestへ保存
- DuckDBへingestion run、object、run-object対応、品質issueをtransaction記録
- 中断または品質失敗時も既存の正常objectを置換しない
- manifest/path/hash不整合を検出する`stock-ai data verify`

### Normalization / point-in-time

- 全external recordへ`provider/source_endpoint/source_date/received_at/available_at/as_of/payload_hash/schema_version/ingestion_run_id/source_record_hash`を付与
- J-Quants 5文字codeを原値`provider_code`として保持し、内部4文字`symbol`を別保存
- 日足のraw execution参照系列とresearch調整系列、`AdjFactor`、adjustment versionを分離
- 財務開示日時、主要実績・予想値、期末発行株式数・自己株式数を正規化
- 営業日区分0/1/2/3を保持し、equity business dayを1/2だけに限定
- APIが過去訂正時刻を返さないため`available_at = received_at`とし、初回取得前へ値を遡及させない
- DuckDB PIT読取はcutoffまでに受信したnatural key最新版だけを返す

### Quality / capability

- required schema、natural key重複、requested date、issue code、OHLC、volume、adjustment factor、disclosure時刻を検証
- 品質errorはrawとreportを残すがnormalized publishを止め、runを`FAILED`にする
- plan / data capabilityを`AVAILABLE / PARTIAL / BLOCKED_BY_PLAN / BLOCKED_BY_DATA_CAPABILITY / OUT_OF_SCOPE`で明示
- 期末発行株式数、初回取得以前のhistorical universe訂正、coverage未確認breadthを`PARTIAL`として推測補完しない
- 認証なしlive commandは停止し、fixtureへのproduction fallbackを行わない

## Goal 2で追加実装したもの（実データ履歴取得待ち）

### Historical acquisition

- 公式V2 Bulk List / Get、gzip CSV、signed URLのcredential非送信・非保存を実装
- Bulk file fingerprint単位のDuckDB checkpointを追加し、`RUNNING / FAILED`を安全にresume
- Bulk fileをsource dateごとに分割し、既存のraw / normalized / quality / immutable publish pathを再利用
- `stock-ai data history --start ... --end ... --plan standard`を追加
- 空Bulk list、header-only CSV、範囲外row、圧縮展開上限超過をfail closedし、file全体が完了するまでPIT queryから不可視化
- resume時はcheckpoint件数だけでなく、紐付く成功run/object/fileの完全性を再確認

### Production point-in-time data

- 営業日別master完全一致からhistorical universeとlisting / delisting intervalを構築し、current universeの過去適用を禁止
- source revision vintage（received_at）とderived observation timeを分離し、日足/TOPIX/contextは次営業日11:30、財務は開示時刻でmerge
- `SINGLE_VINTAGE_AS_REVISED / STRICT_AS_KNOWN`をartifactへ固定。前者は研究専用・採用不可、後者は復元不能labelをblock
- provider adjusted OHLCV、AdjFactor、adjustment versionからCorporate Action effective-date lineageを生成
- 期末開示の発行株式数・自己株式数を開示後だけ使い、未開示期間は0補完せずmissing reasonを保存
- PIT全universeからmarket breadthとsector return、eligible / observed / coverageを生成
- 売買停止gapでtechnical rolling windowをreset
- sector/TOPIX/beta returnも営業日gapでresetし、coverage不足breadthをmodel入力前にblock

### Production features / labels / baseline / E2E

- 同一source vintageからV1を一度だけ計算し、厳密subsetとしてFeatureSet V0（24）を生成。大規模履歴の重複計算を削減
- JPX固定calendarで1 / 5 / 20日absolute、TOPIX excess、sector excess、60日causal-beta residual、large-loss labelを生成
- endpoint価格欠損を`DELISTED_NO_EXIT_PRICE / SUSPENDED_NO_EXIT_PRICE`に分離し、次の観測価格へshiftしない
- Standard契約では12:30 labelを`BLOCKED_BY_DATA_CAPABILITY`とし、日足から推測しない
- Production Datasetをcontent hash付きParquet + JSONで固定し、未成熟labelをsnapshot cutoffでblank
- label entryを11:30より後の同日引けへ固定し、locked holdoutへlabel endが跨るdevelopment行をhorizon別にpurge
- Standardの12:30 exact labelはblock。Premiumでもrow単位entry/end/available_at/statusとcoverageを持ち、未成熟値をblank
- source 5 datasetのschema/value hash、列名/dtype、Parquet hash、metadata hashをsnapshot identityへ含める
- V0 / V1 / Datasetの全検証後だけatomic Production Build Manifestを公開し、partial buildを完成扱いしない
- locked holdout外だけでCASH / Momentum / Ridgeのwalk-forwardを行い、daily cross-sectional Rank ICと10 / 20 / 30 / 50 bps signal diagnosticをimmutable report化
- real-data Ridge predictionから最大8候補を選び、paper all-cash portfolioをDaily Portfolio Decision Engineへ渡すresearch-only E2Eを追加
- `stock-ai research build / baseline / e2e`を追加。order / execution recordは生成しない

### Goal 2 regression tests

- Bulk gzip parse、API key header境界、signed downloadへのkey非送信、checkpoint resume、範囲外row fail closed
- FAILED/RUNNING/file未完了runのPIT不可視、空archive、展開size上限、非数値volume/value、catalog/object/checkpoint照合
- current universe非遡及、財務開示時刻、Corporate Action、売買停止・上場廃止label、12:30能力不足
- future price mutation invariance、V0/V1共有値一致、Momentum/Ridge locked holdout、Decision Engine research E2E
- holdout期間価格の1/5/20日model不変、snapshot schema collision/改ざん、report/dataset provenance mismatch、Premium label maturity

## Goal 3で実装したもの（実データ研究run待ち）

### FeatureSet V2 Extended Technical

- V2 ExtendedをV1 Coreの厳密supersetとしてversioned manifest化
- downside volatility、60/120日最大drawdown、return skew、60日左裾quantileを追加
- volume z-score、20/60日売買代金比、OBV 20日傾き、CMF 20を追加
- adjusted openを推測せず、body/range/wick/close location/gapと20/60日breakoutを追加
- V2を一度だけ計算し、同一観測からV1/V0を厳密projectionする
- V0/V1/V2/Datasetを同じsource lineage・observation as-of・revision policy/statusのProduction Build Manifestへ含め、Dataset内feature値と各snapshotの完全一致を公開時・読込時に検証

### GBDT / Learning to Rank / downside

- LightGBM、XGBoost、CatBoostの回帰とLearning to Rank adapterを実装
- 1 / 5 / 20日を独立modelとして扱い、日付内relevance 0〜4でrankerを学習
- LightGBM/XGBoost/CatBoostの10% quantile回帰とabsolute-return大幅下落classifierを実装
- Brier、log loss、expected calibration error、quantile lower-tail rate / pinball lossを保存
- fold-local clipping、median imputation、相関pruningを実装し、validation値でfitしない
- bounded Optunaはtrial数・時間・seed・single-jobをconfigで固定し、strictly earlier tuning期間だけを目的関数に使う
- tuning期間と後続outer model-evaluation OOFをhorizon別に分離し、outer targetが自身のparameter選択へ入らない回帰testを追加
- COMPLETE / PRUNED / FAILを含む全Optuna trialのparameter・score・state・duration・failure reasonを保存し、COMPLETEが0件でも失敗ExperimentRecordへ監査列を残す

### OOF evaluation / ablation / ensemble / uncertainty

- 全model/task/horizon/seedのrow-level OOFを保存し、重複identityと非有限predictionを拒否
- pooled相関ではなく日付別Rank IC、ICIR、NDCG@5/10/20、Precision@K、Top-K targetを計算
- 実FeatureSet V0をF0とし、F1〜F12を直前championへ逐次追加するablationを実装。promotionはstrictly earlier tuning期間、incremental ICは後続outer期間で評価。F8/F9を非重複化し、V2にない需給F11は推測せず`BLOCKED_BY_DATA_CAPABILITY`
- OOS validation permutation importance、missing rate、fold retention率、seed間Rank IC / prediction安定性を診断
- outer OOFを時系列順のstacking fit / uncertainty calibration / final evaluationへ3分割し、label endpointで各境界をpurgeしたうえで非負・総和1 stackingと未接触区間のcoverageを評価
- absolute-return OOFをexpected return / downside quantile / large-loss probabilityへ集約し、予測as-ofより前にlabelが成熟したresidualだけでstandard errorを更新
- 1/5/20日すべてとaware `as_of`・model/feature/data provenanceを必須にした型付き`Prediction`を生成し、未成熟calibration/horizon非整合は明示block
- benchmark-excess targetはabsolute returnへ偽装せず、Decision Engine入力への変換をfail closed

### Research artifact / CLI

- report、library version、commit、config全文/hash、Build/data/V2 feature snapshot、feature definition hash、全trial/fold、選択期間、holdout境界、cost/tax/Decision Engine version、revision policyを監査field化
- OOF ParquetとJSON metadataをcontent-addressed directoryへatomic publishし、Parquet・metadata・report content hashをload時に再検証
- `stock-ai research advanced`は認証済みV0/V1/V2/Dataset Build Manifestだけを入口とし、成功・設定不正・全trial失敗・途中fold失敗・artifact公開失敗をappend-only ExperimentRegistryへ保存。完了済trial/foldとreport/Build/V2 identityを失わない
- model family / horizon / seed / estimator / Optuna / OOF行数 / model-fit数を明示的にboundし、超過時は`BLOCKED_BY_RESOURCE_CAPABILITY`
- locked final holdoutはreport APIからrowを返さず、Goal 3 development reportは常にresearch-only / adoption不可
- deterministic fixtureでlibrary数値・漏洩境界・artifact改ざんを検証済み。live catalogは2017〜2020を受入済みだが、全取得期間の確定前なのでProduction Datasetは未生成

## Goal 4で実装したもの（live前場provider・model採用はblocked）

### Morning data / freeze contract

- provider-neutralな09:00〜11:30 bar契約と`MorningFreezeMetadata`を実装
- `available_at <= 当日11:30`、aware JST timestamp、exact cutoff、価格・出来高・売買代金、重複をfail closed検証
- current holdingとdaily candidateのunionを監視universeにし、bar universeとの完全一致を検証
- freeze provider / source snapshot ID / 全source record IDをstock・TOPIX・sector入力と完全一致で検証
- freezeのholding / candidate roleとcapability reportをfeature rowへ完全一致で検証
- live provider未設定時は全capabilityを`BLOCKED_BY_DATA_CAPABILITY`とし、fixtureへfallbackしない
- bar区間volume/valueとsession累積を分離し、日次出来高から前場値を推測しない

### F13 / F14 features

- `morning-core-v1`をmachine-readable Feature Manifestとして実装
- 09:00→09:05 / 09:15 / 09:30 / 10:00 / 11:00 / 11:30 return、前日終値gapを実装
- 同時刻TOPIX / sector relative、high / low / range、realized volatility、VWAP、range位置を実装
- 各cutoff cumulative volumeと、当日を除く過去20session同時刻volume / trading-value progressを実装
- monitored / candidate volume rank、holding / candidate role、freeze済みdaily prior forecastを実装
- `morning-microstructure-v1`をF13 strict supersetとして定義し、quotes / order book / trade frequency能力がある列だけ実装
- 部分F14をcapability固有の`morning-microstructure-v1-<feature-subset-hash>` manifestとして保存・再認証
- exact cutoff欠損、宣言済みmicrostructure列欠損、11:30後のbarを推測補完せずblock

### Morning model / Decision compatibility

- 1 / 5 / 20日daily forecastに対する残差更新datasetを実装し、label entryが11:30より後であることを強制
- label entryを同一session exact 12:30、endをartifactに認証した固定JPX calendarの1 / 5 / 20 session後へ固定し、aware `label_end_at`以前のavailabilityを拒否
- 未成熟labelをpublication cutoffでblankにし、label statusを保存
- fold学習・OOF較正とも`label_available_at < prediction.as_of`を要求し、遅延訂正をendpointへbackdateしない
- no-update daily forecastに対し、固定parameter Ridge / LightGBM / optional small MLPをpurged expanding OOFで比較
- modelごとにMSE、日付別Rank IC、revision win rate、holding / candidate row coverageを保存
- OOS改善がないmodelを`REJECTED`、改善してもdevelopmentでは`RESEARCH`に留め、自動Champion昇格しない
- small MLPは既定`DISABLED`。1D-CNN / TCN / GRU / small Transformerは同期sequence履歴不足で明示block
- `label_end < prediction date`かつ`label_available_at < prediction.as_of`のresidualだけでdownside / large-loss / uncertaintyを更新
- daily priorとmorning revisionの両provenanceを持つ型付き`Prediction`をDaily Portfolio Decision Engineへ接続
- 1 / 5 / 20日、同一as_of、同一prior bundle、全freeze universeを満たすPrediction batchだけを生成
- 認証済みreport / Datasetからresearch-only modelを再fitし、履歴終了後の翌営業日11:30をoutcomeなしで推論
- refit bundleは認証済みfactoryだけで生成し、report / dataset / family / seed / training boundary / estimator contract / fitted state hashを一つのidentityとして再検証
- current 20session profile欠損をimputeせずblockし、feature行content hashを再照合してfreeze済みprice / liquidityと全universeをtyped adapterでEngineへ渡す
- provider / source snapshot+record / role / capability / report ID / price / ADVを`research-only` proposalまで保持し、実Portfolio保有と評価Candidateへ再照合
- Morning modelはActionを直接出さず、current inference batchをEngineへ渡し、別の決定的fixtureでHOLD / SKIPからSELL / BUYへの変化がEngine経由で生じることを確認
- Decision EngineはMorning predictionの混在、Portfolio freeze不一致、auditと評価Candidateのprice / ADV不一致を拒否

### Immutable artifacts / CLI

- Morning Datasetとrow-level OOF reportをschema・値・source ID・manifest・Parquet/metadata hash付きで保存
- content-addressed directoryを一時directory完成後にatomic publishし、再利用前に認証
- `research morning-capabilities`と、明示fixture専用`research morning-fixture`を追加
- fixture commandは`research_only=true / order_instruction=false / live_provider_used=false`を明示
- fixture commandは履歴dataset→OOF→research refit→翌営業日の4銘柄current Predictionまで実行

## Goal 5で実装したもの（local運用完成・live acceptanceはblocked）

### Operational ledger / user workflow

- SQLite WAL台帳へPortfolio、AI提案、version付きユーザー判断、実約定、翌日状態を別recordで保存
- proposal/date、decision/version、execution IDをpayload hash、catalog identity、foreign keyで検証し、同一identityの異内容を拒否
- 提案生成に使った`DecisionEngineConfig`全文をproposal IDと生成時刻へ結びつけた不変policy snapshotとして保存し、proposal / archive証跡 / policyを同一transactionで公開。snapshot欠落・改ざんは提案台帳のintegrity違反として拒否
- 判断reviewは全lineを必須とし、AI推奨または取引なしの検証済み候補だけを許す。bucket別現金とexact cost/taxを再計算し、未再最適化株数は保存しない
- 手動約定は方向・注文/約定株数・時刻を判断と照合し、next Portfolioは実fillだけから原子的に生成。proposal/decisionは上書きしない
- 同一銘柄の複数account bucketを全画面・台帳・照合で分離

### Automation / recovery

- data sync、candidate、Morning capture、11:30 freeze、prediction、proposal、notification、EOD、monthly challengerのstage contractを実装
- process lock/heartbeat、handler前RUNNING、成功確定時のlock owner/expiry再照合、stable logical-stage idempotency key、同一workflow upstream gate、freshness/proposal lineageを保持した成功stageの状態repair、失敗・block記録を実装
- proposal archive完了前の通知を拒否し、stale/error時は同日archive済みでも提案を表示しない
- live handler未設定時は`BLOCKED_BY_DATA_CAPABILITY`で停止し、fixtureや前日提案へfallbackしない
- Windows Task Scheduler登録scriptを表示するが自動実行せず、ユーザーreview後の手動登録に限定
- payload/catalog/FK/SQLite integrity検証、status→same-day archive済みproposal照合、atomic no-replace backup、read-only元と明示確認付きrestore、restore前後検証を実装

### Mobile PWA / API

- React / TypeScript / Viteのmobile-first PWAとFastAPI local APIを実装し、`127.0.0.1`でserve、Host/Originもlocalhostへ限定
- 5項目下部nav、Home、Today、Decision Review、Decision Saved、Execution、Ranking、Stock Detail、Validation、正式capital/model下層を含むSettings、Data Operationsを実装
- Settingsの現金・保有・税状態に加え、最低現金比率、最大保有数、銘柄・業種・turnover・ADV上限、改善閾値等をarchive済みproposalのpolicy snapshotから表示し、未登録値を推測しない
- TodayはSELL/REDUCE/BUYを優先、HOLDを折り畳み、SKIPを変更一覧から除外。株数中心でcurrent→recommended→differenceを表示
- 100株制約・cash/cost/taxを安全な選択候補ごとに再計算し、未再最適化または違反中は保存不可。判断保存と約定記録にはmanual intent headerを必須化
- Ranking候補順位と最終Portfolio Actionを分離し、Stock Detailは同一symbolのaccount bucket tab、加重取得単価、口座別Actionを分離表示
- loading / empty / stale / error / fixture状態、data/model timestamp、model version、no-order disclaimerを表示
- service workerはstatic shellだけをcacheし、`/api/` responseをcacheしない。open tabもvisibility/online/60秒で再取得し、offline時は保持提案を破棄
- CSP、frame拒否、referrer拒否、secret value非表示を実装。broker/order routeは存在しない
- Playwright / Microsoft Edge / disposable fixture台帳でToday→判断変更・保存→一部約定→実保有反映→Homeの実backend込みE2Eを固定gate化
- E2EはNTTのSELL 500株中100株の部分約定を記録し、apply後のHomeで実保有が500株から400株へ変わったことをexact assert

### Import / Paper validation

- 約定CSVと口座状態CSVをpreview-firstで取込み、逆売買・注文株数・累積fill差異をconflict化し、明示確認後だけappend。判断前時刻は確認でも拒否
- 口座状態CSVは非ゼロPOSITIONと全bucketのCASH row、available / reserved cashを必須とし、保有・現金を原子的に照合
- Paper outcomeはarchive前に登録したcontent-addressed不変JPX calendar、exact next-session経路、aware endpoint/availability、archive-before-endpoint、model versionを照合した将来観測だけを不変保存
- 1営業日・1営業日1観測だけを週次/月次compoundし、最大drawdown、minimum observation、active Champion cohort、最新行から連続するexact-version Challenger cohort、同一version隣接窓driftを実装
- minimum observationやdriftからmodelを自動昇格せず、実観測のないfixture画面は空状態を表示
- 起動、Task Scheduler、CSV schema、backup/restore、credential境界を`docs/GOAL5_RUNBOOK.md`へ記録

## 検証結果

### 2026-08-26 認証付きホスト版checkpoint

- ユーザーのremote URL要望を受け、既存localhost PWAを直接公開せず、`hosted/`へ本人限定のSites companionを実装
- ChatGPT sign-inのforwarded user headerをserver側で読み、D1にはuser別の安全境界確認状態だけを保存
- J-Quants API key、`data/live`、Production Dataset、model artifact、実口座CSVをホスト版へ送信する経路は設けていない
- 実データ不足時は`NO PROPOSAL`と不足理由を表示し、fixture、前日提案、推測値へfallbackしない
- no-order、no-broker、local credential境界、2017〜2020受入済み／2021年以降未取得の現状を画面へ明示
- D1 migration `operator_settings`、owner-scoped server action、mobile-first画面、OG preview assetを追加
- Next.js 16.3.2、React 19.2.8、vinext beta.8、Vite 8.2.2、Cloudflare plugin 1.53.1へ更新
- `npm run lint`: pass
- `npm run build`: pass
- `npm audit --omit=dev --json`: vulnerability 0
- `npm audit --json`: development dependencyを含めvulnerability 0
- Sites `create_site`は一度だけ呼び出され、実際にはdirect `structuredContent`でproject IDを返していた。当時のagentが誤って`.result`配下を参照したためIDを永続化できず、deploymentを保留した

### 2026-08-29 認証付きホスト版再開checkpoint

- Sites plugin 0.1.46の正本手順を再読し、SIWC sign-in / sign-outを`target="_top"`のtop-level navigationへ更新
- social preview assetを標準の`public/og.png`へ揃え、Open Graph / X metadataも同一pathへ更新
- `npm run lint`: pass、`npm run build`: pass、`npm audit --json`: vulnerability 0
- 再開時もagent側がdirect `structuredContent.items`を誤って`.result.items`として読んだため0件と判定していた。sessionの非secret監査情報から既存project IDを復元し、重複createせず`.openai/hosting.json`へ永続化した
- ユーザーの明示指示でホスト版の閲覧accessをpublicへ変更。公開内容は安全停止理由・準備状況・no-order境界だけで、本人別確認状態の保存はChatGPT認証を維持
- Sites access policyを`public`へ更新し、version 2を`https://stock-ai-decision-support.manato0618.chatgpt.site`へproduction deploy
- 公開URLはHTTP 200、`株AI` / `NO PROPOSAL`表示、secret値pattern不検出を確認。Open Graph / X imageは同一production originのabsolute URLへ修正済み
- live D1 binding `DB`と`operator_settings` tableを確認。public visitorはreadinessを閲覧でき、user別確認状態の保存だけがserver-side ChatGPT identityを要求する

### 2026-08-25 実データ受け入れ中間checkpoint

- 現processで`JQUANTS_API_KEY`設定済みをboolean確認。credential値は表示・保存していない
- 2026-08-24の実API preflightで、銘柄master 4,444行、日足4,444行、Calendar 1行、TOPIX 1行、財務summary 7行を取得
- 5 datasetのBulk List / Getを実確認。2015・2016年の日足BulkはHTTP 400、2017年以降は取得可能で、実file最古日は2017-01-04
- 観測capabilityはStandard相当の10年履歴と整合するが、APIにplan自己申告endpointがないため契約名そのものは自動断定しない
- REST日足は調整OHLCVを返し、Bulk日足は公式仕様どおりraw OHLCV + `AdjFactor`のみ。D064の公式累積係数式へadapterを更新し回帰testを追加
- 午後session / `AAdjO`は実REST応答・Bulkとも利用不可。exact 12:30 entry labelは`BLOCKED_BY_DATA_CAPABILITY`
- Git対象外の`data/live`へ2017-01-04〜2020-12-30を年次stage取得。Calendar scopeは2017-01-01〜2020-12-31
- Bulk checkpointは`SUCCEEDED=198 / FAILED=1`。FAILED 1件は旧schema期待による初回日足fileで、後続resume成功後も監査記録として保持
- 同一scope再実行で2017年1月は5/5 file、2017年2〜12月は45/45 fileがdownload 0でskipされ、resume完全性を確認
- `data verify --data-root data/live`: 10,808 immutable object、feature 0、dataset 0、build 0、status OK
- catalog品質issue 0件。normalized object集計は日足976 object / 3,862,418行、master 995 / 3,935,157行、財務996 / 76,076行、TOPIX 976 / 976行、Calendar 1,461 / 1,461行。rawも同数
- Production Dataset、Goal 3実データwalk-forward、特徴量・parameter・ensemble選定、Champion固定、locked holdout評価は未実行。holdoutには触れていない
- ユーザー指示により2020年stage完了を切りの良い停止点とした。次回再開点は2021-01-01
- 中間checkpoint最終gate: Ruff合格、mypy strict 43 source合格、Python 192 test合格、branch coverage 85.31%、PWA lint / typecheck / 6 unit test / production build / 1 E2E合格
- 固定日fixtureが実日付を越えて露呈した2件のoperations testを修正。stock詳細APIは任意の`businessDate`を受けて再現可能に参照でき、automation lock testは実時計を使用する
- gate後の`data verify`再実行も10,808 object / status OK。`data/live`はGit対象外で、API key値はsource・log・fixture・Markdownへ保存していない

2026-08-24に非editable installを更新後、Goal 2 final gateとして下記を実行した。`uv` executableはPATHにないため、
同じinstalled `uv 0.12.5`をsystem Pythonのmodule entry pointから実行した。

```text
python -m uv sync --all-groups --no-editable
python -m uv run --no-sync ruff check .
python -m uv run --no-sync mypy src
python -m uv run --no-sync pytest -q
python -m uv run --no-sync pytest --cov=stock_ai --cov-branch --cov-report=term-missing -q
python -m uv run --no-sync stock-ai --help
python -m uv run --no-sync stock-ai fixture-demo --snapshot-dir .demo-artifacts/final-dataset
python -m uv run --no-sync stock-ai data capabilities --plan free
```

- Ruff: pass
- mypy strict: pass（32 source files）
- pytest: 101 pass
- branch coverage: 85.08%（設定threshold 85%を通過）
- installed console entry point: pass
- non-editable packageを`--reinstall-package stock-ai-decision-support`で再buildし、主要source/installed moduleのSHA-256一致を確認
- deterministic E2E: pass、58 features、1,360 rows、3 validation folds
- local `data verify`: pass、catalogとimmutable object 12件を照合。Production artifactはlive履歴未取得のため0件
- Goal 2A fixture integration: 5 V2 endpoint、raw/normalized各5 object、PIT read pass
- idempotent refetch、non-retroactive correction、atomic failure、tamper、secret non-persistence: pass

Goal 3 checkpoint前gate（source tree）:

- Ruff: pass
- mypy strict: pass（34 source files）
- pytest: 136 pass
- branch coverage: 85.74%（設定threshold 85%を通過）
- LightGBM / XGBoost / CatBoost各4 taskの決定的OOF smoke: pass
- V2全追加列のexact formula/warm-up/zero denominator、V0/V1/V2 projection、Production Build observation/content lineage: pass
- locked holdout/outer target mutation invariance、label-maturity purge、OOF/report tamper、simplex、calibration、Decision Engine output contract: pass
- Optuna全FAIL trial監査、完全なfold/trial identity、CLI設定不正を含む失敗registry保存: pass
- 後段family/foldの失敗、非有限fold、artifact write/reload/OSErrorでも完了済監査とBuild/V2 lineageを保持: pass
- installed `stock-ai` / `research advanced --help` / fixture E2E / `data verify` / source-installed SHA-256一致: pass

Goal 4 checkpoint前gate（source tree）:

- Ruff: pass
- mypy strict: pass（37 source files）
- pytest: 161 pass
- branch coverage: 85.10%（設定threshold 85%を通過）
- exact 11:30 / provider / source / holding+candidate freeze、post-freeze source、遅延label availability: pass
- F13 exact formula / warm-up / zero-volume、partial F14 manifest / null capability value / artifact tamper: pass
- holdout endpoint purge、pre-fit resource bound、Ridge / LightGBM、3-seed全horizon MLP challenger: pass
- aware label endpoint、snapshot range identity、authenticated report / Dataset refit、model bundle factory/state認証: pass
- outcome-free current inference、全universe typed Prediction、feature evidence hash、Decision Engine exact-freeze E2E: pass
- installed `research morning-capabilities`はlive provider未設定をfail closed、`research morning-fixture`は4 current Predictionを生成: pass
- local `data verify`: 12 immutable object、Production artifact 0件、status OK
- non-editable package再build後、Goal 4主要4 moduleのsource/installed SHA-256一致: pass

Goal 5 final gate（source tree + installed wheel + Microsoft Edge）:

```text
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.venv\Scripts\python.exe -m pytest --cov=stock_ai --cov-branch --cov-report=term-missing -q -p no:cacheprovider
cd web
npm run lint
npm run typecheck
npm test -- --run
npm run build
npm run test:e2e
```

- Ruff: pass
- mypy strict: pass（43 source files）
- pytest: 189 pass
- branch coverage: 85.31%（設定threshold 85%を通過）
- frontend ESLint / TypeScript / production build: pass
- Vitest: 6 pass
- Playwright / Microsoft Edge full-stack E2E: 1 pass。Today→判断変更→保存→NTT 500株のSELLを100株部分約定→実保有apply→Home 400株を検証
- non-editable wheelを再buildし、installed `stock-ai --help` / `ops capabilities` / fixture bootstrap / `ops verify` / Task Scheduler script: pass
- installed fixture台帳: Portfolio 1、proposal / archive / Decision policy各1、status 1、ranking 4、integrity `OK`
- installed server: health `ok`、注文送信不可、Settingsは最低現金0.10・最大保有10・銘柄上限0.50等の実policy値を返し、credential valueを返さない
- Goal 5主要6 moduleのsource / installed SHA-256一致: pass
- read-only最終review（PIT/reliability、quant/Paper、portfolio/operations）: material checkpoint blockerなし
- live data、profitability、model採用はこのgateでは評価していない

read-only specialist reviewを5系統（PIT/leakage、quant、portfolio、tax/cost、software reliability）で実施し、主なhigh findingを回帰test化した。reviewerはfileを変更していない。

## 既知の制約

- Goal 1 labelは12:30 entryやTOPIX/sector excess returnではなく、調整後終値間absolute returnの研究proxy
- Goal 1 baseline uncertaintyはtraining residual RMSE。Goal 3はOOF calibrated rank-space intervalを持つが、live/full-scale empirical coverageは未評価
- Goal 2実装とlive acceptanceは完了し、2017-01-04〜2026-08-28のraw/normalized履歴と、現行市場区分が利用可能な2022-04-04以降のProduction Datasetを認証済み。Goal 3実データbaseline / advanced / final holdoutは未実行
- NISA枠の詳細な機会費用、複数broker/複数税policyのrouter、申告税額は未実装。Tax Engineは意思決定用推定のみ
- exact discrete optimizerは小さい明示candidate universe用。上限超過は近似解へ切り替えずfail closed
- JSONL experiment registryは単一process実装でinter-process lock未実装。Goal 2/3 Production snapshotとadvanced reportはdirectory atomic publish + Build Manifestへ移行済み
- Git外でartifactを生成する場合は`STOCK_AI_CODE_COMMIT`を明示しないとprovenanceが`UNSET`になる
- fixtureのvalidation結果からprofitabilityを推論しない。最終holdoutはfixture E2Eでも未使用のまま保持する
- J-Quants APIは過去訂正の発生時刻を返さないため、初回取得以前の完全なrevision historyは復元不能
- `STRICT_AS_KNOWN`ではreceipt時刻以前へbackfillを遡及させず、historical labelをblockする。`SINGLE_VINTAGE_AS_REVISED`は再現可能な研究専用で採用不可
- `/fins/summary`の`ShOutFY`は期末開示値であり、日次shares outstanding seriesではない
- J-Quants planは自動判定せず、CLIで宣言したplanより上のendpointをfail closedする
- Corporate Actionのannouncement時刻と詳細種別はdaily price endpointに存在せず、effective-date adjustment lineageのみ。推測しない
- 2017〜2026-08-28のJPX履歴取得とfull Production Dataset生成は実測済み。405万8,130行の生成では物理dtype依存hashと一括feature copyを実データで修正し、メモリ境界付き認証まで完了。Goal 3の全family/horizon walk-forward scale capabilityは実run完了まで`PARTIAL`
- Goal 3 advanced reportはdevelopment OOF専用でlocked holdoutを未開封。liveデータ、複数seed、全horizonの実runと最終holdout評価前にChampion採用しない
- OOF ensembleの不確実性は日付内rank space。絶対return金額幅へのcalibrationはlive OOSが得られるまで未採用
- Goal 4 refit bundleとcurrent inferenceは明示的research-only。Goal 5はPaper drift記録を持つが、model weightの承認済み永続registry、live推論時間、十分なlive OOS evidenceが揃うまでChampion採用しない
- Morning datasetのlabel endpointはcallerが供給するJPX session calendarとaware `label_end_at`に依存する。live provider未決のため、fixtureのpandas営業日・15:30 endpointは市場calendar/scheduleの代替でも収益性の証拠でもない
- Goal 5の実データAPI/PWAは引き続きlocalhost専用で、internetへ公開してはならない。本人限定ホスト版companionは実装済みだが、local実データや提案の同期経路は未実装で、Sites project作成結果の外部確認待ち
- PWA内通知だけ利用可能。web push providerは未設定で`BLOCKED_BY_CONFIGURATION`
- daily automation frameworkとTask Scheduler scriptは実装済みだが、live data/Morning/model handlerは外部capability待ちで、未設定のstageは安全に停止する
- Paper集計はlive forward observationが0件のため空状態。fixture proposalから収益性、drift、Champion採否を推論しない

## 実データ/APIまでblockedの項目

- 現在のCodex processは環境変数`JQUANTS_API_KEY`が設定済みであることを認識している。値は表示・保存していない。Standard capabilityと2017-01-04〜2026-08-28のliveデータ品質、年次Bulk resume、Production Buildを実取得で検証済み
- 初回取得以前のprovider correction vintage、完全なlisting/delisting/corporate-action event lineage
- 11:30時点の前場価格、出来高、market breadth、同時刻履歴
- 承認済みMorning model registry entry、live OOS比較、11:30締切内の実推論時間
- 日次shares outstanding、coverage検証済みmarket breadth、需給履歴
- 実fee条件と、local PWAへ手入力する実口座・保有・現金・NISA残枠・税状態。SBI等のCSV mappingはD068により任意で、研究のblockerではない
- spread/slippage/market-impact calibration、live/paper forward observation
- broker integrationと注文送信は仕様上blockedではなく、製品方針として対象外

## Checkpoint後の継続順

1. Goal 2 checkpoint `f5763e7`、Goal 3 checkpoint `d9b094b`、Goal 4 checkpoint `a2a359d`は作成済み。
2. Goal 5の全gateとread-only reviewは完了し、このSTATUSを含む外部依存外のclean checkpointを正本とする。
3. Standard相当Bulkの2017-01-04〜2026-08-28はcheckpoint / resume取得済み。26,030 objectを検証し、Production Build `2fc936a7ca9b939d8016ad3c5efea17c53ffd5264d5ece398a8329bf2f2dfe5f`を固定した。
4. 次はGoal 3 development-only選定と固定、locked holdout単回評価、Goal 4 live OOS、Goal 5 live Paper観測の順に実行し、model採否を追記する。
5. broker integrationと自動売買は今後も実装しない。

## 2026-08-29 実データ研究再開

- ユーザー指示によりSBI口座状態CSVを必須条件から外し、local PWAへの手入力を初期運用の正本とした（D068）
- Goal 3実データ研究は口座入力を待たず、J-Quants capability確認、2021年以降のBulk resume、全履歴verify、Production Dataset生成の順で再開する
- model / feature / hyperparameter / ensemble weightの選択終了前にlocked final holdoutを評価しない

## 2026-08-30 Goal 2 live acceptance完了

- J-Quants V2 Standard capabilityを実取得で確認。`security_master / daily_prices / research_adjusted_ohlcv / trading_calendar / topix_context / financial_summary / bulk_history`は`AVAILABLE`、`shares_outstanding / historical_point_in_time_universe / market_breadth`は`PARTIAL`、exact 12:30 entry labelは`BLOCKED_BY_DATA_CAPABILITY`、前場intradayと需給は今回scope外
- raw最大期間は2017-01-04〜2026-08-28（Calendarは2017-01-01開始）。2021〜2025は各49 file、2026-08-28までは105 fileを追加取得し、2021年stage再実行は49 fileすべてskipしてresumeを確認
- catalogはdaily prices 9,806,149行、financial summary 185,321行、security master 9,878,888行、TOPIX 2,360行、Calendar 3,528行。最終`data verify`は26,030 object、feature snapshot 3、dataset snapshot 1、build 1、status `OK`
- 現行Prime / Standard / Growthかつcommon issueのPIT universeは2022-04-04から利用可能。Production Dataset `3d837e220b4662d2405dafd295b91645813af6e8ffed8cd52a44988b49847a7d`は2022-04-04〜2026-08-27、1,077営業日、4,144銘柄、4,058,130行
- 1 / 5 / 20日absolute labelの`AVAILABLE`は4,004,464 / 3,985,623 / 3,924,593行。売買停止・上場廃止・未成熟は理由別statusで保持し、価格をshiftや推測で補完していない
- Production Buildは`2fc936a7ca9b939d8016ad3c5efea17c53ffd5264d5ece398a8329bf2f2dfe5f`。source cutoffは2026-08-29 23:30 JST、historical revisionは`SINGLE_VINTAGE_AS_REVISED / PARTIAL`のため研究専用で、採用可能性を意味しない
- 実データで市場区分開始境界、provider code優先株衝突、no-trade行、UTC精度、全欠損lineage、一括feature copy、Parquet物理dtype hash、Build全frame同時保持を修正。旧物理dtype hash bundle 4.77GBは削除せず`artifacts/quarantine/production-physical-hash-v1-20260830`へ隔離した
- locked final holdoutにはまだ一度もアクセスしていない。Goal 3の全model / feature / hyperparameter / ensemble weight選択をdevelopment期間だけで完了してから単回評価する
- Goal 2 live acceptance後の全品質gateはRuff / mypy strict（43 source files）/ pytest 195件 / branch coverage 85% / frontend ESLint・TypeScript・Vitest 6件・production build / Microsoft Edge E2E 1件がすべてpass。実データ`data verify`も26,030 object、3 feature snapshot、1 dataset snapshot、1 buildで再度`OK`

## 2026-09-04 Goal 3実データ研究の中断安全化

- 2026-08-30 12:37 JST開始の旧monolithic runは、5日horizonで3 model family、4 task、Optuna、F0〜F12 ablation、diagnosticsを一processへ詰め、12時間超の計算後にhost session終了で停止した。content-addressed advanced reportは未公開、Experiment Registryの成功記録もなく、locked holdoutにはアクセスしていない
- D060の既存方針を実運用化し、`stock-ai research campaign`を追加した。`1 horizon × 1 model family`ごとに独立process、content-addressed report、append-only Experiment Registry、atomic resume manifest、attempt別logを持つ
- 再開時は保存済みartifactをhash / identity / config / commitまで再認証し、成功分をskipする。report公開直後の親停止はartifactから回復し、停止済み`RUNNING`だけを`INTERRUPTED`として再実行する。生存中childは二重起動しない
- ablation後の選択済みfeature subsetを同じbatch境界で再学習できるようにし、V2外・重複featureを拒否してfeature名hashもresume認証へ含めた
- API keyは不要な研究childの環境から除去し、campaign command / manifest / logへも含めない。campaignとlogはGit対象外、実験結果は既存の認証済みartifact境界とExperiment Registryへ保存する
- 親processはBuild markerのidentity / metadata hashを軽量認証してmanifestを先に保存し、各batch childが全Parquet内容を実行直前に完全認証する。model開始前の約20分間にresume状態が存在しない実測上の穴を塞いだ
- 旧runの失敗理由はresource scaleと中断粒度であり、model成績による棄却ではない。development選択は新campaignの完了結果だけから行い、全選択固定までlocked holdoutを開かない

## 2026-09-04 Goal 3 5日foldのメモリ境界修正

- base campaignは1日LightGBM / XGBoost / CatBoostの3 batchを認証済みで完了。5日LightGBM attempt 1はhost process中断でartifact未公開、attempt 2は3 Optuna trialと一部outer foldを完了後、2,826,087行 × 77特徴の`float64`一括copy（1.62 GiB）を確保できず`FAILED`になった
- attempt 2の失敗、完了trial、生成済みfold監査はExperiment Registryへappend済み。content-addressed成功reportは公開されず、5日XGBoost以降も開始していない。locked final holdoutは引き続き未開封
- D071として有限値正規化を列単位の事前確保`float32`行列へ変更し、training-only clip / medianも`float32`、clip / fill / dropをin-place化した。行数・特徴数・target・fold・purge / embargo・tuning範囲は削減していない
- 変更後はAdvanced Research / campaign 44 testをFutureWarningエラー扱いでpass、Ruffとstrict mypy（45 source files）もpass。新code commitを固定した5日 / 20日campaignとして再開し、旧code成功分と新code分のprovenanceを混同しない

## 2026-09-04 Goal 3独立runnerへの引継ぎ

- ユーザー指示により、Codexが30〜60秒周期でPID / CPUを監視する運用を廃止した。以後はユーザーが進捗を尋ねた時だけread-only statusを1回実行する
- 最終の単発process確認ではPython workerが存在せず、campaign `28f0c8df2ed45e5d345271a14ffcb9f7fc288998c4dd710ec10cf6e290b52558`の`h5-lightgbm`だけが保存上`RUNNING`、実効状態`INTERRUPTED`だった。locked holdoutは未開封
- `runner/research-runner.ps1`を追加。campaign / Build / source / dependency provenance、完了artifactを認証し、排他lock、生存worker重複拒否、dead `RUNNING`のatomic `INTERRUPTED`遷移、未完了batchの自動resumeを行う
- `runner/register-research-runner-task.ps1`を追加。hiddenなWindows Task Scheduler jobとしてlogon時と5分周期の再開入口を構成し、Codex終了やWindows再起動後も同一manifestから再開できる
- 研究childへ`JQUANTS_API_KEY`を継承しない。command / task / manifest / runner logにもcredentialを保存しない
- 現行campaignの安全を優先し、最小checkpointはD070の`horizon × model family`単位を維持する。fold / Optuna trialの永続再利用は独立campaign完了後のsource変更境界で追加し、完了済み1日3familyのreportと全失敗監査を保持する
- read-only確認入口: `powershell -NoProfile -File runner/research-runner.ps1 -Action status -Manifest artifacts/campaigns/goal3-base-v3.json`
- Windows PowerShell 5.1のnative引数quote差異と、Task Scheduler権限境界でのGit ownership判定を修正した。repo限定の`safe.directory`をprocess引数へ渡すだけでglobal Git設定は変更していない
- Task Scheduler `StockAI-Goal3-Research`を登録し、初回の独立起動を確認。`h5-lightgbm`はattempt 2の保存状態・実効状態とも`RUNNING`、worker identity一致、task状態`Running`であり、以後は周期監視せずrunnerへ委譲する

## 2026-09-04 Goal 4 / Goal 5 live capability再確認

- 独立runnerの学習process・PIDは照会せず、`stock-ai research morning-capabilities`と`stock-ai ops capabilities`だけをread-only実行した
- Goal 4は`morning_ohlc / intraday_bars / intraday_volume_profile / quotes / order_book / trade_frequency`がすべて`BLOCKED_BY_DATA_CAPABILITY`。前場market-data providerは未設定であり、日足やfixtureから推測しない
- `morning_model_adoption`も、認証済みlive OOS evidenceと承認済みmodel registry entryがないため`BLOCKED_BY_DATA_CAPABILITY`
- Goal 5は`operational_ledger / in_app_notifications`が`AVAILABLE`、remote accessは`LOCALHOST_ONLY`、web pushは`BLOCKED_BY_CONFIGURATION`
- 実運用開始には、Goal 3の固定Championと単回holdout結果、exact 11:30前場provider、local PWAでユーザーが手入力する実保有・account bucket・available / reserved cash・取得単価・税/NISA状態、cost/slippage方針、認証済みJPX Paper calendarが必要。SBI CSVはD068どおり必須ではない
- `order_submission`は`OUT_OF_SCOPE`であり、broker発注・自動売買は実装しない

## 2026-09-04 granular checkpoint隔離実装

- 実行中のmain campaignへ一切のsource変更を見せないため、別Git worktree / branch `goal3-granular-checkpoints`で中断耐性を実装した。mainへは現campaign完了後の安全境界までmergeしない
- recoverable branch commitは`26817dc`（fold / Optuna永続化）と`253644f`（単発CLI cache隔離・改ざん回帰test）
- 新campaign manifest v2は`model family × horizon × seed`単位。各walk-forward foldをDataset / Feature / code / config / parameter / seed / split hash付きParquetとしてatomic publishし、完了済みfoldを再認証してskipする
- Optunaはcheckpoint namespace内SQLiteへ永続化し、study provenanceを認証する。完了済みtrial数と累積時間を元のboundから差し引いてresumeし、残存`RUNNING` trialはsingle-worker lock取得後だけ`FAIL`へ遷移する
- progress manifestはfoldの`RUNNING / INTERRUPTED / FAILED / SUCCEEDED`、attempt、artifactをatomic保存し、worker死後の`RUNNING`を`INTERRUPTED`へ回復する。成功表示とartifact欠損・Parquet / logical frame / metadata改ざんはfail closed
- read-only granular status commandとWindows runnerのseed表示 / checkpoint-root引継ぎを追加。development checkpointはlocked holdoutを含まない
- 隔離branch gate: Ruff pass、strict mypy 46 source pass、pytest 215 pass、branch coverage 85.03% pass。Production researchの同一testを連続2回実行してcache混線がないことも確認した

## 2026-09-05 Goal 3 legacy base campaign完了

- 独立runnerへ委譲したlegacy campaignは正常完了した。`goal3-base-v2.json`の1日LightGBM / XGBoost / CatBoost 3 batchと、`goal3-base-v3.json`の5日・20日LightGBM / XGBoost / CatBoost 6 batch、合計9 batchが認証可能な`SUCCEEDED` report / OOFを持つ
- `goal3-base-v3.json`はcampaign `28f0c8df2ed45e5d345271a14ffcb9f7fc288998c4dd710ec10cf6e290b52558`、Production Build `2fc936a7ca9b939d8016ad3c5efea17c53ffd5264d5ece398a8329bf2f2dfe5f`を認証し、最終20日CatBoostは2026-09-05 15:27 JSTに完了した。全workerは終了済みで、locked holdoutは未開封
- 5日regressionのmean daily Rank ICはLightGBM 0.036813、XGBoost 0.039487、CatBoost 0.019956。5日rankingは-0.002873、-0.001487、0.073736
- 20日regressionのmean daily Rank ICはLightGBM 0.062259、XGBoost 0.064231、CatBoost 0.068081。20日rankingは0.034376、0.020157、0.103577
- これらはseed 17、`run_ablations=false`、`run_diagnostics=false`のdevelopment-only基準実験であり、Champion選定の十分条件ではない。D073〜D075に従い、次は隔離branchを安全にmainへ統合して研究code / configを固定し、3 seed以上のv2 Feature Ablation campaignへ進む

## 2026-09-04 Goal 3選択固定・単回holdout基盤（隔離ブランチ）

- 実行中のlegacy campaignを変更・停止・再起動せず、次の安全なsource境界で使う実装を隔離branchへ追加した。現行campaign終了まではmainへ取り込まない
- v2 ablation / final-candidate campaignを全artifact hashまで再認証し、3 seed以上のfeature vote、全3 model family × 1 / 5 / 20日 × 4 taskの完全matrixを要求する
- purged development OOFだけからhorizon別feature、expected return、rank、downside quantile、large-loss model、全parameter、非負simplex ensemble weight、uncertaintyを選び、content-addressed selectionへ固定する。ensembleは同じmeta-evaluation区間のbest componentを上回った場合だけ採用する
- 選択後だけ使えるlocked holdout evaluatorを追加した。holdout読込前にselectionと唯一のledger path / evaluator commitを一度だけ結び付け、component単位のtargetなしprediction checkpointからresumeし、完了済みcomponentを再fitしない
- completed reportはselection / Build / Dataset / evaluator / feature definition / prediction hashを再認証する。選択・holdout結果はappend-only Experiment Registryへidempotentに保存し、task固有metricを欠損時0へ置換しない
- full JPX OOFのselection再読込は、最初に全bundleのlogical / Parquet / report hashを順次認証し、ensemble整列passでは同じParquet hashを読込前後に確認してregression / rankingの6列だけをpredicate読込する。quantile / large-loss rowの不要な再materializeを避けるが、認証・期間・行は省略しない
- holdoutの独立runnerとTask Scheduler登録入口を追加した。全development選択固定後の明示登録時だけ単回評価を開始し、Windows再起動後も同じledgerをresumeする。研究workerへAPI keyを渡さず、read-only statusは状態を変更しない
- fixtureで中断・resume・成功済みcomponent skip・改ざん・alternate root / commit拒否・selection schema不整合を検証した。実データlocked holdoutは未開封で、Champion候補もまだ固定していない
- 隔離branchの全品質gateはRuff / strict mypy（48 source files）/ Python 229 test / branch coverage 85.33% / frontend ESLint・TypeScript・Vitest 6件・production build / Microsoft Edge E2E 1件がpass。PowerShell 5.1で両holdout runner scriptの構文とTask Scheduler引数表示も検証した

## 2026-09-05 Goal 3 feature固定→candidate実行ブリッジ（隔離ブランチ）

- ablationのtuning-only seed voteを、horizon別exact feature列、F1〜F12 evidence、Build / Dataset / Feature / campaign / report / code / holdout境界とともにcontent-addressed `DevelopmentFeatureSelectionArtifact`へ先に固定する入口を追加した
- 固定artifactだけから1 / 5 / 20日それぞれのLightGBM / XGBoost / CatBoost × 3 seed以上をv2 campaignとしてrun / resumeし、完了後に全model・parameter・ensemble weight・uncertaintyを固定する二段階CLIを追加した
- candidate専用の独立runnerとWindows Task Scheduler登録scriptを追加した。Codex終了・Windows再起動後も同じmanifest、fold checkpoint、永続Optuna studyから自動再開し、API keyをworkerへ渡さず、locked holdoutを開かない。run再開時はPIDだけでなくPython process名と開始時刻を照合し、PID再利用を生存workerと誤認しない
- `research campaign-status` / `candidate-status`はread-onlyで、v2 campaignのhorizon / model / seedに加えactiveまたは最新のtask / foldとcheckpoint件数を返す。status実行前後にcampaign / progress byteが同一であることをfixture testで確認した
- 独立runnerが実際に使う`python -m stock_ai`入口を追加した。日付切替前後でもGoal 5 E2Eが未来時刻fixtureを作らないよう、APIへaware clock注入口を設け、E2EだけJSTの固定時刻を使用する。production既定は現在JSTのまま、naive clockは拒否する
- 品質gateはRuff / strict mypy（48 source files）/ Python 234 test / branch coverage 85.29% / frontend ESLint・TypeScript・Vitest 6件・production build / Microsoft Edge E2E 1件がpass。candidate / research / holdout runner全scriptはWindows PowerShell 5.1 parserを通し、candidateの実statusがread-onlyかつcredential非表示であることと、Task Schedulerの全研究config明示引数をWindows上で実行確認した
- 現行legacy campaignは変更・停止・再起動しておらず、この隔離sourceはその安全な完了境界後までmainへ取り込まない。実データfeature vote、candidate実行、Champion候補固定、locked holdout単回評価はまだ未実行

## 2026-09-05 Goal 3中断再開基盤のmain統合

- legacy base campaignの全9 batch完了と成果物checkpoint `b1d8fef`を安全境界として、`goal3-granular-checkpoints`のfold / Optuna永続checkpoint、feature固定、candidate campaign、development選択固定、単回holdout評価基盤をmainへ統合した
- 次の実データ処理は3 seed以上のv2 Feature Ablation campaignであり、研究code / feature定義 / seed / bounded Optuna条件を固定して独立runnerへ委譲する。全development選択固定までlocked holdoutを開かない
- main統合後gateはRuff、strict mypy（48 source files）、Python 234 test、branch coverage 85.29%、frontend ESLint / TypeScript / Vitest 6件 / production build、Microsoft Edge E2E 1件がpass。Task Scheduler設定表示の端末幅依存改行を固定幅出力へ修正し、該当回帰testを含む全suiteで再確認した

## 2026-09-05 Goal 3 3-seed Feature Ablation開始

- main commit `000812e09be3ceef5491aab073b47778a757c165`、Production Build `2fc936a7ca9b939d8016ad3c5efea17c53ffd5264d5ece398a8329bf2f2dfe5f`、FeatureSet V2、seed 17 / 29 / 43を固定し、v2 campaign `94b974e90eb666c93d18b9fec7985628ef33de3c240e25aefe731a7912a87285`を作成した
- campaignは1 / 5 / 20日 × LightGBM / XGBoost / CatBoost × 3 seedの27 batch。各batchで20 trial / 累積900秒のbounded Optuna、300 estimator、F1〜F12 chronological ablation、OOS diagnosticsを実行し、fold / trial checkpointから再開する
- Windows Task Scheduler `StockAI-Goal3-Ablation`へ登録して開始要求済み。Codexは周期監視せず、ユーザーが進捗を尋ねた時だけ`goal3-ablation-v2.json`のread-only statusを1回確認する。locked holdoutは未開封

## 2026-09-05 Windows worker生存判定の安全修正

- read-only status失敗の原因を、WindowsでPythonのPOSIX式`os.kill(pid, 0)`を使用していたことによる`WinError 87`と特定した
- runnerの生存判定を`ALIVE / DEAD / UNKNOWN`へ変更。PID不存在、非Python PID、開始時刻不一致だけを`DEAD`とし、`WinError 87`、`AccessDenied`、その他の確認失敗は`UNKNOWN`として`INTERRUPTED`へ変更しない
- statusのcheckpoint読取から不適切なPython PID probeを除去し、確認不能でもread-onlyな`UNKNOWN`を返す。自動復旧も`UNKNOWN`が一件でもあればmanifestやworkerを変更せず終了するため、重複起動しない
- Windows PowerShell 5.1でWinError 87、AccessDenied、PID不存在、PID再利用、正常一致、およびresearch runner statusの非変更性をfixture検証した。対象7 testはpass
- 現在のAblation workerは停止・再起動・PID照会していない。`src`、依存lock、研究条件、seed、Ablation設定、成果物、locked holdoutは変更しておらず、研究は独立runnerへ委譲したままとする

## 2026-09-05 Goal 3の1日Challenger軽量screen方針

- D077として、新しい1日複数seed結果を比較する前にscreen条件を固定した。20日を中期の主alpha、5日を短期補助alpha、1日を売買タイミング・短期リスク補助Challengerとして扱う
- 現在実行中の`h1-lightgbm-s17`は停止・再起動せず、そのまま完了させる。稼働中campaign manifest、checkpoint、Experiment Registry、artifactは変更・削除しない
- 1日はF1〜F12 full ablationを先行せず、既存seed 17を再利用してXGBoost / CatBoostのseed 29 / 43を追加する軽量screenへ変更する。LightGBM seed 17は保存するが、追加seedを優先しない
- screenはdevelopment OOFだけで、3-seed / fold方向安定性、5日・20日との非重複性、5日＋20日への増分OOF、realistic costと10〜50 bps stress、turnover / downside / large-loss非悪化を全て要求する。不成立・評価不能なら1日をFinal Candidateから除外する
- 5日・20日は予定どおり3 model family × 3 seedのfull Feature Ablationを行う。locked holdoutは未開封のまま、正常な長時間計算はrunnerへ委譲し、Codexは継続監視しない
- 現行のPython campaign親はmanifest内batchを連続実行し、稼働中processへ次batchだけを安全に差し替えるcontrol pointを持たない。D077のruntime切替は現在のseed 17を壊さないbatch境界でのみ行い、それまではsource / manifestを変更しない
- 現在の`h1-lightgbm-s17`が成功状態をatomic保存した後、旧計画の`h1-lightgbm-s29` workerを起動する直前だけfail closedする一回限りの境界ラッチを、次attempt log pathへdirectoryとして設置した。現worker、親process、manifest、checkpoint、Registryには触れず、次の長時間workerを重複・旧条件で開始しない。pause-after sidecarを読むrunnerも追加し、以後のTask Scheduler再実行は指定batch成功かつ全後続PENDINGなら正常終了で待機する。境界判定の隔離test 3件を含むrunner test 10件はpass。次回ユーザー要求時のread-only statusで安全境界を確認してから、1日screen campaignと5日・20日full campaignへrunner入口を切り替える

## 2026-09-06 Goal 3 multi-seed軽量screen方針

- D078として、screen結果を見る前に全horizonの共通screen・family打切り条件・計算削減順序を固定した。削減目的は重複と見込みの薄い追加探索の除去であり、multiple seeds、walk-forward OOF、cost評価、holdout隔離は削らない
- 5日・20日はLightGBM / XGBoost / CatBoostをseed 17だけで落とさず、同一条件の最低3 seed OOFを先に比較する。paired block-bootstrap 95% CI、seed × foldの80%、全objective、ensemble全split、cost / turnover / downsideの全棄却条件を満たすfamilyだけ`SCREEN_REJECTED`とし、それ以外は`SCREEN_HOLD`または通過としてfull Ablationへ残す。削減数目標は置かない
- 1日はD077どおりChallengerで、比較可能な既存seed 17を再利用して不足seedだけ軽量screenする。既存成果物のcode / split / feature / parameterが一致しない場合は補助evidenceとして保持するが、純粋なseed安定性へ混ぜず、不足する比較可能seedだけを追加する
- screen通過・保留のhorizon × familyだけF1〜F12 full Ablationへ進み、tuning期間と評価OOFを分離し、importance / SHAP単独で採用しない。Final CandidateはAblation後の残存候補だけで全model要素をdevelopment OOFから固定する
- 現在実行中の正常batch、境界ラッチ、artifact、checkpoint、Experiment Registry、locked holdoutは変更していない。安全なbatch境界到達まではruntime planを切り替えず、Codexによる継続監視を行わない

## 2026-09-06 Goal 3後続screen予約

- D079に従う`runner/goal3-phase-runner.ps1`とTask Scheduler登録入口を追加した。別taskは既存research runner lockが解放されるまで計算せず、現在のseed 17 worker・親process・既存taskを停止、再起動、再登録しない
- Windows Task Scheduler `StockAI-Goal3-Phased`を登録済み。確認時は`Ready`、`MultipleInstances=IgnoreNew`で、既存runner lock保有中の起動は計算せず終了する
- 安全境界後は、1日XGBoost / CatBoost × seed 17 / 29 / 43、続いて5日・20日LightGBM / XGBoost / CatBoost × seed 17 / 29 / 43のlightweight screenを自動run / resumeする。各batchはfold / Optuna checkpointと認証済みartifactを再利用する
- screen configはV2全列、3 trial / 900秒、50 estimator、500 / 60 / 60 session、holdout境界120、Ablation / diagnosticsなしで結果前に固定した。full Ablationはscreen判定後の通過・保留候補だけへ限定する
- read-only進捗入口は`powershell -NoProfile -ExecutionPolicy Bypass -File runner/goal3-phase-runner.ps1 -Action status`。今後もユーザーが「進捗」と求めた時だけ1回実行し、継続監視しない
- PowerShell 5.1 parser、Ruff、境界・status・Task登録の隔離testをpass。API key、locked holdout、model source、既存manifest / checkpoint / report / Registryは変更していない

## 2026-09-06 Goal 3 core horizonのFull Ablation直行へ変更

- D080として、1日screenの実測が1 batch数時間であることと、既存seed 17 OOFで5日・20日の全3 familyに役割別の有用性があることを踏まえ、5日・20日のlightweight screenを廃止した。現在実行中の1日screenは停止・再起動せず6 batchを完走する
- 1日はD077の固定gateを変更せず、全screen reportを結び付けたdevelopment-only判定artifactで残留・除外を決める。判定artifactがない間、更新phase runnerは`ONE_DAY_EVALUATION_READY`で停止する
- 判定後の長時間処理は5日Full Ablation → 20日Full Ablationの順とし、各horizonでLightGBM / XGBoost / CatBoost × seed 17 / 29 / 43、20 trial / 900秒、300 estimator、F1〜F12 Ablation、OOS diagnosticsを維持する。1日を残す場合だけ、両core horizon完了後かつ特徴量固定前に1日Full Ablationを実行する
- 稼働中processが保持する旧D079遷移だけを安全境界で止めるため、未作成だった`goal3-screen-5d20d-v1.json` pathへdirectory型fail-closed latchを設置した。現在の1日worker、screen manifest、checkpoint、report、Experiment Registry、model sourceには触れていない
- model-family pruningはFull Ablation後だけ行い、複数seed/fold、全objective、ensemble、realistic cost、turnover、downsideの全棄却条件を満たすfamilyに限定する。削減数目標は置かず、locked holdoutは未開封を維持する


## 2026-10-03 19:10 JST: one explicitly authorized quantile continuation remains blocked

- ranking fold6 was saved at 15:59 JST. All 16 successful units were authenticated, including its 224,458 rows; each saved manifest/Parquet byte hash is unchanged after the continuation. The same `c7f55e2...` namespace was resumed: code/data/config were unchanged, so no new identity or chained import was fabricated. ranking6 remains attempt 1 and was reused without a new fit.
- The old worker exited after the 16:00 quantile1 pre-fit guard: 3.423523 GiB available versus the unchanged 3.5 GiB requirement. Previous progress, failure registry, logs, array receipt and ranking6 bundle were archived before the explicitly permitted single continuation.
- At 19:03 JST, actual stock workers were 0, all four legacy tasks Disabled, preparation RAM 6.033401 GiB (required 5.5), and the same genuine `a68e8327914e265e6594e22e02f24bdbbfee39a5` model/worker source and exact config were verified. One hidden worker was launched; full input authentication completed at 19:06.
- At 19:08:07 JST, quantile1 attempt 2 again failed BEFORE FIT: available 3.416367 GiB, shortfall 0.083633 GiB / 85.64 MiB. No native fit started. At 19:10:44 JST, worker count was 0; exit-time free RAM 6.199165 GiB is not fit-time headroom. No further retry was performed or scheduled.
- Previous ranking input matrices/preprocessor are explicitly deleted, and the fit guard runs gc/reap. The exit receipt has no ranking6-sized mapping. A fresh process that skips all ranking fits reproduced the shortfall, so old ranking native allocations alone cannot explain it. Current preparation, loaded OOF/model inputs and contemporaneous OS RAM are not separately measured at the guard.
- The observed preparation reduction was 2.617035 GiB. Under identical conditions, 6.117035 GiB preparation availability would only mathematically reach the 3.5 GiB boundary; this is not a safe retry threshold or a capacity guarantee. No threshold, dtype/precision, feature, seed, split/evaluation, CPU1 or 300-iteration change was made. No app exit, OS setting, authentication, billing, holdout opening or real order occurred.
- Verification: 16 saved fold bundles authenticated; all 16 byte hashes preserved; original checkpoint unchanged; prior failed registry is an unchanged prefix of the current registry. No code edit or new benchmark/test fit. Evidence: `docs/evidence/memory-recovery-20261003/quantile-once/` and the local one-attempt archive. Continuation is BLOCKED; full-run peak RAM and remaining runtime are unconfirmed.


## 2026-10-04: bounded preprocessing work buffers; production restart pending

The explicitly requested stock continuation found worker0 and 5.758 GiB available at 15:25 JST. Previous fresh-process quantile1 failed before fit with 3.416 GiB against the unchanged 3.5 GiB guard; starting availability alone is not proof of fit-time headroom. All 16 saved units were reauthenticated and archived before source edits, including the original ranking6 Parquet SHA256 `7bb013fb429ea79d3deefdc86691bcf6f72efae120804a05cc93e3e178e3b020`.

Only `_finite_numeric`'s final DataFrame construction changes: the exact same owned float32 C-layout array is exposed as one pandas block per feature. FoldPreprocessor, model constructors, parameters, loss functions, split/evaluation logic and constants are byte-equivalent AST definitions. Existing quantile/median/clip operations avoid a whole-width temporary block. Independent a68 statistics, retained features, inputs/hashes and native CatBoost OOF/report outputs match exactly under both Copy-on-Write modes. The measured quantile work array shrinks from 41 columns to one. Wall-clock tuning durations are independently measured and excluded from semantic equality; no research result is excluded. 89 relevant tests pass; Ruff and strict mypy pass. This is not a measured production RAM saving or native peak guarantee.

A genuine new code commit and namespace are required. The planned 16-unit continuation imports the original 15 native units directly from 94aab78 and ranking6 directly from a68/c7f55e2's native artifact, with separate authenticated equivalence proofs. It does not import the already-imported c7 copies or relax chained-import checks. Existing source namespaces, failure history and Optuna duration/budget remain untouched. CPU1, iterations300, data/features/dtype/seed/config, guard3.5 and locked holdout remain unchanged. The next milestone must verify actual preparation/guard/fit state and follow completion or safe stop. Evidence: `docs/evidence/memory-recovery-20261004/`.


## 2026-10-04 15:55 JST: actual guard stop and bounded Arrow allocator diagnosis

The ae1a531 block-layout continuation started at 15:50 with preparation RAM 5.738335 GiB. Input authentication completed at 15:53. quantile1 stopped BEFORE FIT at 15:54:58: available 3.215996 GiB against unchanged required 3.5 GiB (290.82 MiB short), native fits0, succeeded16, failed1. Worker0 was confirmed at 15:59. The verified smaller quantile work array did not establish adequate production headroom. Preserve this failed attempt and all previous results.

Installed Arrow23.0.1 uses mimalloc. Its release_unused API is best-effort, potentially expensive, and documented for benchmarking/debugging. Add exactly one pressure-triggered resource diagnostic per owned recovery workspace: after gc/reap, only if actual headroom is insufficient, request unused default-pool memory release; log backend/live bytes and physical availability before/after; then apply the UNCHANGED 3.5 GiB guard to the actual after-value. Live buffers stay owned. Cleanup error/ineffectiveness remains a guard stop. Later pressure cannot cause repeated cleanup or restart. No working-set cap, other-process action or OS setting is used.

93 tests pass, including independent old statistics/native OOF parity, sufficient-headroom no-op, at-most-one cleanup, exception/low-headroom refusal, and real live Arrow buffer bit/dtype preservation. Ruff and strict mypy pass. Model/data/features/dtype/seed/CPU1/iterations300/split/evaluation/holdout stay unchanged. Bind genuine new code provenance and directly import native original15 and a68 ranking6; never chain imported folds. Actual recovered RAM and fit entry remain unverified until the next observation. API: https://arrow.apache.org/docs/23.0/python/generated/pyarrow.MemoryPool.html#pyarrow.MemoryPool.release_unused


## 2026-10-04 16:13 JST: second guard stop; final bounded OOF buffer improvement

The e410185 allocator attempt started at 16:08 with preparation RAM 5.880241 GiB. Full input authentication completed at 16:11. quantile1 again stopped BEFORE FIT at 16:13:02: available 3.288280 GiB before and 3.343269 GiB after one unused-pool release, against unchanged required 3.5 GiB. The gain was 56.31 MiB; the remaining shortfall was 160.49 MiB. Live Arrow bytes stayed 191165696. Native fits0, succeeded16, failed1, worker0 confirmed at 16:13:32. Exit-time RAM 6.077 GiB is not fit-time headroom.

The research caller already owns OOF parts and ignores generate_oof_predictions' full return. Skip only that unused complete concat/sort in an explicit private collection mode. Preserve default API, per-part predictions, duplicate identity and nonfinite validation, and the final research/report concat. No model constructor, parameter, feature, dtype, seed, split, evaluation or holdout changes. Four new tests verify exact part/hash equality and rejection paths; all 97 relevant tests, Ruff and strict mypy pass. Actual production RAM benefit remains unverified. Use genuine code provenance and direct native imports of original15 plus a68 ranking6. This is the final bounded continuation for the present authorization: if the same 3.5 GiB guard remains insufficient, preserve the failed history and stop without another fix/restart loop.


## 2026-10-04 16:32 JST: final bounded continuation safely stopped; no native quantile fit

The 8d82fa6 OOF-buffer continuation started once at 16:27:56 JST, with preparation RAM 5.912430 GiB, stock workers0 and all four legacy tasks Disabled. All16 units were imported directly from native original15 plus a68 ranking6 into c424b0f8; each authenticated reload matched, and no chained import or source-pin rewrite was used. Full data authentication completed at 16:30:32. quantile1 reached the guard at 16:32:06: actual available 3.373367 GiB before and 3.433807 GiB after one unused-pool release, below the unchanged 3.5 GiB requirement by 67.78 MiB. Live Arrow bytes stayed 191165696. The worker recorded BLOCKED_BEFORE_FIT at 16:32:12 and had exited at the 16:32:20 observation. Native fits0, succeeded16, failed1, running0. Exit-time free RAM 6.140 GiB is not fit-time capacity.

The final one-time process snapshot confirms workers0 and legacy tasks Disabled. After exit, every old saved fold's manifest/Parquet byte hash is unchanged; all16 new saved folds were reauthenticated and their row counts/logical hashes match the original receipt. ranking6 remains the original 224458-row native a68 result. Original source namespace manifest/progress hashes are unchanged. All prior failure registry bytes are an unchanged prefix; five entries are retained. Model/worker/lock/config source remains exactly the genuine 8d82fa6 pin. Data,41 features,dtype,seed29,CPU1,300 iterations,split/evaluation,holdout and guard3.5 are unchanged. The 97 relevant tests,Ruff and strict mypy passed before launch.

The present authorization ends at this safe stop: no further fix/restart loop, automatic restart or learner schedule was created. The observed fit-time headroom increased relative to the preceding attempt, but differing OS availability means this is not a controlled causal RAM benchmark or a native peak guarantee. Quantile remains incomplete and no new native fit started today. Overall remaining calculation time, full-run peak memory and seed43/20-day completion time remain unconfirmed; do not invent completion percentages or days. Evidence: docs/evidence/memory-recovery-20261004/oof-buffer/final/ and the local runtime audit.


## 2026-10-04 18:26 JST: authorized normal Edge close; first native quantile fold completed

The user explicitly approved normal Edge closure and one stock continuation. UI Automation confirmed readonly email fields, empty editable password fields and no existing dialog; no input value was recorded. A normal window-close request at 18:16:54 closed all visible Edge windows without confirmation acceptance or force kill. Six background processes remained and were not killed. Actual available physical RAM rose from5.848602 to7.284618 GiB at the18:16:58 observation; this contemporaneous change is not an isolated causal memory benchmark. No other app,OS setting,history or data was changed.

All16 original results were reauthenticated before launch, each old byte hash unchanged, with source namespace manifest/progress unchanged. Resume the exact existing c424b0f8 checkpoint and genuine 8d82fa6 model pin, preserving the previous failed quantile1 attempt. No new namespace/import or scientific source change was needed. The preparation-only launch gate is7.0 GiB, a practical extra margin based on the preceding observed2.478622 GiB preparation-to-guard reduction; it is not a validated capacity requirement. The native fit guard remains3.5 GiB. Stock workers0 and all four old tasks Disabled were confirmed before one launch at18:20:40, with7.463245 GiB available. CPU1,300 iterations,41 features,data,dtype,seed29,split/evaluation and holdout remain unchanged. No recurring task was enabled or automatic restart created.

Full input authentication completed18:23:08. The first actual fit guard at18:24:35 passed with5.005829 GiB available, after the one permitted pressure-triggered unused Arrow release (before3.498837 GiB,live Arrow bytes unchanged191165696). Quantile fold1 completed and persisted at18:26:23: training2074895 rows,validation/OOF202496 rows,attempt2,SUCCEEDED,no import lineage. Its Parquet SHA256 ad9bcca5104742560e170c34a2ded062259ecaddff56c9a9e309b776366dbee8 matches the native manifest; logical frame hash6bc00d61927a736f80654fca108e34751ea2c002663c1750829a6eb43b0fca72. This proves a newly completed native fit; total saved units16 to17. The once-only2-second CPU sample at18:26:38 was after first-fold completion and showed the continued worker alive,CatBoost native module loaded,2.25 CPU seconds,WS3.586449 GiB,peak WS5.273209 GiB,private commit2.193943 GiB,system available4.125542 GiB. Commit is not physical RAM. Do not infer live fit solely from stale worker phase/training_started fields.

This is an active-run milestone, not full completion. Subsequent fold guards and checkpoint completion/safe stop remain to be observed at low frequency. No restart loop is authorized. The full native peak and overall quantile/large-loss/diagnostic/seed43/20-day ETA remain unconfirmed. The97 relevant tests,Ruff and strict mypy passed for the unchanged scientific source before the prior attempt; no new model benchmark or code change was performed here. Evidence: docs/evidence/memory-recovery-20261004/edge-resume/ and the local runtime audit.


## 2026-10-04 18:44 JST: all six native quantile folds saved

The same authorized single worker38000 completed quantile folds1-6; the last saved update is 2026-10-04T18:44:39.847454+09:00. Native quantile OOF totals 1,327,530.0 rows. Each of the six Parquet byte hashes matches its native manifest; no import lineage is present, and seed29/config/41-feature identities match. Total succeeded units22,failed0. The existing plan automatically proceeded into large_loss fold1; no new model configuration, extra worker or observer was created. All six quantile fit guards passed the unchanged3.5 GiB threshold; the sixth guard had4.505730 GiB available. The same genuine8d82fa6 model/worker/lock source remains unchanged. This is quantile phase completion, not full seed/campaign completion. Large-loss and fixed diagnostics/report verification remain. Continue the existing low-frequency observer until current execution completion/safe stop, with no automatic retry or additional task enablement. Evidence: docs/evidence/memory-recovery-20261004/edge-resume/quantile-phase/.

## 2026-10-15 — 日次版の監査・記録・本人専用閲覧の実装

5日9/9・20日9/9、計18候補の研究学習が完了。全report/OOFを再認証し、成功checkpoint503unit、保存ラベルの13分割境界を照合した。再開proofは当時のraw sourceを使用し、科学source pin・成功成果物・失敗履歴を変更していない。Drive v04は21単体試験と全calibrationを再実行し、配布結果と一致。SB20/SB60の誤較正も再現したため採用条件には使わない。

Prediction v2（5日/20日・1日はnull）、日次0/0/1 decision policy、原予測/7項目手動調査/本人レビューの分離保存、preview-confirm import、JSON/CSV/Markdown export、backup/integrity対応、daily-only workflow順序、本人専用Sitesへの最小結果同期を実装。画面は学習完了と採用準備を区別する。未検証のadoptは明示的にブロックする。

日次live inference・定期sync・状態付きNAV・企業行動会計の統合は未完。26項目全部の合格、最終モデル確定、holdout評価、現在の推奨株数、実用採用は未達。single-vintage/実用費用/個人設定の不足も残る。元学習データの時点は8月であり現在予測とは表示しない。工程と終了条件は docs/DAILY_RUNBOOK.md、実測証拠と26試験票の対応は docs/evidence/daily-readiness-20261015。

実注文は送信していない。最終検証結果は同証拠ディレクトリの verification.md に記録する。

## 2026-10-15 — アプリ内の口座・保有入力

ユーザーの「現在は何もない」「口座区分とか現在の所有株はアプリ内で入力」へ対応。private/portfolioで保有なし、口座区分、銘柄・株数・取得単価、任意の資金・最大下落率を入力・確認・保存・再読込できる。本人専用D1へ履歴保存、古い画面の更新は409拒否。空欄金額はnull。ローカル検証で保有なし→再表示、NISA/1株/小数取得単価、2画面競合と再読込を確認。本番に検証用口座・保有を登録していない。個別推奨への接続は未完。

Python最終全体試験408 PASS、coverage85.26%（基準85%維持）。private/はschema/DB migrationテスト12 PASS、TypeScript/eslint/build PASS。学習18/18の完了と、未完の最終評価・holdout・日次推論は区別する。

本番反映も完了。source847864637a69cfb9e970550a45cca71dc8495bc5、deployment appgdep_6acfbd154be08191a17329c2767a639b、本人のみのprivateを再確認。通常サインイン後、本人申告の「保有なし」を02:36:51 JSTに保存。口座0件・資金/リスクは未入力。ローカルpreview停止後も本番再表示を確認。匿名の口座API/同期APIはいずれも401。検証用銘柄や金額は本番へ送っていない。

## 2026-10-15 — 日次NAVの会計評価器

前回Goal turnは口座入力の本番反映・読戻しでprogress。今回はDrive v01 V18〜V23に対応する研究用日次NAVを実装。口座別現金/予約・保有・未収金を引き継ぎ、時刻・単元・呼値・共有capacity・資金・決済待ちを満たす分だけ仮想約定する。費用の二重控除、終値を見た同時刻約定、価格欠損による保有消去を拒否。分割/端数、配当権利と受取、確認済み現金交付を処理し、同じ初期状態のHOLDとの差を出す。CLI research evaluate-navで明示入力からimmutable receiptを保存できる。

新規45 tests、既存cost/tax/simulator/domain/CLI/daily系を含む105 PASS。新規module coverage92%、ruff全体PASS、mypy54 modules PASS。証拠はdocs/evidence/daily-nav-20261015。最初の制限環境のPermissionErrorは記録し、workspace内basetempと許可された実行で再検証した。実市場adapter、Decision Engineの連続実行、個人税シナリオ、全候補比較、holdoutはまだ未完。Goalはactiveのまま。実注文なし。

## 2026-10-15 — 開発評価指標の手計算検証と認証OOFへの接続

日次NAV source checkpoint55e2878の全体回帰は453 PASS、coverage85.48%。追加の順位・確率・分位点の手計算試験40 PASS、初期moduleはbranch込み100%。同点の行順不変、負return・K超過、等日付/銘柄数加重の差、確率端点・base rate・過信、pinball/coverage・交差を確認した。旧学習reportは保持し、新版を別の診断として固定。CLIおよび27候補fixtureの認証→全task採点→receipt保存を含む53 PASS。

research audit-candidates --score-developmentから新しい診断を実行できる。元report/OOF/source・feature・key/target・holdout境界の認証が先。単一alphaは交差確認不可、元の確率/予測を修復しない。計算規則はdocs/DAILY_EVALUATION_METRICS.md。実18候補の新版診断、全baseline/NAV比較、最終selection/holdout、日次推論・個人保有接続は引き続き未完。実注文なし。

## 2026-10-15 — JPX休日境界と全特徴量の因果性検証

公式JPX休業日一覧に基づく2026-01-12の休日fixtureを追加。01-09 featureから01-13入口、1日01-14・5日01-20・20日02-10の出口を独立した日付と照合した。入口価格欠損時は日付をずらさずSUSPENDED_NO_ENTRY_PRICEとtarget欠損を保持する。productionの未来価格変更試験はV0/V1/V2全列へ拡張し、過去値がexact一致。関連3試験PASS。新評価指標の統合は53 PASS、新moduleのbranch込みcoverage100%、Ruff/mypy55modules PASS。実18候補の診断を継続中。証拠: docs/evidence/daily-metrics-20261015。

## 2026-10-15 — 実18候補の新版診断と全体回帰の完了

実18候補のreport/OOF/source・feature・key/target・holdout境界を認証し、daily-development-metrics-v1を全4taskへ適用。全18 PASS、非有限値の除外0、5日各task1,327,530行・20日1,044,317行。元report metricsも同じreceiptに保持し、指標source hashとlibrary版、日別IC・確率binを保存した。receipt ID06aa2b94c2dcd90ef0faa850c1924c93ea7080f4a0a37f998750927e273cf65c、検証証拠docs/evidence/daily-metrics-20261015。再学習・最終selection・holdout評価・採用は行っていない。

全Python回帰はsource checkpoint ac0fa41で497 PASS、coverage85.68%、Ruff全体とmypy55modules PASS。元の5監査receiptはbyte hash不変。既存baseline report47afb247…はholdout境界2026-02-24で今回の2026-03-04と異なるため、そのsummaryを直接比較しない。次は同一開発期間のbaseline・日次5/20日adapter・実価格/企業行動/費用を通したNAV比較。現在の保有入力画面は公開済みで、個別推奨への接続は未完。実注文なし。


## 2026-10-15 — 日次5/20日OOFと保有比較の接続検証

日次専用adapterを追加。原campaign/report/OOF/固定特徴量とdataset全体のlogical identityを認証後、開発期間に一致するlabel時点列だけを取得する。受信時刻の厳密な過去条件とlabel終了日の翌日条件で20日残差RMSEを計算し、5/20日Prediction v2・1日null・risk20日へ接続。horizon不足/履歴不足は理由付きblock、保有予測の欠落は比較全体を停止。単日のDecision Engineへ新候補＋全保有を渡し、元portfolioは変更しない。

明示LightGBM seed17ペアを2025-11-06 11:30 JSTで検証。3,717銘柄の予測、horizon不足30銘柄、較正962,235行/257日。最良モデル選択ではない。source checkpoint2cd7167、実データreceipt99bb487396e9ddecb4ff14ee907f8cfae94235d954aa290876bb0bc558d081d6。証拠はdocs/evidence/daily-oof-20261015。全sourceのhash認証とholdout成果の評価を区別し、後者は行っていない。

新規34試験、関連合計97 PASS、新module coverage94%。全体531 PASS、coverage85.86%。Ruff全体/mypy56modules PASS。元dataset・学習成果の変更なし。個別module指定のcoverage起動2回はNumPy初期化失敗、標準のsource-directory指定で回復し失敗log保持。状態を引き継ぐ戦略→日次NAV、実市場/企業行動adapter、全baseline比較、selection/holdout/最新推論、個人設定との接続は未完。Goalはactive。実注文なし。


## 2026-10-15 — Decision Engineから日次会計への連続接続

判断時点の保有・現金・未収金を受けるstateful NAV callbackと、固定5/20日予測から毎日Decision Engineを実行するresearch evaluate-daily-strategyを追加。実際の仮想約定/未約定、企業行動、支払だけを翌日の状態へ反映する。全保有を候補へ追加し、必要情報の欠落/古い単位の価格/探索上限は停止理由と保有持越しを記録する。停止を含む比較はdecisions_complete=false。未収金はNAVには含め、支払までは買付余力に使わない。

税前の研究用口座metadataを明示し、本人の口座区分・NISA・税シナリオとは分離。日次提案のis_research_onlyが汎用engineの既定falseになっていた点を、独立したDailyDecisionAuditと必須trueで是正。原予測・市場・現在portfolio・candidate根拠のhashを提案へ束ねた。固定注文の既存APIと同じ会計経路を使い、生成注文の再実行で全結果が一致する。

追加29試験、関連112 PASS、新module coverage99%。source checkpoint9d39864で全体560 PASS、coverage86.10%、Ruff全体/mypy57modules PASS。手計算のpartial-fill、資金・取得単価・費用、決済待ち、停止株、配当・分割、未来価格変更、欠損時の保有維持を確認。証拠docs/evidence/daily-strategy-20261015。市場成績はまだ計算しておらず、保存した戦略receiptは合成テスト専用。

実sourceの最新raw/normalized各5種、計10objectのschema/byte hashをread-only検査。raw株価のUL/LLはnormalized schemaに未接続、raw財務配当列だけでは権利/支払イベントにならない。公式V2仕様でULは終値ではなく高値到達、特別気配・実際の利用可能時刻・訂正前データは非提供と確認。元学習dataset/履歴は変更なし。次はrawの認証と執行用projection、企業行動/約定能力、全baseline比較。個人税、selection/holdout/最新予測も未完。Goalはactive、実注文なし。


## 2026-10-15 — 保存日足の認証と執行用projectionの前段

research project-daily-marketを追加。固定feature selectionとholdout境界を確認後、指定開発期間のraw/normalizedとcatalog/manifest/byte hash/行metadata/値をread-onlyで照合する。無約定行、UL/LL欠損、空partitionを保持。末尾0以外のprovider codeは普通株へ短縮結合せず、元codeとsymbol nullで残す。元dataset/保存sourceは変更しない。

実4日間2025-11-04〜11-07、8object・17,669行の認証に成功。取引あり16,899、無約定770、特殊code20、調整要確認1行。初回は特殊codeを拒否し、保存方法を修正して再検証した。追加30試験、関連115 PASS、新module coverage94%、Ruff全体/mypy58modules PASS。全体回帰はsource checkpoint da999e1で590 PASS、coverage86.28%。証拠docs/evidence/daily-market-20261015へ記録した。

投資対象ユニバース/営業日完全性、元dataset source-frame一致、企業行動/約定能力/実用費用は未確認。実市場NAV、全baseline比較、個人税、selection/holdout/最新推論も未完。Goal active、実注文なし。


## 2026-10-15 — 同一開発foldの回帰baseline比較実装

research compare-daily-baselinesを追加。固定datasetと全18候補のidentityを認証し、元のpurge/embargo/初回評価開始と同じfoldを再現する。評価key・target・as_of・foldは完全一致必須。ゼロ予測、20日momentum、V0 Ridge(alpha5)、固定候補平均の指標とOOFを保存。CLIは開始・成功・失敗を別receiptに残す。

Ridgeは正確なtrain内中央値とblock単位の中心化共分散を使い、通常実装と一致する線形方程式を解く。新規23試験PASS、module coverage89%、Ruff全体/mypy59modules PASS。初期のfixture Path型、dataset認証に必要なsymbol列、DuckDB/Pandas時刻単位の差を修正し、失敗logも保持。実18候補とbaselineを5日1,327,530行/6fold、20日1,044,317行/5foldで比較し完了。元の18候補の順位auditと全一致。source checkpoint304d3e8で全体613 PASS、coverage86.35%。証拠docs/evidence/daily-baselines-20261015。

予測指標の比較でありcash/HOLDのNAV成績ではない。全baselineの確率/分位点、cross-fitted learned ensemble、企業行動/約定能力/費用/個人税、最終selection/holdout/最新推論は未完。Goal active、実注文なし。


## 2026-10-15 — 同一foldの確率・下側分位点baseline

compare-daily-baselines v2で、全18候補の大幅下落確率・分位点と、train内発生率・経験分位点・V0 Logistic(C1)を同じ行で比較する。候補の閾値/alphaとtask間as_ofも照合。全学習行を維持し、補完/標準化後の一時ファイルをblock読みで最適化する。単一classは明示constant、未収束は拒否。元学習成果とv1 receiptは保持。

関連36試験PASS（追加13）、module coverage91.08%、Ruff全体/mypy59 modules PASS。独立sklearn pipelineとの数値一致、閾値の等号、単一class、未収束拒否、未来の正解変更に対する過去fit/予測不変を確認。初回はテスト側の固定閾値と分位点の完全浮動小数一致で2失敗、修正してログ保持。実18候補とbaselineを5日1,327,530行/6fold・20日1,044,317行/5foldで比較し完了。元候補のリスク指標18件と全一致。source a0be507で全体626 PASS、coverage86.42%。証拠docs/evidence/daily-risk-baselines-20261015。

残りのrule/Elastic Net、cross-fitted ensemble、企業行動/約定能力/費用/個人税を通した状態付きNAV、最終selection/holdout、最新予測、本人入力の比較接続は継続。Goal active、実注文なし。


## 2026-10-15 — 最終評価アクセスのローカルmetadata調査

reports/selections/campaigns/experimentsの73 JSON/JSONL、161レコードをread-onlyで調査。アクセス宣言148件はboolean false147件と文字列false1件、trueなし。artifacts全体でholdout/ledger名JSONなし。旧baseline47afb247のreport identityを再計算し、宣言commit86c958d0fd60c91c2941420a58a0dcfe7bcea764のproduction/validation関数が2026-02-24以降とlabel跨ぎを評価から除外することを確認した。現最終評価境界2026-03-04より前である。

ファイル一覧/byte SHA、宣言の位置・型、固定関数本文/位置/SHAをdocs/evidence/holdout-access-inventory-20261015へ保存。元の記録・データ・学習成果は変更なし。未記録/外部アクセスを除外できる証跡ではなく、旧reportも署名実行証跡や行別key receiptを持たないため、履歴完全性はNOT_PROVEN。この調査をholdout開封/採用gateのpassに置き換えない。新しい成績の採点や実注文なし。Goal active。


## 2026-10-15 — 複数時点のアンサンブル・確率調整の開発評価

research crossfit-daily-ensembleを追加。元18候補と固定datasetを認証し、3つの後続評価期間ごとに重み学習・調整・評価を分離する。両境界にhorizon以上の観測日embargoとlabel終点/受取時刻のpurgeを適用。未受領の同日他銘柄targetも順位正解に混ぜない。回帰/順位/確率の非負・合計1重み、順位からリターンへの較正、isotonic確率較正、固定平均分位点の残差補正を保存する。

追加24試験PASS、module coverage93.23%、Ruff全体/mypy60modules PASS。独立数値解との一致、過去モデル/予測の未来変更不変、入力/時刻/キー拒否、全18候補の認証とCLI成功/失敗記録を確認。初回は合成fixtureの20日調整期間不足で19PASS/1FAIL。必要日数を弱めずfixtureを延長し、誤ったcoverage指定も修正して再試験した。失敗ログも保持。source afa9a5fで全体650試験PASS、coverage86.58%。実18候補の比較も完了し、5日662,791行/177日・20日523,258行/140日を各3時点で評価した。18回の重み最適化は全収束。元baselineの同じ評価行と完全一致し、単純平均との差は最大2.23e-16。保存した全重み/較正から予測を再現し、原成果は保持。証拠docs/evidence/daily-ensemble-20261015。

順位ICは単純平均0.0682/0.0992から学習重み0.0855/0.1064へ改善（5日/20日）。ただし回帰MSE改善は小さく、5日の生リターン平均/学習重みはゼロ予測より悪い。確率較正はECEを下げても両horizonでBrier/log lossを悪化させ、分位点補正もpinballを悪化させた。期間別の悪化も記録し、較正成功や採用の判定はしない。

個別候補/単純平均/学習ensembleを同じ後半期間で比較し、順位スコアとリターン単位を区別する。成績改善や較正成功は前提にしない。残りのbaseline・実市場状態付きNAV・個人設定/費用/税・最終selection/holdout・最新推論は継続。Goal active、実注文なし。詳細docs/DAILY_ENSEMBLE.md。


## 2026-10-15 — アプリ入力の本人専用PC取込

口座/保有/資金/最大下落率の手入力を、本人専用SiteからPCへ取り込む経路を追加。保存版とexportのSHA256、厳密schema、owner固定、版/時刻rollback拒否を行い、SQLiteへ確定してから同じ版の受領記録を返す。アプリはPC取込待ち/取込済みを保存版ごとに表示する。再取得は冪等で受領時刻を保持し、旧版ACKで新しい入力を取込済みにしない。移行は追加tableのみで、元予測/入力を保持する。

関連Python56試験、CLI認証情報非表示追加後の取込38試験、Node12試験、Ruff全体/mypy61modules、private lint/TypeScript/build PASS。source checkpoint c0f6a81/5be26b4。本人専用公開成功、実際の保有なし/口座0/資金・リスクnullを改変せず取込・冪等再取得・backup検証、画面のPC取込済みまで確認。認証不足/外部Originの4種類はHTTP401。明示再開後に前回Pythonプロセス0件を確認して全回帰を再実行し、688 PASS、coverage86.74%を確認。旧実行はhandle消失/利用上限によるreview不能で19%までの未完ログとして保持する。公開・実入力取込・認証拒否・全体試験の証拠はdocs/evidence/manual-portfolio-import-20261015に保存。入力取込と約定台帳/税/費用/最新予測を使った個人比較は別段階であり、後者は未完了。手順はdocs/MANUAL_PORTFOLIO_IMPORT.md。Goal active、実注文なし。


## 2026-10-15 — Elastic Net・固定ルールの同一期間比較

compare-daily-baselines v3へ固定Elastic Netとmomentum+revision/4特徴等重みの順位スコアを追加。全候補の認証と同一fold/評価keyを維持する。ルールの同日母集団は未来label結合前のsource特徴全行で決め、正解未受領peerも含める。順位スコアをreturn/確率とせず順位指標だけを保存。Elastic Netはtrain統計と全行Gramでfitし、KKT残差1e-9以下・有限目的値を要求、未収束は失敗を残す。

関連61試験PASS（追加25）、新module coverage97.10%、Ruff全体/mypy62 modules PASS。独立sklearnとの予測/目的値一致、batch変更、欠損/定数/同順位、未来target不変、未受領peerの参加、時点不整合拒否を確認。試作段階も数値20/接続3試験PASS。実18候補比較と全体回帰はsource checkpoint後に実施。条件は実スコア計算前に固定したが、以前の候補成績を見た後の探索診断であり採否用の事前登録とはみなさない。費用/税/実市場NAV、最終selection/holdout、最新推論と個人比較は未完。Goal active、実注文なし。


実行中の点検で共有順位audit内にリターン単位MSEが残る出力不整合を発見。入れ子mean_squared_errorの不在を検証する試験で1 FAILを再現し、ルール出力からだけ除去して25 PASS、Ruff/mypy PASS。元候補・回帰baselineの指標は変更しない。実比較attempt1と全回帰attempt1は新規スコア計算前に停止し、logと中断理由を保存。条件や予測値を調整したものではない。修正checkpointから再実行する。


修正checkpoint7fccbe1で全713試験PASS、coverage86.81%（基準85%）を確認。1482.05秒、2031 warnings。full-regression.jsonへsource・実行日時・log/coverage SHAを保存した。追加モデルの実データ比較は別途継続中であり、この全回帰成功を実評価・採用の完了とみなさない。runbookのPC取込未実装という古い記述と、試験票のDecision Engine未接続という古い記述を、既に検証済みの実装範囲に合わせた。


## 2026-10-15 — 学習時の元データ5種類との一致と新規取得の接続確認

固定feature selection→production buildのcontent identity→dataset metadata→全5種類のsource frameを読み取り専用で照合し、全識別値の一致を確認した。normalized 13,015 objectのbyte hashを処理前後で検証。PIT選択後は株価/銘柄一覧が各9,801,708行、財務185,307行、営業日3,527行、TOPIX2,359行。512MBのDuckDB処理と型をそろえた行hashで、元の全件計算と同じ識別値を再現した。証拠docs/evidence/daily-source-identity-20261015。

これは入力の同一性監査。元データの全暦日にはholdout日付も含むが、予測/target/成績を計算していない。訂正前vintage、全期間raw/normalized行ペア、PITユニバース/営業日完全性、企業行動/執行能力の保証には置き換えず、projectionはevaluation_ready=falseを維持する。catalog・元データ・dataset・学習成果は不変。

同日の公式V2への読み取り確認では、株価Bulk一覧とFree対応の銘柄一覧がいずれもHTTP403。配当APIは未要求で、原因や本人の契約プランは未確定。認証値・応答本文は記録せず、契約/資格情報/production dataも変更していない。契約プランとキー有効状態を本人へ確認依頼済み。最新取得・最新推論は接続復旧が必要だが、保存データの追加比較・残実装は継続する。証拠docs/evidence/live-data-access-20261015。Goal active、実注文なし。


## 2026-10-15 — 追加Elastic Net・固定ルールの実比較と全行再現完了

source7fccbe1で5日1,327,530行/354日/6fold、20日1,044,317行/279日/5foldの比較を08:28〜09:07 JSTに正常完了。receipt acc6ee1190f496ebce794281bb7927269b6b4e77ec46da027c9138dd0a51c5de。全18候補の元指標・key/target/foldはv2と完全一致、既存baseline予測の差も0。全11foldの保存係数と別実装scipy順位計算から全採点行を再現し、いずれも差0。KKT残差1e-9以下を確認した。正解未受領等のpeerを5日14,027行/20日13,385行含め、未来labelによる順位母集団選択を行っていない。証拠docs/evidence/daily-simple-baselines-20261015。

Elastic Netの平均Rank ICは5日0.010408/20日0.017013で、全18候補が上回った。ただしMSEで上回るのは5日8/9、20日5/9。2種類の固定ルールは両期間で平均ICが負だが、5日の等重みルールのNDCG@20は0.381223で個別候補最大0.381083より高い。指標ごとの混在結果と全fold/全候補を保持し、勝者選択や有意差・実用収益の断定は行わない。別のensemble診断は評価日数が異なる。

全713試験PASS/coverage86.81%と実比較の正常終了は別証拠として保存。初回中断・出力単位の修正履歴も保持した。元成果を変更せず、holdout採点・実注文なし。実市場の企業行動/約定能力/費用/個人税を通す状態付きNAV、本人入力の比較接続、最終selection/holdout、最新refit/推論/同期は残る。最新データAPI403の解消も必要。Goal active。


## 2026-10-15 — アプリ入力と既存台帳の個人研究比較

ops compare-personalとローカルAPIを追加。本人の最新手入力版・全口座/全保有・現金/取得単価・明示税状態・未反映約定・現在日の11:30原予測を照合し、設定/市場が揃う場合に既存の費用/税/HOLD比較へ接続する。全口座共通の目標株式時価上限とNISA残余購入枠を適用。単元未満保有を保持し、売却で同日NISA枠を復元しない。原入力・約定・現金・税・予測台帳を変更せず、途中変更は拒否する。研究専用/採用不可を維持し、最大下落率を保証へ変換しない。

関連129試験、最終個人比較34試験、Ruff全体/mypy63 modules PASS。合成試験の各1,000円費用・2,000円推定税・残現金196,000円・HOLD比26,000円を独立手計算と照合。本人の実入力は保有なし・口座0・資金/リスクnullを保持し、提案なし/不足理由を返すことと全DB記録hash不変を確認。証拠docs/evidence/personal-comparison-20261015。全体回帰はこのsource checkpoint後に実行する。

初回台帳の明示照合/確定、クラウドの補足設定と比較表示、実市場NAV・企業行動/約定能力/費用/税/リスク実証、最終selection/holdout・採用、最新推論/同期は残る。API403も未解消。Goal active、実注文なし。


## 2026-10-15 — 個人比較の全回帰と開発期間の市場照合完了

source 7eea42a44642ad6ddf520c5359edfb7295c000f8で全747試験PASS、coverage86.9514%（基準85%）。09:44 JSTに正常終了した。原入力不変・口座別照合・費用/税/HOLD計算を含むコードの回帰成功であり、実市場NAV・本人向け推奨や採用の完了とは区別する。証拠docs/evidence/personal-comparison-20261015/full-regression.json。

開発評価期間2024-07-31〜2026-03-03の日足を42区間で認証。386営業日、raw/normalized 772 object、1,702,477行。全営業日の欠落・予定外日付・四本値の大小関係違反は0。取引あり1,629,008行、無約定73,469行、特殊code1,675行、調整要確認394行を保持。全receiptのcontent identity/byte hash、区間集計を独立に再確認した。元データは不変、最終評価の価格行・成績は未読/未採点。証拠docs/evidence/daily-market-development-20261015。

独立集計scriptの初回はWindows既定cp932による日本語path誤読でidentity照合が失敗。元receiptの不変と正しいidentityを確認し、UTF-8を明示して再確認した。元audit・学習・全回帰は再実行せず、失敗scriptも保存した。次は当時の銘柄一覧とのキー照合。個別銘柄網羅、訂正前vintage、企業行動/約定能力/決済/費用/税、実市場NAV、初回台帳・クラウド補足設定/比較表示、最終selection/holdout・最新予測は残る。API403未解消。Goal active、実注文なし。


## 2026-10-15 — 開発期間の当日銘柄一覧と全価格キーを照合

固定vintageの当日master raw/normalized 772 objectを認証し、2024-07-31〜2026-03-03の386営業日・全1,702,477キーを価格と外部結合した。全営業日のmasterが存在し、対象銘柄の価格欠落・価格だけが存在する銘柄・全masterの価格欠落は0。既存対象ルールに一致する1,471,945行のうち、取引あり1,461,907、無約定10,038、不完全日足0、企業行動要確認359。対象外市場228,857行・特殊provider code1,675行も保持。単元株数は提供されないためnullを保つ。

元sourceのcatalog/manifest/byte hash/行metadata/キー/会社・市場・業種等の値を照合。全master catalogのpath/hash一覧は既存の学習時source-frame ID一致証拠に結び付け、終了後の元ファイル不変を確認した。42件の保存Parquetのhash・キー・日付・集計も独立再計算で一致。初回は同じキー値に対するpandas object/StringDtypeの差で0区間で停止。最初の4,386キーが一致することを別に確認し、両側の文字列dtypeを合わせた第2試行が09:55 JSTに正常終了。元データ・失敗記録は保持した。証拠docs/evidence/daily-universe-development-20261015。

これは当日銘柄一覧と価格の網羅確認であり、訂正前vintageや上場廃止イベントの復元ではない。最終評価期間のmaster/価格行・予測・target・NAVを読まず、採用へ昇格しない。企業行動/約定能力/呼値/決済/費用/税を通すNAV、本人設定/初回台帳/クラウド比較表示、最終selection/holdout・最新予測は未完。ライブラリsourceは7eea42aから不変で全747試験PASS証拠を保持し、同じ全回帰を再実行しない。Goal active、実注文なし。


## 2026-10-15 — 補足設定画面のローカル検証完了・本人依頼で一時停止

公開済みの口座・保有・資金・リスク入力に続き、補足設定 /settings を実装した。口座ごとの拘束現金、未反映取引、年内損益・繰越損失・NISA残余枠、費用・税の仮定と研究条件の確認を、保有入力の正確な版に結び付けて追記保存する。未入力はnullを保ち、0や法定税率を自動補完しない。本人限定API、競合拒否、古い保有版の検出、書き出し、追加DB migrationを含む。PC取込・初回台帳確定・比較結果のクラウド表示への接続は未実装で、画面にも準備中と明示する。

既存を含むNode 22試験PASS、TypeScript型検査PASS、ESLint全体/修正箇所PASS、Sites build PASS。初回型検査のunknown JSON応答3件を型ガードで修正し、失敗logも保持した。ローカルDBへmigrationを適用し、ブラウザーで保有なし・口座0・資金/リスク未定のテスト入力から、補足項目を未定のまま保存する流れを確認。実口座やproductionデータを変更していない。入力済み口座・HTTP境界/競合・エクスポート・モバイルを含む追加結合確認は残る。証拠docs/evidence/personal-settings-local-20261015。

本人の「きりいいところで停止して進捗とどれくらいかかりそうか教えて」により、このローカル検証済み・未公開の境界で停止する。確認用サーバーsession19454はCtrl-Cで終了、port5193の待受なしを確認。学習・監査・全回帰も終了済み。公開サイトはv3/source0073ca93のまま。選択されたSites checkoutの変更15ファイルをprivate/へ同一byteで保存し、Sites側のcommit/push/deployは行わない。Goalは本人依頼によるpausedへ移す。

全747試験PASS/coverage86.9514%のPython sourceは7eea42aから不変。18候補の学習・開発比較と386営業日の価格/当日銘柄網羅監査は完了。実市場の企業行動/執行/決済/費用/税を通す資産推移比較、最終モデル固定/holdout、最新予測・同期は未完。J-Quants API403も未解消。再開後の概算はアプリ残接続/結合確認が数時間〜1日、実市場評価/最終検証が追加数日以上。データアクセスと必要な企業行動情報が揃うことを前提とする粗い作業見積もりで、稼働日や採用を保証しない。実注文なし。


## 2026-10-15 — Android化の初期基盤とオフライン計算一致

本人のAPK配布・端末内計算の新指示に従い開始。PC main5b7aa4dはGitHub main0c9f88cより69commit先で、remote-onlyは0。Git bundleと未commit差分を保存し、fetchだけで照合した。移転先iburigakko-picoloom/stock-ai-specはPUBLIC、既存Release/Actions signing secretsなし。未公開設定・既存研究成果・本人の未commit変更を保全する。

既存React UIへCapacitor8.5.3/Android基盤を追加。PCの特徴量・保有比較・台帳/APIの具体module23本を同一byteでAPKへ同梱し、公式Pyodide0.29.3と依存21packageのhashを固定する。Web Worker上の端末内ASGI adapterを通し、ネットワークのPC/serverを立てない。desktop ingestionとfixture bootstrapのpackage facadeだけをmobile namespaceへ置換し、元計算moduleは変更しない。APIキーのKeystore暗号化・端末保存・更新確認のnative基盤も追加したが、Androidコンパイル/署名/配布・backup UI・差分取得・モデル取込は後続検証中。

端末内API4試験、既存React18試験、型検査/lint/Web build成功。外部HTTPSを遮断したEdgeの実WASMで、保有なし/nullの保存とPC版41/51特徴量の4合成銘柄に対する小数7桁一致を確認。初回の不足namespace、試験path、WAL backup/新FastAPI ASGI互換を修正し失敗logも保存。Windows制限環境のrename EPERMは許可された実行で再検証。Android実機は未接続で確認待ち。採用モデルは依然なし、公開APKへ私有モデル/市場データ/口座/APIキーを入れず研究表示を維持。証拠docs/evidence/android-apk-20261015/stage1.json。実注文なし。


## 2026-10-15 — Android端末内処理と署名配布のローカル検証

PCと同じ26具体moduleを同梱。Keystore暗号化SQLiteの確定保存、競合拒否、端末口座入力、J-Quants V2の5dataset差分取得/検証/訂正時点保持、41/51特徴量、data-onlyの3種類GBDT adapter、確認済みhashのみのモデル取込、暗号化backup/明示復元を追加。元PC production loaderは読出しProtocolと11:30当日計算の明示引数を追加し、既存研究pathは維持した。履歴不足・403・未採用を最新予測へ見せない。現在approved_modelsは空で私有model/dataを同梱しない。

Python39件中37成功、XGBoost2件のfloat32 cutとJSON decimalの境界差を発見・修正。3種類×2taskの6件と追加締切1件が成功し、重複を除く40ケースを確認。全体ruff、mypy63module、React18件、TypeScript/lint/build成功。外部HTTPS遮断WASMで41/51特徴量の小数7桁一致と6合成model vectorのPC一致、保存後のworker再起動/復元、短い履歴の422拒否を確認。VitestがPlaywright試験を拾う設定不備とpackage auditのroot-relative path判定も修正し、失敗logを保全した。

main関連変更→PR検証→main署名build→immutable Release/APK/hash/変更履歴のworkflow、署名証明書照合、増加versionCode、更新先/署名/サイズ/hash検査を実装。署名鍵は暗号化p12とWindows本人DPAPIで保全し、4Secretsへ改行なしstdinで登録済み。オフPCバックアップ手順とOSS表示を追加。AndroidコンパイルとReleaseはまだ未実行。本人端末はXiaomi 14T Proで、USB接続は後ほどとの回答。実機試験/Android版は未確認。

初回台帳・補足設定と保有比較の完全接続、最終model採用/配布条件、実API403と大量履歴の実機能力、本人による鍵のオフPC保管は残る。実注文なし。証拠docs/evidence/android-apk-20261015/stage2.json。


## 2026-10-15 — 公開前履歴検査とLinux CIの型検査対応

未公開履歴781 blobで秘密鍵/生市場ファイル/token形式を検査し該当なし。本人の指示に従い検証branchを公開し、draft PR #1を作成。初回CI 38674562787は既存PC用memory/checkpoint/holdoutのWindows分岐をLinux型検査が判別できず停止し、Androidコンパイル前。sys.platformの明示分岐へ変更し、計算や保存方針は変更しない。Linux/Windows指定のmypyは各63module PASS、Windowsの排他保存/holdout再開/メモリー保護6件PASS。CIへ両OSの型検査と関連試験を追加し再実行する。実データ再学習・実holdout評価は行っていない。実注文なし。


## 2026-10-15 — 初回Android CI成功・大容量保存の追加検証

CI 38674953724はfresh checkoutの試験親directory不在で停止し、mkdirを追加。続く38675174542でPython40件/関連6件、両OS型検査、React18件、通信遮断WASM一致、公開範囲検査、Android debugコンパイル/backup暗号化test/lintがすべて成功した。まだmainへmergeせずReleaseは未作成。

公開前のコード点検でnative SQLiteの単一blob読出し上限が大きな保存内容の障害になると判断し、256Ki文字ずつのGCM暗号化と世代/分割番号の認証、全体hash/長さ/分割数、transaction rollbackへ修正。初期の小さな状態だけでなく、3MiB合成状態の再読込・古い書込拒否・途中障害rollback・欠落/改変拒否をAndroid instrumentationへ追加した。debugアプリは別applicationIdへ隔離し、release状態を試験で変更しない。エミュレーター試験はCIの追加gateでありXiaomi実機試験の代替ではない。保存失敗/worker異常時には未確定メモリー状態を破棄し、確定保存から再起動する。画面lint/型検査/build成功、native修正とinstrumentationはCI待ち。128Mi文字state/150万行dataset制限と全市場長期履歴の実機能力未確認をrunbookへ明記。実注文なし。


## 2026-10-15 — Androidエミュレーター成功・main反映と署名互換性修正

追加したinstrumentation buildが依存libraryの試験APKも対象にしてKotlin重複で失敗したためapp taskへ明示。SDKのPATH、avdmanagerとemulatorの保存先相違もログで特定・修正し、Python/WebとAndroidを独立jobへ分けた。両jobが成功しなければ署名公開しない条件を維持。CI 38679352303で両job成功、API35 emulatorのStatePersistenceTest 3件/失敗0/skip0をXMLで確認。3MiB再読込、古い世代拒否、途中障害rollback、欠落/改変拒否を確認した。本人Xiaomi実機は後日USB接続待ちのまま。

PR #1をmainへmergeし、PCも0667659へfast-forward。元の研究71行、DECISIONS31行、STATUS89行は未commitのまま保持した。main CI38679892491でも両検証成功。最初のreleaseはWindows PKCS#12のkey bag別名不一致で署名前に停止。同じ鍵を暗号化PEM pipeで包み直し、元encrypted PFXを保持、同一certificate SHA256とRSA challenge署名を検証し、Secretsを再登録。鍵/証明書を作り直していない。再実行はAPK生成・apksigner検証・package audit成功、公開前の固定証明書の出力照合で停止。公開APK/Releaseはまだない。

固定hashと単一signerの検査は維持し、SDK範囲/大小文字/複数表示とSourceStampを区別する照合helperへ分離。異なる証明書、複数signer、不足出力の拒否を含む9件の試験とruffを通過。public署名情報を診断へ残し次runで公開を確認する。setupは既知の証明書がある状態で鍵が紛失していたら再生成を拒否する。実注文なし。


## 2026-10-15 — 研究用APK 0.1.11の初回自動公開と配布ファイル検証

main CI38682133797のverify/android/release全jobが成功。StockAI0.1.11/versionCode10011をGitHub Releasesのandroid-v0.1.11へ自動公開した。source97f665f、APK21,138,909 bytes、SHA256 bd86aeb312d4185a72c4a9c136aca2dce23e5db3fe0a640d5964d945bd868f9d。APK/update.json/SHA256SUMS/signature.txtを実ダウンロードし、サイズ/ハッシュ/固定certificate一致を確認。APK内の26共有PC sourceを当該Git commitのblobとbyte比較、runtime21依存も固定hash一致、approved_models空を確認した。認証なしの最新Release APIとupdate.jsonの取得も成功。

署名照合失敗は公式ツールの実出力がV2 Signer形式だったためと特定し、実際の形式を追加した10件の照合試験を通過。同一certificate/単一signerの拒否条件を維持し、署名鍵/証明書は最初の97a93c...から不変。最終CIのPythonは50+6件、React18件、WASMの41/51特徴量と6合成model vectorのPC一致/保存再起動/履歴不足拒否、Java暗号化、API35 emulator保存3件、Android lint/release build/apksigner/package audit成功。失敗と成功の証拠を保持した。

更新は起動時の版/履歴確認、HTTPS許可host・サイズ・SHA・appId・増加版・同一署名確認後にAndroid画面へ渡す実装。通信失敗時は現行アプリと確定保存を使用する。実機に旧版を入れた状態での更新/保存維持は未確認。Xiaomi14T Proは本人が後日USB接続予定で、Android版・初回導入・再起動・backup復元・403/通信断・実機計算/性能は未確認。エミュレーターを実機成功と数えない。

初回台帳/補足設定と個人比較の全接続、最終モデル採用と配布条件、実API403、全市場長期履歴の端末能力は残る。state128Mi文字・dataset150万行の制限を明記し、実予測/推奨を利用可能と報告しない。モデル/APIキー/実口座/市場データ/秘密鍵は公開APKへ含めない。署名鍵のオフPC保管は手順を用意したが本人実施待ち。元の研究71行・DECISIONS31行・STATUS89行と未追跡研究dataを保持。公開サイトv3は変更せず、実注文なし。実績docs/evidence/android-apk-20261015/release-final.json。


## 2026-10-15 — USBなしの本人操作による実機確認へ移行

本人がXiaomi 14T Pro上の操作と結果報告で進める方針を了承した。USBを導入・通常利用・更新や受入開始の必須条件にせず、ログ取得などが必要な場合の選択肢とする。GitHubの公開最新版が0.1.11、APK21,138,909 bytesであることを再確認し、初回導入→設定の「現在は保有なし」保存→アプリ再起動の確認手順を用意した。APIキーなしで始められる。以降のオフライン・端末再起動・暗号化backup/復元・次版更新を段階的に確認する。

手順と未報告の一覧はdocs/evidence/android-apk-20261015/xiaomi-manual-acceptance.md。実機結果はまだ報告されておらず、成功扱いにしない。Android/HyperOSの版、実機での数値一致と性能も未確認。本人報告と自動試験の証拠を区別する。今回は文書と確認方法のみを変更し、APK/計算コードは不変のため既存試験を再実行しない。研究用表示とモデル採用待ちを維持し、実注文なし。


## 2026-10-16 — Xiaomiの保存・アプリ再表示を本人報告で確認

「現在は保有なし」を保存し、アプリを開き直して保持を確認する案内に、本人から「のこってる」と回答があった。保存・再表示が実機で成功した本人報告として記録し、必要な導入・起動も確認済みとする。PCからの観測やログ取得は行わず、アプリ版の端末表示とAndroid/HyperOSの版は未確認のまま。

次は機内モードかつWi-Fiオフで起動・再表示を確認する。端末自体の再起動、backup/復元、次版への更新、実APIと端末内計算の一致・性能は未確認。証拠docs/evidence/android-apk-20261015/xiaomi-manual-acceptance.mdの結果と残項目を更新した。今回は文書のみでAPK/計算コードは変更せず、既存試験を再実行しない。実注文なし。


## 2026-10-16 — 実機の一括成功報告・端末内の補足設定と初回台帳

本人から、オフライン・端末再起動・backup作成・誤password拒否・正しい復元は「ぜんぶいけてる」と報告があり実装を再開。0.1.11での本人報告として記録し、次版更新・実API403・実機計算一致/性能は成功扱いにしない。Android/HyperOS/アプリ版の数値も未報告。

manual-personal-settings-v1の共有Python schemaと端末内保存、口座・保有revisionの競合拒否、旧0.1.11入力の共有storeへの移行を実装。null・明示0・無料手数料確認・NISA区分・小数現金を保持し、補足設定は正確な保有revisionへ結ぶ。初回台帳は全口座の確認previewから明示確定し、台帳と確認receiptを一transactionへ保存。15分失効、変更/改変/不足/既存台帳/約定履歴を拒否。日足参照日と初回残高をhomeへ表示し、その後のdraft編集で台帳を書き換えない。共有のread-only個人比較へ入力・補足条件を渡し、不足理由を画面表示する。最新原予測/市場根拠、モデル採用と実市場評価は未完。

変更部分のPython26件、React21件、型/Lint/buildを確認。通信遮断WASMの特徴量41/51・6モデルvectorと新規の補足設定/初回現金/再起動復元は2件成功。最後の確認内容再計算の追加後はPython26件成功、WASM再試験はローカルserver起動30秒でtimeoutしたため全体試験後に再実行する。全Python790件とcoverageの検査は実行中。最初のPython試験は金額文字列表記1/1.0の比較、最初のReact試験はcleanup漏れで失敗し、値の検査を維持して修正。失敗logも保持する。実注文なし。


## 2026-10-16 — 補足設定・初回台帳APK 0.1.12公開と検証完了

source ab2d5caを保存してmainへpushし、CI38766244677のverify/android/release全job成功。Python71+6件、React21件、通信遮断WASM2件、Android15/API35の保存3件、Java暗号化/lint/build/署名/公開範囲検査を通過した。ローカルWASM再試験のserver起動timeoutは同一最終sourceのCI成功で確認を完了し、試験条件を緩和していない。

StockAI0.1.12/versionCode10012を自動公開。APK21,150,645 bytes、SHA256 d3a31fc717a28bd2453eb5ca1f69df9398893404051e8c880bad44e997162fe0。配布4ファイルを実取得し、サイズ/hash、初回から不変の固定certificateを持つ署名build報告、27共有PC source・mobile adapter6件のGit blob一致、21runtime依存hash、採用model0件を確認。認証なしの最新Release API/update.jsonも10012を返した。実機の更新/新画面の確認は別途未実施。

ローカル全回帰は790件を収集し789成功、1件が試験準備のgit rev-parseで作業directoryの所有者確認により停止した。信頼先を当該試験processのGIT_CONFIG環境だけへ指定し、該当1件と全体収集後に追加した3件を再実行して4成功。既存789件と合わせ最終793件を確認し、append後coverage87.07%（基準85%）を達成。全件が一度のrunで成功したという記録にはしない。コード修正や試験skipで回避せず、元の失敗logを保持した。64moduleの型検査、React型/Lint/build、変更部Python26件も成功。証拠docs/evidence/android-personal-20261016/verification.json。

本人の0.1.11での保存・オフライン・端末再起動・backup/復元の成功報告は記録済み。新APKの実機更新、新画面、最新原予測/市場根拠と個人比較の全接続、初期履歴の一括取得、最終モデル採用/配布条件、実市場NAV、実API403、全市場長期履歴の端末能力、所有者による鍵のオフPC保管は残る。元の研究71行・DECISIONS31行・STATUS89行と未追跡dataを保持し、private siteは変更していない。実注文なし。

## 2026-10-17 — 完成工程の固定とChatGPT連携の実装開始

本人の完成指示に基づき、docs/FINISHING_PLAN.mdとD112へ、300億円/300候補・全保有維持、モバイル回線、毎営業日の自動更新、本人用モデル一度取込、ChatGPTの独立調査と判断併記、48px/12pxの操作間隔を固定した。既存研究成果と未commitの研究記録は保持する。

Androidの別pluginへ公開OAuth client、loopback/PKCE、JWKS/issuer/audience/nonce/期限/同一本人検証、Keystore資格情報、更新、モデル一覧、推論深度保存、検索付きSSE完了確認を追加した。資格情報をJS/backupへ返さず、別料金APIへ切り替えない。認証故障・scope・中断SSE・暗号文差替のAndroid試験を追加。Reactの接続画面と保存前の試験禁止/権限不足/中断の3試験を追加した。

ローカルTypeScript/Lint/build成功、React24件PASS、Pythonの配布検証10件PASS。最初のReact試験はWindowsのsandbox一時directoryのrename EPERMで試験収集前に停止し、作業領域内TEMP/TMPで同じ試験を再実行して成功。Androidコンパイル/機器試験と実アカウント認証・検索はまだ未確認。PCにJDK/SDKがないため既存Android CIを使用する。制限環境でghの接続確認が失敗し、接続済みGitHubアプリもbranch作成403だった。許可された読み取り接続で既存ghのrepository push/admin権限を確認し、既存CLI経路へ戻した。認証情報の変更や取得・表示は行わない。

これは連携入口の段階であり、独立調査の自動保存/表示、背景実行、履歴一括取得、実市場評価、モデル採用、最新予測/個人株数の接続、実機性能は未完。Goal active、実注文なし。
