# Decisions and Open Questions

更新日: 2026-08-22  
状態: v0.2

## 確定事項

### D213 — 選定・最終評価・採用接続へ範囲を固定し、将来ラベル依存の対象集合を停止（2026-10-20）

- 最新の本人指示をFINISHING_PLAN冒頭へ置く。0.1.27の画面工程を締め、研究/採用/配備を別に扱う。元作業の未commit差分、18構成×4タスク、元152件と追加探索、私有2weight、未採点の最終期間を保全する。
- 日次の回帰選定は3seed平均MSEを最小化し、代表は固定最小seed17とする（metric名v2）。順位の選定とensembleの最強個別IC条件は維持する。古い凍結artifactのmetric名/identityは書き換えない。MAE/RMSE・bias・同じ行のzero_returnとの誤差差を追加し、校正や費用後運用成績とは区別する。
- 元152件の共通対象は、全市場の保存OOFから当日確認できる国内100株単元を選んだ集合であり、旧アプリ300でもTOPIX500でもない。全結果byteを再照合し56完走/96不完全を保持する。ただしOOF作成は将来ラベル利用可能行に限定される。実際に当時の規模区分と照合し、予測欠落の大半が出口価格なしの上場廃止に対応することを確認したため、元の完走は実行可能な対象集合の評価証拠へ昇格させない。
- この既知の`common-domestic-OOF-domain-v1`を新たな通常研究NAVとして再生する入口を、企業行動/価格読込前に`LABEL_CONDITIONED_UNIVERSE`で拒否する。保存済み結果の削除/上書き/合否の改変はしない。独立した当時の候補集合と必要予測を用意し、未来ラベルの欠損で銘柄を消さない。現在weightによる過去OOF補完、欠損価値ゼロ、strict/holdoutゲート解除は行わない。
- 保存した当日付マスタは後日取得版。規模区分の履歴を調べられても、実受領時刻や月次適用履歴を再現済みとはしない。元152件の欠損と、TOPIX500の予測網羅・当時情報の不足を分ける。最終基準案はFINISHING_PLANに提示し本人確認待ち。実holdout/owner_manual承認/新規公開配布は行わない。
- 10/21追加：最終予測の生成集合も将来ラベルの可否から分離する。既存の単回ledger/再開/fit/推論を再利用し、特徴量行には予測を残す。採点は別maskとし、新しいv2 reportに予測/採点/未採点件数・理由を保存する。labelなしの指標はnull、rank ensembleは全予測の順位化後に採点maskを適用する。v1 reportのidentity/読取を保ち、既存結果を再採点しない。採用不可のliteralは不変。最終戦略NAV・本人採用・任意headの接続が完了したとはしない。

### D212 — 青基調の設定と上部の簡潔な更新案内（2026-10-20）

- 本人が緑から青への変更と「上から新しいverがあります」の確認を希望したため、D210の設定一覧の構造を保ったままaccentを既存の青tokenへ揃える。損益/売買を表すsemantic色、保存値・計算式・モデル・nativeは変更しない。
- 起動時の既存更新確認を使い、最上部のsticky帯へ短い新版メッセージ・版・更新ボタンを表示する。長い変更内容は任意の折りたたみで参照する。勝手に取得/インストールせず、native応答待ちを直列化し、提供元許可・失敗・再試行を区別する。
- 320/390px・文字100/150%の上部表示/青色/横はみ出し・48px操作/12px間隔、更新なし/通信失敗/Web版/二重操作/許可要求/取得失敗と再試行を検証する。通常APKは変更commitの必要CI成功後に既存署名で作り、承認済みの更新配信経路へ反映する。旧0.1.26の公開資産を上書きしない。

- 製品3209604/CI39431174408の必要3job成功後、既存署名・同一CI資産の0.1.27を承認済み更新先へ配信した。公開URLと全4assetの認証なし読戻し/hashを確認。旧0.1.26は保持し、本人実機の成功とはしない。

### D211 — 検証済みAPKを既存のアプリ内更新先へ配信する（2026-10-20）

- 本人がAPKと更新情報の公開を承認したため、成功CI/署名検査済み0.1.26候補の同一byteを既存GitHub Releasesへ公開する。候補source18fb6d8をtagへ固定し、main mergeや再buildは行わない。私有モデル/市場/認証/口座情報は非公開のまま。
- 既存の更新確認は起動時のlatest API、数値3桁tag、非draft/非prereleaseを要求する。互換tag `android-v0.1.26`を使い、実versionName `0.1.26-candidate`/researchOnly=true・正式HOLD・実機未確認を明記してlatest配信する。公開したことをモデル採用やXiaomi試験成功に読み替えない。
- draft上の全4assetを読み戻して元byte/hashを確認してから公開する。公開後は認証なしの既存URLでlatest/更新JSON/APK等のHTTP 200とbyte/hashを照合する。既存のサイズ/署名/applicationId/増加code検査は維持し、取得/インストールは本人のタップとAndroidの確認へ渡す。無操作のsilent更新や本人端末への自動installは追加しない。

### D210 — 提示画像に合わせた現在値付き設定一覧と個別編集（2026-10-20）

- 本人提示の「シンプル一覧」を優先し、D209の7折りたたみを5つの見出しと行末の現在値・右矢印へ変更する。緑の線画アイコン、白いgroup、薄いグレー背景を採り、既存5タブと機能は保持する。画像中の50万円/10%/接続済み/5日単独を本番の初期値や能力へ読み替えない。実APIキー保存状態・保存済み本人入力・5日/20日・native通知許可を表示する。
- 編集は同じ設定routeのqueryで表示を切り替え、未表示のcomponentも維持する。戻る・履歴・編集し直しで下書きと保存途中を維持する。口座/資金/下落率は保存対象のfieldだけを保存済みportfolioへ重ね、別編集の未保存入力は送信しない。既存expected_revision_idを維持する。全入力の読戻しは詳細内で、他の編集も戻ることを明記する。
- 自動更新の一覧switchと詳細操作は、既存の日次制御を1つだけ共用する。応答前に状態を変更せず、連打を直列化する。操作前に発行した古い状態読取と、操作中のpollを完了後の状態へ反映しない。停止/再開自体のnative/WorkManager/データ処理は変更しない。
- 通知は独立した通知設定が既存nativeにないため、偽のON/OFFを追加しない。実際のAndroid許可を表示し、詳細の既存許可要求へつなぐ。オフや再設定のAndroid操作を案内する。画像にある取引終了後の更新へ時刻を変更せず、既存日次処理を維持する。
- 320/390px・文字100/150%で一覧/全編集の操作高・間隔・横はみ出し・数字の非分断・キーボード/履歴・下書き/保存保持を検証する。研究計算・市場原本・モデル/holdout・APK候補・Xiaomi確認は別範囲として保全する。

- APK化時のAPI35実画面確認で、資金/モデル編集から画面内の「設定一覧へ」は正常に戻る一方、端末の戻るキーはActivityを閉じる既存shell動作を確認した。browser履歴と端末キーを区別し、0.1.26候補では画面内操作を案内する。失敗ログを保持し、native変更を追加してこの候補の範囲を広げない。Xiaomiは未確認。

### D209 — Android設定は項目一覧から必要なフォームを開く（2026-10-20）

- 本人から「設定画面の情報量が多すぎる」との指摘。Androidの全フォームがWeb用分類タブより上へ無条件表示されていたため、上記7項目の折りたたみへ変更する。初期表示は項目名と短い説明だけにする。既存の参照画面・操作は残し、ChatGPT手動相談への入口も既存routeへつなぐ。
- native detailsで表示だけを切り替え、componentをunmountしない。下書き・保存処理・復元previewを開閉で破棄せず、開くだけで保存・取得・計算・AI調査を実行しない。既存の状態参照は維持する。APIキー・口座の読込失敗は一覧で見えるようにする。
- 48px以上の操作高と12px以上のボタン間隔を維持する。320/390px・文字100/150%で、横はみ出し、キーボード開閉、未保存入力、保存中の閉じ直しと完了表示を合成native bridgeで確認する。Android/Xiaomiの実保存・暗号化試験とは区別する。
- 計算式、研究モデル、18候補・152条件、正式HOLD、未使用holdout、API送信項目、保存形式、WorkManagerは変更しない。従来0.1.25候補の確認は継続できるよう保全し、今回の画面変更を同候補へ反映済みとは表示しない。

### D208 — 同じ締切のリスト訂正は最後に記録した不変版へつなぐ（2026-10-20）

- 完成前の変更経路確認で、同じeffective_atの版をhash降順で選ぶと、8回の合成訂正中4回で直前版を飛ばすことを再現した。hashは受領順・記録順を表さない。対象数や予測式の問題と区別する。
- effective_atの降順を維持し、その同時刻内だけ既存SQLite rowidの記録順を使う。新しいtable/移行や既存リストのhash/内容の書換えは行わない。再表示、再open、古い締切の後からの参照、SQLite backup復元で直前版と差分を保つことを検証する。
- 関連14件と最終のリスト5件が成功。最初の追加試験はdiff.changedを銘柄文字列と誤認した検査で停止し、既存のbefore/after構造を厳密比較して修正した。元の再現・試験失敗を保存する。0.1.24候補は旧方式の比較用に保全し、新方式の受入は修正後sourceの必要CI/候補で行う。
- 特徴量・モデル・入力cacheの式と版、既存152条件/正式HOLD/最終holdoutを変更しない。Androidの追加/訂正/保有変更は明示した合成fixtureで先に分岐を検証し、新実営業日の実測やXiaomi成功とは表示しない。

- 修正後791dfa5で、合成Android11経路/56予測/8版リンク/中断rollback/再起動と、実730日通常予測保存121.241秒/978予測・全特徴量/入力版一致を別確認した。必要CI39387328864全成功、同sourceで署名0.1.25候補を作成した。D207初回/B1は不変50計算file・同cache版・同実リストへ限る再利用であり、現在の初回再測定ではない。
- in-place VM再起動が既存5400MiB host guardで停止した事実は残す。同じAVD/Keystoreを別の新VMプロセスで冷間起動し、再install/seed/再計算なしに全47tableの読戻しを確認した。guardや時計を変更して合格させない。
- 実前日再生では、当時締切までに未受領の途中履歴によりnext session認証で停止。完全な現在版の利用と、当時版の再現を区別する。受領時刻/guardを変更せず、真正な次営業日の測定を残す。合成変更経路を実日次/実イベント/Xiaomiの成功へ読み替えない。[結果と残件](evidence/topix500-20261020/d208-completion.md)。

- 通常署名0.1.23→0.1.25の更新では元44table/590保存予測/設定/保有/モデル/試験用credentialの保持を独立照合した。私有試験がreleaseのcloseForTestを呼んだ失敗は試験側だけで修正し、製品の拒否を維持する。冷間試験の参照JSON消失も失敗のまま残し、同じ保存AVDで参照原本だけを復元した追加読戻しを別証拠にする。保存capsuleの世代/hashと全tableは再投入せず比較し、hostの搬送権限と通常アプリの権限、emulatorとXiaomiを分ける。[署名更新記録](evidence/topix500-20261020/release-upgrade.json)。

- 20日18:42 JSTに新たに受領した20日分5data/21日calendarは、元を保持した私有コピーへ反映する。20日11:30の全入力/978予測/出所が変わらず既存予測を再推論せず返すことを、実受領後に厳密比較した。受領時刻を遡らせず、21日の予測は実行しない。PCでの受領・反映19.391秒をAndroid日次性能へ読み替えない。当日の所属受領、実営業日のAndroid/通知、Xiaomiを残す。[実差分の準備と時点分離](evidence/topix500-20261020/live-delta.json)。

### D207 — 共通計算で使わない履歴metadataとv1正規化の反復だけを減らす（2026-10-20）

- D206/source5b07f3eのPC全値一致は成功したが、Android初回は再び600秒で停止。sampled app+rendererは3,049,295,872bytesへ減少したものの未合格。既存stageログではrequest後のexport-archive→export-chunksへ到達してからtimeoutしており、予測の暗号化commit成功とは扱わない。必要CI39374367653は追加修正が必要なため自分のrunだけ停止し、元0.1.23/PR #2の試験は触らない。
- 固定APKに時間観測だけを付けた私有診断版で工程を測る。計算ソース・時計・制限は同じで、診断runtimeの差分とhashを別記録し、通常候補へ使わない。master読込226.509秒、その中のraw v1行hash61.340秒を観測。cache再利用やPC時間を初回Androidの合格へ読み替えない。
- 新context経路だけ、過去の会社名の保持と未使用の上場interval列の生成を省く。全市場の対象行、日付欠損/不正履歴の除外、適格性検査、業種、共通集計式、price joinは維持する。画面の会社名は従来どおり実受領済みの当日masterを使う。旧方式/研究用の既定universeは変更しない。
- raw v1 hashのJSON tokenをUTF-8へ一度変換し、検証済み列の既存128件LRU内だけで再利用する。各refのDB bytes読取/検証は毎回維持し、変更・消失・別圧縮・trailing dataを旧cacheが隠さない。定数列も同じv1表現を使う。数値/Unicode/key順/欠損・raw/normalized照合・全source IDを変えない。codecも計算cacheのコードfingerprintへ含める。
- 同じ初回の中では、既に原本/hashを検証した財務・暦・TOPIXの小さなframeを共有し、財務結合用に二度読み込まない。永続の原本検証を省略するcacheや全市場価格/master frameの保持は追加しない。別の再計算では受領版を改めて確認する。
- 変更後の関連試験、実730日PC全値一致、通常APKのAndroid初回/保存/復元/再起動と必要CIを別に検証する。600秒・RAM/CPU・export上限・正式HOLD・最終holdoutは不変。

### D206 — 初回600秒停止を不合格として保全し、全量コピーと反復走査を除く（2026-10-20）

- D205/source203f42bの必要CI39367905793は全成功だが、実730日/493銘柄の初回Android予測要求が600秒で停止した。cache再利用128.941秒・978予測完全一致・B1/再起動後47table一致の成功と分離し、このCI成功だけで通常候補を完成扱いにしない。旧0.1.23は不変。停止前のsampled app+renderer最大3,328,581,632bytesで、background processのlow-memory killも記録する。計算renderer自体はJUnit終了まで存在し、直接の失敗はcompute timeoutである。
- 初回の選定済み履歴を銘柄ごとに全行文字列比較する代わりに、symbol位置indexを一度作る。履歴0行の対象にも同じ空schemaのcacheを残す。分割調整は、元sourceから分離済みのprivate merge結果を使う新context経路だけで重複deep copyを除く。既定/単独helperは元入力を保護するcopyを維持する。
- 数値式・調整係数の累積順・全市場lineage hash・全市場/業種母集団・財務時点・feature定義は変えない。v1 cache証拠と停止ログを保持し、新しいコードfingerprintで安全に再構築する。新sourceでPC全値一致とAndroid初回/再利用を測り直し、必要CI成功後だけ別候補を作る。600秒/RAM/CPU/export上限・holdout・正式HOLDは維持する。

### D205 — TOPIX500事前選定を独立した試験方式として実装する（2026-10-20）

- 本人の最新指示を優先し、9fe568eから独立worktree/`feature/topix500-preselection`で進める。0.1.23/c2fa278、PR #2、元の未commit差分、市場原本、152条件、最終holdout、Xiaomi一括受入は保全する。D197/D199の共通cache追加保留を今回の試験範囲で変更する。
- `/v2/equities/master`のScaleCatがCore30/Large70/Mid400で、末尾0・国内普通株ProdCat=011・対応市場の銘柄をそのまま採る。数を500へ補充せず、売買代金上位300への再選別もしない。全保有を加え、非対応/履歴不足を理由付きで扱う。正式採用はHOLD。
- 旧方式を既定に保持し、新方式は`topix500-preview`の明示選択だけで有効化する。月次の不変リストと構成変更時の追加版に、選定理由・規模・出所・実受領時刻・適用時刻・前版差分・hash/規則版を保存する。当日の検証済み受領がなく、現時点の所属を確認できないときは停止する。後日取得版による過去バックテストの構成再現を名乗らない。
- 価格・所属の全市場共通計算を維持し、財務の日次展開は対象履歴へ限定する。再生成可能な銘柄別履歴/common統計cacheを原本とは別tableへ保存する。通常の追加日では全市場の直近2日と対象履歴を読み、元の共通計算式を再利用する。訂正・分割・追加銘柄・code/schema変更時は保守的に再構築する。初回/再構築はまだ全市場の価格入力を保持するため、日付batchだけで初回まで完結したとは扱わない。
- cacheは損失のない数値/時刻/dtype形式と内容hash、元の受領版、コード版を結ぶ。原本のv1 source IDは日別のrow-hash列から同じ順で再構成する。保存済みSHA digestの連結で代用しない。warm読取は認証済みcacheと原本の版参照を確認し、原本全BLOBの再検証を毎回行ったとは表示しない。
- 旧/新で共通する銘柄の特徴量・個別推論と、全市場の共通統計を照合する。対象集合による上位20の違いは算術誤差と区別する。現行の2つの回帰headは銘柄ごとの推論であり、cross-universe正規化を新たに加えない。過去152条件を新方式の運用成績へ読み替えない。
- 600秒・CPU/RAM・export/restore上限は維持する。PC実データ一致、Android全量と暗号化保存、差分/訂正/入替/再開、対象commitの必要CI、別候補のXiaomi受入が済むまで既定を切り替えない。既存0.1.23の受入を新方式の成功とは扱わない。

根拠：[上場銘柄一覧](https://jpx-jquants.com/ja/spec/eq-master)。翌営業日情報は17:30以降に提供され、各recordの実際の利用可能日時や訂正前の値は提供されない。従って提供時刻の目安から受領時刻を推定せず、保存済みの実受領を11:30境界と照合する。

### D001 — 意思決定支援

本製品は自動売買ではない。AIは実注文しない。最終判断と注文はユーザーが行う。

### D002 — 提案時刻

毎営業日11:30時点で利用可能な情報を凍結し、12:30に向けた提案を作る。

### D003 — 中心目的

おすすめ銘柄ランキングではなく、現在の保有・現金・候補を同時評価して目標ポートフォリオを提案する。

### D004 — 判断対象

現在保有株を毎日必ず再評価する。新規候補だけを前場AIへ入れない。

### D005 — Action

最終Actionは:

- BUY
- HOLD
- REDUCE
- SELL
- SKIP

### D006 — 株数中心

内部では比率・金額を使えるが、画面は現在株数・推奨株数・増減株数を中心にする。

### D007 — 初期売買単位

初期版は100株単位。

### D008 — HOLD反実仮想

乗り換え判断は、代替案と「現在のままHOLD」を比較する。

### D009 — 全体最適化

単純なA→Bペア交換だけでなく、ポートフォリオ全体を同時最適化する。

### D010 — コスト

最低限:

- Commission
- Spread
- Slippage
- Market Impact

を考慮する。

SBIの手数料無料は設定条件であり、ハードコードしない。

### D011 — 税と口座

保有は `symbol × account_bucket` で管理する。

最低限:

- NISA / 特定口座等
- 取得単価
- 保有株数
- 含み益・損
- 年内確定損益
- ユーザー入力の損失繰越
- NISA入力情報

を扱う。

### D012 — 税影響

含み益銘柄を売る場合は、推定即時税影響をHOLDとの比較に含める。

### D013 — 機械学習の役割

LightGBM、XGBoost、CatBoost、前場AI、深層学習等は期待リターン・下振れ・不確実性を予測する。

最終株数を決めるのはDaily Portfolio Decision Engine。

### D014 — M14

M14の名称は `Daily Portfolio Decision Engine`。

### D015 — No-trade

毎日判断するが、毎日売買を提案しない。売買なし・全額現金も有効。

### D016 — 状態付き検証

バックテストは前日の現金・保有株を翌日へ引き継ぐ。

### D017 — 実取引反映

初期版はユーザーが約定株数・価格を手入力。将来CSV取込へ拡張。

### D018 — スマホの役割

スマホは確認・通知・入力・監視。機械学習本体をスマホのバックグラウンドで実行しない。

### D019 — Top-10

Top-10等加重はBaseline。最大10銘柄は暫定制約であり、目的ではない。

### D020 — Point-in-time

`available_at <= as_of` を必須にし、未来情報・生存者バイアスを防ぐ。

### D021 — モデル採用

高度なモデルはChallenger。単純モデルより安定して改善した場合だけ採用。

### D022 — Goal運用

製品全仕様をGoal本文へ詰め込まない。MDを正本にし、Goalは段階別に実行する。

### D023 — 主要画面の役割

- ホーム: 実資産と実保有
- 今日: 当日の株数変更の結論
- ランキング: 予測順位の探索
- 銘柄詳細: 理由とHOLD比較
- 検証: モデルとDecision Engineの実力
- 設定: 資金・口座・税・コスト・データ・モデル

### D024 — 提案・判断・約定の分離

AI提案、ユーザー判断、実際の注文・約定、Paper結果は別レコードとして保存し、互いに上書きしない。

### D025 — UIのAction表示

`current > 0` かつ `target = 0` は必ずSELL。REDUCEは0株より多く残る場合だけ使用する。

### D026 — ランキングの位置付け

ランキング上位は予測上の候補であり、最終BUYを意味しない。最終Actionは保有、現金、税、コスト、リスク、100株制約を含むDecision Engineが決める。

### D027 — UI仕様の正本

画面、ルート、操作、状態、表示データ、UI受入条件は `docs/UI_SPEC.md` を正本とし、`docs/ui-reference/` は非正本の参考画像とする。

### D028 — 広い特徴量候補プール

MACD、RSI、移動平均、Bollinger、ADX、ATR、出来高、財務、相対強度、需給、市場環境、前場指標を広い候補プールとして持つ。

個別候補と計算規則の正本は `docs/FEATURE_CATALOG.md`。

### D029 — 段階別Feature Set

特徴量は次の順で実装・検証する。

- FeatureSet V0: 最小Baseline
- FeatureSet V1 Core: 約40〜60の最優先候補
- FeatureSet V2 Extended Technical
- FeatureSet V3 Data-dependent

候補プール全体を一度にChampionモデルへ投入しない。

### D030 — 指標を固定売買ルールにしない

RSI、MACDクロス、移動平均クロス等は特徴量候補であり、直接BUY / SELLへ変換しない。

最終Actionは予測モデルの出力をDaily Portfolio Decision Engineが現在保有・税・コスト・現金と統合して生成する。

### D031 — Feature Family Ablation

特徴量の採否は、家族単位のOut-of-Sample Ablation、複数fold・複数seed、Decision Engineの税・コスト控除後改善で判断する。

SHAPや単一の重要度だけでは採用しない。

### D032 — Feature Definitionのバージョン管理

特徴量名、式、入力列、パラメータ、warm-up、正規化、利用可能時刻、実装名・版をFeature Registryへ保存する。

TA-Lib等のライブラリは実装手段であり、仕様の正本ではない。

### D033 — Feature選択も時系列分割内

clip、percentile、相関削減、Feature選択等は訓練fold内だけでfitする。検証期間や最終holdout全体を使って選択しない。

### D034 — Goal 1のBaseline境界

2026-08-24の最新Goal指示を、旧`CODEX_GOAL.md`テンプレートより優先する。

Goal 1ではMomentumとRidgeを実装し、LightGBM、Elastic Net、Logistic RegressionはGoal 2以降の比較対象に残す。fixture成績を収益性最適化へ使わない。

### D035 — Goal 1のテクニカル指標実装

FeatureSet V0 / V1 Coreの主要指標はNumPy / pandas上の小さな決定的実装と既知値テストを正本にする。TA-Lib等を将来採用する場合もFeature Definitionのversionを更新し、数値差分を検証する。

### D036 — Goal 1の離散探索境界

Daily Portfolio Decision EngineのMVPは、明示的candidate universe内の100株候補を全体同時評価する上限付き厳密列挙を使う。組合せ数が設定上限を超えた場合、未レビューの近似解へ無言で切り替えずfail closedする。大規模universe向けoptimizerは次Goalの課題とする。

### D037 — Goal 1の税計算精度

初期Tax Engineは、NISAの即時税影響0、課税口座の設定税率、年内確定損益、ユーザー入力の繰越損失を使う意思決定用推定とする。取得費・複雑な損益通算・申告確定額を断定せず、すべて推定として出力する。

### D038 — Goal 1ラベルの意味

実前場・12:30価格が未接続のGoal 1では、1日・5日・20日の調整後終値間absolute returnを研究proxyとして明示する。これは本番の12:30 entryやTOPIX/sector超過リターン予測を意味しない。label endpointの`available_at`がsnapshot cutoffを超える場合はlabelを保存しない。

### D039 — Sector / Breadthの入力境界

sector-relative値とmarket breadthはcandidate subsetから再計算しない。履歴時点で確定した明示的sector contextとmarket contextをFeature Engineへ渡し、coverageまたは必要capability不足時はfail closedする。

### D040 — 税の経済効果と決済現金

推定税負担、NISA機会費用、証券会社の推定源泉徴収による決済現金影響を別フィールドにする。同一口座bucketの複数売却は一括評価し、同じ損失繰越や年内利益を重複利用しない。

### D041 — J-Quants V2専用境界

日次公式データadapterは`https://api.jquants.com/v2`だけを許可し、V1 token、mail/password、refresh token、設定ファイル読込を実装しない。認証値はlive command起動時にprocess環境の`JQUANTS_API_KEY`からだけ読み、header・例外・log・manifest・fixture・Markdownへ値を出力しない。

### D042 — 初回取得以前へ訂正値を遡及させない

J-Quants REST responseは現在返される値の過去訂正時刻を提供しない。したがってGoal 2Aのexternal recordは`available_at = received_at`とし、初回backfillを過去の予測時点から利用可能だった値として扱わない。同一natural keyの後日訂正は新しいimmutable objectとして保存し、PIT queryはcutoffまでに受信した最新版だけを返す。初回取得以前の完全なrevision historyは`PARTIAL` capabilityとする。

### D043 — Content-addressed immutable object

raw / normalizedは`dataset + source_date + payload_hash + schema_version`から識別するimmutable Parquet objectとする。Parquetとmanifestを一時directoryへ完成させてからdirectory単位で公開し、同一payloadの再取得は重複させない。中断・品質失敗・catalog失敗は既存の正常objectを置換しない。

### D044 — Raw価格とresearch調整価格の分離

`/v2/equities/bars/daily`の`O/H/L/C/Vo`をexecution参照用raw系列、`AdjO/AdjH/AdjL/AdjC/AdjVo`をresearch用系列として別columnに保存する。`AdjFactor`とpayload由来の`adjustment_version`を保持し、両者を暗黙に上書きしない。

### D045 — Provider codeと内部symbol

J-Quants V2の5文字`Code`は`provider_code`として原値保存し、末尾のprovider桁を除いた4文字を内部`symbol`とする。数字・英字を含む新証券コードを許可し、整数化しない。

### D046 — Capabilityは推測で補完しない

利用planと実装範囲を`AVAILABLE / PARTIAL / BLOCKED_BY_PLAN / BLOCKED_BY_DATA_CAPABILITY / OUT_OF_SCOPE`で明示する。Goal 2Aでは財務summaryの期末発行株式数を日次株式数へ補間せず、breadthは全銘柄coverage検証前、historical universeは初回取得以前の訂正履歴欠落を理由に`PARTIAL`とする。

### D047 — Goal 2Aの取得単位

Free planでも安全に動く既定datasetは銘柄master、株価日足、財務summaryとする。Light以上の営業日calendarとTOPIXは明示選択する。全endpointは日付単位、逐次rate limit、`pagination_key`追跡、429/5xxのbounded retryで取得し、fixtureへのproduction fallbackは行わない。

### D048 — Bulk履歴のcheckpoint境界

Goal 2の履歴取得は公式J-Quants V2 `/bulk/list`・`/bulk/get`を使う。署名付きURLは保存せず、Bulk keyのhash、size、last-modifiedからfile fingerprintを作る。downloadしたCSVはprovider source dateごとに分割し、Goal 2Aと同じraw / normalized / quality pathへ通す。全date sliceのimmutable publish完了後だけfile checkpointを`SUCCEEDED`にし、`RUNNING`・`FAILED`はresume時に再取得する。

### D049 — Source revision vintageと研究上の利用可能時刻を分離

J-Quantsから受信したexternal recordの`available_at = received_at`はD042どおり維持し、訂正vintageのPIT境界とする。Production Research Datasetを構築する際は、このsource vintageを`source_snapshot_as_of`で固定したうえで、日足・TOPIX・集計contextを「次のJPX営業日11:30」、財務をproviderの`announced_at`で利用可能とするderived observationを別に作る。derived recordにはsourceの`revision_available_at`も残す。これは初回取得以前のprovider訂正履歴を復元するものではなく、単一取得vintageによるhistorical researchという制約を保持する。

### D050 — Goal 2 research universeと欠損exit policy

Goal 2の初期research universeは、各営業日のmaster snapshotに存在する東証Prime / Standard / Growth（market code 0111 / 0112 / 0113）の普通issue（5文字provider code末尾0）とする。master snapshotは営業日ごとの完全一致を必須とし、現在の構成を過去へbackfillしない。5・20日label endpointに価格がない場合は次の観測価格へずらさず、endpoint時点でuniverse外なら`DELISTED_NO_EXIT_PRICE`、universe内なら`SUSPENDED_NO_EXIT_PRICE`としてtargetを欠損にする。

### D051 — 12:30 labelの能力境界

正確な12:30 entry labelは、Premiumで提供されるafternoon-session adjusted openを取得できる場合だけ生成する。Standard以下、または当該列が欠損の場合は日足open/high/low/closeから推測せず`BLOCKED_BY_DATA_CAPABILITY`とする。研究用Decision Engine E2Eで前日raw closeをreference proxyとして使う場合も、12:30価格ではないことをreportへ明記する。

### D052 — Corporate Actionの扱い

研究価格はproviderの`AdjO/AdjH/AdjL/AdjC/AdjVo`と`AdjFactor`を使い、raw取引参照価格と分離する。`AdjFactor != 1`からeffective-date action lineageを生成し、payload hash由来のadjustment versionを保持する。daily endpointが提供しないannouncement時刻・action種別は推測せず欠損理由を残す。将来行の変更が過去特徴へ影響しないこと、分割時もadjusted系列が連続することを回帰testにする。

### D053 — PIT market / sector context coverage

Breadthと業種returnはcandidate集合ではなく、D050の営業日別PIT universe全体から計算する。eligible / observed issue数とcoverage ratioを保存し、既定95%未満の業種returnは欠損にする。閾値は実験設定としてversion化できるが、欠損銘柄を0 returnとして補完しない。売買停止等でsymbolの営業日観測が途切れた場合、technical rolling windowをそのgapでresetする。

## 暫定デフォルト

以下は現在の仮置きで、実験・設定により変更可能。

- 東証プライム普通株
- 最大10銘柄
- 1銘柄10%
- 1業種30%
- 最低現金10%
- 現物買いのみ
- 100株単位
- 1日 / 5日 / 20日予測
- 12:30を主対象
- J-Quants V2を日次公式データの初期アダプターにする

## 未決事項

### Q001 — 投資対象

- 東証プライムのみ
- 東証全普通株
- 流動性上位N銘柄

初期実験の対象を最終確定していない。

### Q002 — 日次候補数

前場監視へ渡す新規候補数。例: 30 / 50 / 100。

### Q003 — 前場ライブデータ源

J-Quantsの契約範囲、別の市場データ、証券ツール等から選ぶ必要がある。

SBIを注文先にしても、データ提供元は別でよい。

### Q004 — J-Quants契約プラン

履歴年数、前場・分足、財務詳細、TDnetの利用可能範囲。

### Q005 — 初期資金と口座構成

- 利用可能資金
- NISA / 特定口座
- 源泉徴収方式
- 現在保有
- 年内確定損益
- 損失繰越

実運用開始時に必要。

### Q006 — 制約値

- 最大保有銘柄数
- 1銘柄上限
- 1業種上限
- 最低現金
- 最大Turnover
- 日次提案金額上限
- 流動性上限

### Q007 — 税ルールの精度

簡易推定、年内損益通算、繰越損失、NISA枠の機会費用をどこまで初期版へ含めるか。

### Q008 — NISAで売る口座選択

同一銘柄をNISAと課税口座で持つ場合に、どちらをREDUCE / SELLするかのユーザー方針。

### Q009 — 予測期間の統合

1日 / 5日 / 20日の重みを手動・OOF学習・市場状態別のどれで決めるか。

### Q010 — コスト推定

Spread / Slippage / Market Impactを、最初は保守的固定値、流動性モデル、実約定学習のどれで始めるか。

### Q011 — 通知

- PWA
- メール
- LINE等
- OS通知

### Q012 — 実行環境

- 常時稼働Windows PC
- クラウド
- Windows + クラウド分離

### Q013 — リモートアクセス

PWAを自宅LAN、VPN、認証付きクラウドのどれで公開するか。

### Q014 — CSV形式

SBI等の保有・約定CSVの実ファイルを取得後にマッピングを確定する。

### Q015 — 提案のユーザー承認記録

ユーザーが提案を採用・一部採用・不採用にした理由を学習・検証へ使うか。

### Q016 — 12:30固定

12:30を主対象にするが、9:00 / 15:30と比較した結果で変更可能にするか。現状は比較実験を残す。

### Q017 — テクニカル実装ライブラリ（Goal 1方針確定）

Goal 1はD035のとおりNumPy / pandas実装とする。Goal 2以降にTA-Lib等を比較採用するかは未決。

### Q018 — V1 Coreの最終有効列

V1 Coreは約40〜60特徴を目安にするが、同じ指標の生値・順位・傾きのどれを初期有効化するかはM3の設計時にmanifestへ固定する。

### Q019 — 需給・市場Breadthのデータ源

信用、空売り、投資部門別売買、52週高安銘柄数、前場同時刻出来高履歴等の提供元と履歴範囲。

## 変更記録

### 2026-08-22

- 自動売買から意思決定支援へ変更
- BUY / HOLD / REDUCE / SELL / SKIPへ変更
- M14をDaily Portfolio Decision Engineへ変更
- 株数中心、100株単位へ変更
- 取引コストと税・口座区分を中核へ追加
- HOLD反実仮想と全体最適化を追加
- MD正本 + 段階別Goal方針を追加
- モバイルPWAの正式UI仕様と参考画像を追加
- AI提案・ユーザー判断・実約定・Paper結果のUI分離を確定
- 一般的なテクニカル・財務・需給・市場・前場指標を候補プールへ追加
- FeatureSet V0 / V1 / V2 / V3の段階導入を追加
- Feature Family Ablation、Feature Registry、数値fixture、fold内選択ルールを追加

### 2026-08-24

- Goal 1の最新指示に合わせ、BaselineをMomentum / Ridgeへ限定
- FeatureSet V0 / V1 Coreの初期manifestを58特徴で固定（cross後経過日数を含む）
- Goal 1のテクニカル実装をNumPy / pandas + 既知値testに決定
- 離散optimizerの上限超過をfail closedに決定
- Goal 1 Tax Engineの推定範囲を固定
- label availability、cross-sectional Rank IC、locked holdoutを追加
- sector / breadthをcandidate subsetから分離した明示入力へ変更
- 税の経済効果、NISA機会費用、源泉徴収cash effectを分離
- Goal 2AをJ-Quants V2専用・環境変数認証・immutable Parquet + DuckDBに固定
- 初回取得以前へprovider訂正値を遡及させず、`available_at = received_at`に固定
- 同一payloadのidempotent再取得、後日訂正の別version、atomic publishを固定
- plan / data capability不足を推測値で補わず明示状態に固定

### D054 — Historical revision policyをartifactへ固定する

J-Quants V2の初回backfillは、初回取得以前に存在した訂正vintageを復元できない。したがってProduction artifactは
`SINGLE_VINTAGE_AS_REVISED`または`STRICT_AS_KNOWN`を必ず記録する。前者は再現可能なas-revised研究に限り、
`historical_revision_status = PARTIAL`かつ`adoption_eligible = false`とする。後者ではsource receipt時刻を
effective availabilityへ含め、復元不能なhistorical labelを`BLOCKED_BY_REVISION_HISTORY`とする。どちらも完全な
correction-PITであるとは表示しない。

### D055 — Production targetは11:30より後に開始し、holdout境界でpurgeする

日足proxy targetのentryはfeature `as_of`と同じ営業日の引け、exitは固定JPX calendar上の1 / 5 / 20営業日後とする。
前日引けから11:30までに実現済みのreturnをtargetへ含めない。locked final holdout開始日以後にlabel endが入る行は、
feature日がholdout前でもdevelopmentから除外する。12:30 exact labelは行単位のentry/end/available_at/statusを持つ場合だけ
利用し、Standard planでは推測しない。

### D056 — Production buildはstaged featureとdatasetのatomic publication markerで完成とする

V0、V1 Core、V2 Extended、Production Datasetはそれぞれcontent-addressed directoryとしてatomic publishし、全snapshotの検証後に
Production Build Manifestを最後にatomic publishする。各snapshotは列名・dtype・値・source frame ID・manifest hashをidentityへ
含める。`data verify`はDuckDB catalog、immutable object、Bulk checkpoint、feature/dataset snapshot、build manifestを相互照合し、
空store、orphan snapshot、partial build、改ざんを成功扱いしない。

### D057 — Goal 2の外部blockと次Goalの進行

API keyが現在processへ継承されていない、契約planに必要endpointがない、providerがrevision historyを提供しない等の外部制約は
`BLOCKED_BY_*`または`PARTIAL`としてSTATUSへ固定する。推測データで埋めず、Goal 2の独立して検証可能な実装と品質gateを完了後、
recoverable checkpointを作り、Goal 3以降の外部制約に依存しない作業を継続する。

### D058 — Goal 3の選択・tuning・stackingはdevelopment OOFだけで行う

LightGBM / XGBoost / CatBoost、回帰 / ranking / quantile / large-loss、feature family ablation、Optuna、ensemble weight、
uncertainty calibrationはpurged expanding developmentだけで比較する。各horizonの前半をhyperparameter tuning専用、後半を
outer model evaluation OOF専用にし、outer targetが自身のmodel parameter選択へ入らないようにする。outer OOFはさらに時系列順に
stacking weight fit、uncertainty calibration、reported metric / coverage評価の3区間へ分離し、各境界をlabel endpointでpurgeする。
Decision互換の逐次uncertainty更新は、予測as-ofより前にlabelが成熟したresidualだけを使う。locked final holdoutはGoal 3 report APIへrow indexを返さず、
model・parameter・feature・ensemble選択へ使用しない。Goal 3 reportはrevision statusにかかわらず`adoption_eligible = false`とし、
最終holdout評価とlive/full-scale acceptanceを別工程にする。

### D059 — benchmark-excess予測をabsolute returnとしてDecision Engineへ渡さない

TOPIX / sector / beta-residual targetはresearch metricとして比較できるが、cash・cost・taxと比較するDaily Portfolio Decision Engineの
期待return fieldへそのまま代入しない。Decision Engine互換OOF出力はabsolute-return modelだけから生成する。OOF ensembleは
日付内rank spaceで非負・総和1 stackingし、その不確実性もrank spaceとして明示する。絶対return幅へのcalibrationはlive OOSで
別途検証する。

### D060 — Goal 3は認証済みV2 buildと明示的resource boundを必須とする

advanced researchは任意のParquet pathを直接信用せず、V0/V1/V2/Datasetを含む認証済みProduction Build Manifestから開始する。
Buildはsource lineageだけでなく、共通のobservation as-of・revision policy/statusと、Datasetへ埋め込んだ各feature値のsnapshot一致を必須にする。
config全文、feature snapshot/definition hash、全Optuna trial、fold結果、選択期間境界、library versionをartifactへ保存する。
全trialがFAILした場合もtrial監査を例外へ保持し、失敗ExperimentRecordへ永続化する。
full JPXで一括materializeする推定OOF行数またはmodel fit数が明示上限を超える場合は、未測定のままOOMへ進まず
`BLOCKED_BY_RESOURCE_CAPABILITY`で停止し、horizon/model-family単位のcontent-addressed batchとして実行する。

### D061 — Goal 4 Morning AIはprovider-neutralな11:30 freezeと日次予測の残差更新にする

前場data providerはQ003のまま未決とし、providerを推測・自動選択しない。実装済みの
`IntradayMorningData`は、`symbol / timestamp / price / volume / trading_value / available_at /
provider / source_record_id`を必須とする。`volume`と`trading_value`は各bar区間値であり、累積値は
同一session内だけで計算する。09:00 / 09:05 / 09:15 / 09:30 / 10:00 / 11:00 / 11:30の
exact barをF13 Morning Coreに必須とし、欠損時に直前値、日足OHLCV、日次出来高から推測しない。
current holdingとdaily candidateのunionを監視universeとしてfreeze metadataへ固定し、現在保有の欠落を
`BLOCKED_BY_DATA_CAPABILITY`にする。

F13は時刻別return、TOPIX/sector relative、range/VWAP、realized volatility、同時刻volume/trading-value
progress、監視対象内rank、daily prior forecastを持つ。同時刻profileは当日を除く直前20sessionだけを使う。
F14 Morning Microstructureはquotes / order book / trade frequencyの各capabilityが明示的に存在する列だけを使い、
不足列を0や合成値で補わない。当日終値と11:30後の値をmorning featureへ入れない。

Morning modelは前日・当日朝にfreeze済みの1 / 5 / 20日daily forecastに対する残差を予測する。
no-update daily forecastを必須baselineにし、固定parameterのRidge / LightGBMと、明示的に有効化したsmall MLPを
purged expanding development OOFで比較する。各modelはOOSでbaselineを改善しなければ`REJECTED`にし、
development結果から自動Champion昇格しない。1D-CNN / TCN / GRU / small Transformerは同期固定間隔の
前場sequence履歴がない間`BLOCKED_BY_DATA_CAPABILITY`、small MLPも既定`DISABLED`とする。

Decision Engine互換の更新値は、対象11:30より前にlabel endを迎え、かつ実際の`label_available_at`も対象11:30より前の
OOF residualだけでdownside、large-loss、standard errorを較正し、daily予測とmorning revisionの両provenanceを
型付き`Prediction`へ残す。ActionはMorning modelが
直接出力せず、更新後Predictionを全保有・候補とともにDaily Portfolio Decision Engineへ渡して初めて決める。
Morning Datasetとrow-level OOF reportはschema・値・source record ID・feature manifest・hashを含む
content-addressed Parquet + JSON directoryとしてatomic publishし、再利用前に認証する。live provider未接続時は
fixtureへfallbackせず、CLI capabilityを`BLOCKED_BY_DATA_CAPABILITY`として表示する。

各sessionの`MorningFreezeMetadata`はprovider、全source snapshot / record ID、holding + candidate universeを持ち、
roleとcapability reportを含めてfeature builder、dataset identity、Prediction batch、research-only proposalまで伝播する。
label entryはexact 12:30、endはartifactに認証した固定JPX calendar上の1 / 5 / 20 session後だけとする。
labelはendpointだけで成熟扱いせず、各fold学習と
Decision較正の双方で`label_available_at < prediction.as_of`を要求する。F14はcapability組合せごとのmanifestを作り、
AVAILABLE宣言済みの11:30値が欠けた場合はblockする。

認証済みreport / Datasetからresearch-only modelを決定的に再fitし、履歴終了後のcurrent freezeをoutcomeなしで推論する
経路を許す。Prediction provenanceはreport / snapshot / selected family / seedから導出し、caller自由文字列を使わない。
この経路は実装検証用で、live OOS evidence・推論時間・承認済みmodel registryが揃うまで採用不可である。

### D062 — Morning labelとDecision freezeは時刻・内容まで認証する

Morning labelは`label_end_date`だけで成熟判定せず、timezone-awareな`label_end_at`を必須にする。
`label_end_at`は認証済みJPX calendarのend sessionと同じ日で、entryより後、かつ
`label_available_at >= label_end_at`でなければならない。過去の取引時間を一律の時刻で推測しない。

current inferenceのPrediction batchは、11:30 feature行全体のcontent hashと、symbol別のreference price / ADVを
不変証跡として持つ。Decision adapterは同じfeature行を再hashし、freeze roleと実Portfolio保有、価格・ADVを照合する。
Decision Engineもaudit価格・ADVと評価Candidateを照合し、research-only proposalへ証跡を保存する。
履歴OOF replayをcurrent proposal用adapterへ渡すこと、認証済みrefit factoryを迂回したmodel bundle生成、
内容identityが一致しないDataset snapshotのresearch/refit利用は拒否する。

### D063 — Goal 5はlocal append-only台帳を実状態の正本にする

Goal 5のAI提案、version付きユーザー判断、実約定、翌日Portfolio、通知、ランキング、Paper将来観測は
SQLite WALの別recordとして保存し、同一identityの異なる内容を拒否する。提案は通知より先にarchiveし、翌日状態は
保存済みユーザー判断ではなく実際のfillだけから生成する。PWA/APIは`127.0.0.1`だけで提供し、mutating APIは
明示的なmanual-record intentを要求する。broker login、注文送信・変更・取消APIは設けない。

各提案は、生成に使った`DecisionEngineConfig`全文をproposal ID / generated-atへ結びつけた不変
`DecisionPolicySnapshot`と必ず同時に保存する。proposal payload、archive時刻証跡、policy snapshotは一つの
SQLite transactionで公開し、いずれかが欠ける場合はproposalを成功・表示可能にしない。Settingsはこの認証済み
snapshotだけを表示し、未登録の制約値をdefaultや推測値で埋めない。

CSV取込は必ずpreview→差分確認→appendとし、既存recordを上書きしない。約定の逆売買、注文株数、累積超過、
判断前時刻をpreviewで照合し、判断前時刻は確認でも上書きできない。口座状態CSVは非ゼロ保有の
`POSITION` rowに加え、全account bucketの`CASH` rowとavailable / reserved cashを必須とし、
保有だけ更新して古い現金を温存することを禁止する。
実broker固有CSV mappingは代表file取得まで決め打ちしない。

Paperは同一営業日の最終archive済み提案に対し、content-addressed不変台帳へ先に登録したJPX calendar、
horizon session経路、aware endpoint、実label availability、archive後の観測時刻、proposal model versionを
照合した実将来値だけを不変追加する。calendarはproposal archiveより前に固定済みであること、proposal営業日から
ちょうど次の1 / 5 / 20 sessionであること、proposal archiveがlabel endpointより前であることを必須とする。
同一営業日・horizonは1観測に限定する。週次・月次return、cost/tax推定誤差、
Champion/Challenger絶対誤差、隣接する過去窓のdrift比を集計するが、最低観測数到達やdrift判定からmodelを自動昇格しない。
運用curveとcompound returnは非重複の1営業日Paper系列だけを使い、5日・20日overlap labelを独立PnLとして複利計算しない。
model誤差・drift・Challenger比較はactiveな同一version cohortだけで計算する。Challengerは最新観測から連続する
同一versionの比較だけを使い、version切替または欠測をまたいで過去比較を再利用せず、比較分母を表示する。
PWA service workerはstatic shellだけをcacheし、`/api/` responseや前日の提案をoffline cacheから再表示しない。

運用backupは新規pathへonline SQLite backupし、全content hash・status→same-day archive済みproposal参照を検証後、
atomic no-replaceで公開する。restoreはPWA/job停止後、明示的な
replacement確認、restore元のread-only検証、restore後の再検証を必須とする。live handlerやdata capability不足時は
jobを`BLOCKED_BY_DATA_CAPABILITY`で停止し、fixture・前日提案・推測dataへfallbackしない。
jobはhandler前にdurable `RUNNING`を記録し、成功確定時にも同じprocessが未失効lockを所有することを再照合する。
freshness/proposal lineageをblock・failure・成功stage reuseで保持し、stable logical-stage idempotency key、heartbeat、同一workflowの
upstream成功を必須とする。APIはDailyStatusが指す提案だけを表示・操作可能にし、Host / Originをlocalhostへ限定する。

### D064 — V2 Bulk日足は公式file-download調整式で研究系列を再構成する

2026-08-25の実取得で、`/equities/bars/daily` RESTは`AdjO / AdjH / AdjL / AdjC / AdjVo`を返す一方、
公式Bulk CSVは仕様どおり`O / H / L / C / Vo / AdjFactor`だけを返すことを確認した。Bulk rawは受信列をそのまま保存し、
存在しない調整値を日次slice内で推測しない。Production build時に固定済みsource vintageの全期間を銘柄別・日付降順に並べ、
公式file-download仕様に従って「現在行より新しい日付の`AdjFactor`の累積積」を価格へ乗算し、出来高を除算する。
`ExRT = 3`のrights issueは公式注意事項どおり出来高側の累積係数から除外する。

再構成methodと全入力系列hashを`adjustment_source / adjustment_version`へ固定する。RESTの調整OHLCVが5列すべて存在する行は
provider値を使い、5列の一部だけが存在するrowはfail closedする。この処理は`SINGLE_VINTAGE_AS_REVISED`の制約を解消せず、
完全なhistorical revision PITや採用可能性を意味しない。

### D065 — 全期間Calendar Bulkは要求scope別にcheckpointする

実取得した`/markets/calendar` Bulk fileは、Bulk Listの要求期間にかかわらず2008-01-01〜2027-12-31の全期間rowを返した。
Calendarだけは要求`start / end`をfile fingerprintのcheckpoint scopeへ含め、要求範囲内rowだけを日付sliceへ公開する。
同一scopeの再実行は全object完全性を確認してskipし、別scopeを誤って完了扱いしない。Calendar以外のdatasetが要求範囲外rowを
返した場合は従来どおりfail closedする。

Production buildはCalendar全体をmaster / daily prices / TOPIXの共通する連続coverageへ境界化し、境界内部でどれか1系統の
営業日が欠ければ日付を黙って落とさず`BLOCKED_BY_DATA_CAPABILITY`にする。

### D066 — ホスト版は本人限定の運用確認面とし、local実データ基盤を置き換えない

ユーザーのremote URL要望を受け、Goal 5 localhost PWAとは別に、ChatGPT sign-inとSites access policyで
所有者本人だけが利用するホスト版control roomを設ける。これは公開マルチユーザー投資助言サービスではなく、
実データ準備状況、安全停止理由、no-order境界を確認する補助面である。broker接続、注文送信、変更、取消は実装しない。

`JQUANTS_API_KEY`、`data/live`、Production Dataset、model artifact、実口座・NISA・税状態CSVはホスト版へ送信しない。
ホスト版D1が保存できるのは認証済みuser IDに紐づく安全境界の確認状態など、機密な市場・口座dataではない
最小の運用metadataに限る。実データ・model・提案の正本は引き続きlocal append-only台帳と認証済みartifactであり、
安全な同期contractを別途承認・実装するまでホスト版は提案を生成せず、前日提案やfixtureを表示しない。

Sites deploymentはowner-only accessを既定とする。Internet公開、workspace全体共有、外部viewer追加は
別の明示承認なしに行わない。localhost FastAPIをreverse proxyでInternetへ公開せず、ホスト版workerから
local serviceへ到達させるための推測tunnelや代替APIも採用しない。

### D067 — ホスト版の安全状態画面はpublic閲覧を許可する

2026-08-29のユーザー明示指示により、D066のowner-only access既定をホスト版の閲覧に限って変更する。
安全停止理由、実データ準備状況、no-order境界だけをpublic表示し、本人別の安全境界確認状態を保存する操作は
ChatGPT sign-inを必須とする。public visitorには提案、Portfolio、口座、NISA・税状態、実約定、model artifact、
J-Quants取得内容やcredentialを返さない。

この変更はlocalhost実運用PWA/APIの公開を許可しない。localhost service、append-only台帳、`data/live`、
Production Datasetは従来どおりInternetへ公開・同期しない。Sitesへのpublic deploymentは、この限定画面の
検証済みversionだけに適用する。

### D068 — 実口座状態は手入力を初期運用の正本とし、SBI CSVを必須にしない

2026-08-29のユーザー明示指示により、現在保有、account bucket（NISA / 特定口座等）、利用可能現金、
reserved cash、取得単価、税・NISA入力はlocal運用PWAでのユーザー手入力を初期運用の正本とする。
SBI等の実口座CSV提供・broker固有mappingは、モデル研究、Production Dataset生成、Champion候補選定、
Paper運用開始の必須条件にしない。

既存のCSV preview / reconciliation機能は任意の将来入力手段として残す。手入力でも未提供項目をfixtureや
推測値で補完せず、実提案生成時は必要な口座・現金・税入力の完全性を従来どおりfail closedで検証する。
この決定はbroker login、注文送信・変更・取消を許可しない。

### D069 — Production artifact identityは論理値をhashし、検証はメモリ境界付きで行う

実データでは固定オフセット日時がParquet往復で`ns / UTC+09:00`から`us / pytz.FixedOffset`へ変わり、
同一時刻でもpandasの物理dtype依存hashが変わることを確認した。Production feature / Datasetのcontent identityは、
aware datetimeをUTC nanosecond、naive datetime / timedeltaをnanosecond、floatをfloat64かつNaN・signed zero正規化、
nullable integer / boolean / stringを明示logical型へ正規化してから列順・行順込みでhashする。
Parquet file SHA-256とmetadata hashも従来どおり必須とし、logical content hashの代替にしない。

405万行規模で全feature列を一括copyしたり、V0 / V1 / V2 / Datasetを同時loadして検証してはならない。
無限値cleaningは1列ずつ行い、Build Manifestは各snapshotを順次content認証した後、Datasetとのkey一致とfeature値一致を
最大8列ずつ比較する。resource不足時に行削減や近似比較へfallbackせずfail closedする。

### D070 — Goal 3実データ研究は認証付き再開マニフェストで小分け実行する

full JPXのadvanced researchは、`horizon × model family`を最小保存単位にする。各batchは独立subprocessで実行し、
成功時だけ既存のcontent-addressed report / OOF bundleとappend-only Experiment Registryを公開する。campaign側は
plan identity、config hash、feature name hash、attempt、child PID、log、report identityを小さなatomic manifestへ保存する。再開時は
manifestの`SUCCEEDED`表示だけを信用せず、OOF Parquet、metadata hash、report identity、config hash、feature名、commitを再認証する。
親processがartifact公開後かつmanifest更新前に停止した場合はreport rootから同一configを再発見し、未完了batchだけを
再実行する。生存中childの重複起動は拒否し、停止済み`RUNNING`は`INTERRUPTED`へ移す。研究childから不要な
`JQUANTS_API_KEY`環境変数を除去し、command、manifest、logへも渡さない。

campaign親はcontent-addressed Build marker自体のidentity / metadata hashだけを軽量認証して、resume manifestを即時公開する。
各batch childは開始時に従来どおり全feature / Dataset Parquet内容まで完全認証する。これにより長い事前認証中の親停止でも
campaignの現在地を失わず、Parquet完全性を省略しない。

### D071 — Goal 3のfold前処理はfloat32でメモリ境界を固定する

full JPXの5日LightGBM実runでは、2,826,087行 × 77特徴のfoldを前処理する際、既存frameに加えて
`float64`全列copyを作成しようとして1.62 GiBの連続領域確保に失敗した。行・期間・特徴を削減するfallbackは行わず、
有限値正規化は事前確保した`float32`行列へ1列ずつ変換し、training foldだけから求めるclip境界と中央値も
`float32`へ固定する。clip / fill / 不採用列dropは同じ行列上で行い、不要なwide `float64`中間copyを作らない。

この変更はfeature定義、target、fold境界、purge / embargo、Optuna範囲、model family、locked holdout境界を変えない。
ただし数値表現は研究codeの一部なので、新しいcode commitとcampaign identityで追跡し、旧codeの成功reportを
新campaignの成功batchとして偽装しない。OOMを含む失敗experimentと完了済みtrial / fold監査は削除しない。

### D072 — 長時間研究はCodex非依存runnerへ委譲し、状態照会を要求時だけ行う

長時間のGoal 3研究はWindows Task Schedulerから起動するlocal runnerへ委譲し、Codex processや会話sessionの
存続へ依存させない。runnerは認証済みcampaign manifestを唯一の再開入口とし、未完了batchを順に実行する。
同じmanifestに対する排他lockとTask Schedulerの`IgnoreNew`を併用し、生存中workerの重複起動を禁止する。
保存状態が`RUNNING`でも、記録PID・process名・開始時刻が一致するworkerが存在しない場合だけatomicに
`INTERRUPTED`へ遷移して再開する。Windows再起動後はlogon triggerと`StartWhenAvailable`から同じ入口を使う。

runner開始前にcampaign / Production Build identityを認証し、model source・dependency lockがcampaignの
code commitと異なる場合、または未追跡sourceが存在する場合はfail closedする。各研究batchは従来どおり
Dataset / feature / Build / config / commitを完全認証してから計算し、成功済みcontent-addressed reportと
Experiment Registryを再認証してskipする。研究workerへ`JQUANTS_API_KEY`を継承せず、locked holdout評価は
development campaignと別の明示入口まで禁止する。

進捗確認は`runner/research-runner.ps1 -Action status`をread-only入口とし、Codexによる周期的PID / CPU監視は
行わない。statusは保存状態とworker identityから求めたeffective状態を表示するだけでmanifestを書き換えない。
fold / Optuna trial単位の永続再利用は、動作中batchのsourceを変更せずに移行できる境界で追加する。それまでは
D070の`horizon × model family`成功artifactを最小再利用単位とし、既存1日model成果物と失敗監査を削除しない。

### D073 — 新規Goal 3 campaignはseed / fold / Optuna trialを認証付きで永続化する

D072の独立campaign完了後に開始する新規研究は`research-campaign-manifest-v2`を使い、batchを
`model family × horizon × seed`へ分割する。各batch内のwalk-forward foldは、Production Dataset ID、
Feature snapshot / manifest hash、順序付きfeature名、研究code commit、config全文/hash、target、model task、
parameter、seed、fold番号、train / validation index hashと期間を一つのidentityへ固定する。成功foldだけを
content-addressed Parquet + metadataとしてatomic publishし、Parquet / logical frame / metadata hashをすべて
再認証できた場合だけ再利用する。成功表示に対応するartifact欠損・改ざん・identity不一致は再計算で隠さず
fail closedする。

fold開始前に小さなatomic progress manifestへ`RUNNING`を記録し、同じcheckpointのOS排他lockを新workerが
取得した時に残存`RUNNING`を`INTERRUPTED`へ移す。成功artifact公開後かつprogress更新前の停止は、artifactを
再認証して`SUCCEEDED`へ回復する。progress照会はread-only commandとし、workerを起動・停止しない。

Optuna studyは同じcheckpoint namespaceのSQLiteへ永続化し、study user attributesにdataset / feature / code /
config / horizon / family / seed identityを固定する。再開時は完了済み`COMPLETE / PRUNED / FAIL` trialを再試行せず、
残trial数と累積実行時間だけを元のtrial / timeout上限内で実行する。停止時に残った`RUNNING` trialは、外側の
single-worker lock取得後だけ`FAIL`へ遷移する。SQLite破損、study provenance欠落・不一致は新studyへ黙って
fallbackせず停止する。development checkpointはlocked holdout rowを含まず、holdout評価入口とは分離する。

### D074 — Development選択を完全固定してからlocked holdoutを一つのledgerで単回評価する

Goal 3のfeature familyはablation campaignのtuning期間だけを用いたseed voteで決め、選択featureによる
final-candidate campaignを別に完走する。LightGBM / XGBoost / CatBoost、1 / 5 / 20日、3 seed以上、
regression / ranking / quantile / large-lossの全証跡を認証し、model、feature、hyperparameter、ensemble weight、
uncertaintyの選択をpurged development OOFだけで完了したcontent-addressed selection artifactへ固定する。
このartifactは`locked_holdout_accessed=false`かつ`adoption_eligible=false`であり、不完全matrixやsnapshot / Build /
feature / code identityの不一致を拒否する。

locked holdoutはselection directoryへ追加する一つの`holdout-access.json`で、selection、Build、Dataset、
evaluator commit、唯一のledger pathをholdout読込前に結び付ける。別root、別commit、別Buildによる再評価は拒否し、
中断後は同じledger内のmodel component単位prediction-only checkpointから再開する。prediction artifactにtargetを
保存せず、成功済みcomponentは再fitしない。最終reportとExperiment Registryには固定済みfeature hash、component /
ensemble結果、単回accessを残すが、holdout後のtuning・再選択・自動採用には使わない。

単回評価も長時間化し得るため、全development選択の固定後に限って専用Task Scheduler runnerを明示登録できる。
runnerはevaluator source / dependency lockとcommitを照合し、API keyを継承せず、Windows再起動後も同じledgerだけを
resumeする。status入口はread-onlyであり、broker発注や自動売買を行わない。

実データOOFのensemble整列では、各candidate bundleを最初の選択取込時に全logical-frame hashまで順次認証する。
二回目の整列passは同じParquetのbyte hashとreport identityを読込前後に再認証した上で、regression / rankingに必要な
6列だけをpredicate付きで読む。quantile / large-loss rowを同時に再materializeせず、行削減や未認証sampleへのfallbackも
行わない。

### D075 — Feature voteとfinal-candidate研究の間に不変artifactを置く

実データのproduction順序を、`ablation完了 → tuning-only feature vote固定 → final-candidate campaign → 全development選択固定`
の二段階にする。feature voteはhorizon別のexact feature列、F1〜F12のseed vote、Production Build、Dataset / Feature snapshot、
manifest、source report / campaign / code、holdout境界をcontent-addressed artifactへ保存し、`locked_holdout_accessed=false`とする。
final-candidate入口はこのartifactと同じBuild / holdout境界だけを受け入れ、LightGBM / XGBoost / CatBoost、1 / 5 / 20日、
3 seed以上をhorizon別v2 campaignとして実行する。

candidate runnerはCodexから独立し、horizonを順に進め、各campaign内ではmodel / seedを順に進める。foldとOptuna trialは
D073の認証済みcheckpointだけを再利用する。statusはfeature selectionに属する全horizon manifestを一度だけreadし、
保存状態、worker実効状態、horizon / model / seed、activeまたは最新foldを返すだけで、manifest・worker・holdoutを変更しない。
現行legacy campaignへこのsourceを途中適用せず、安全な完了境界後に新方式へ切り替える。

### D076 — Windows worker生存判定はALIVE / DEAD / UNKNOWNの三状態にする

Windows runnerはPythonのPOSIX式`os.kill(pid, 0)`をprocess生存確認に使わない。Windows PowerShellの
`Get-Process -Id ... -ErrorAction Stop`でPIDを照会し、Python process名とmanifestへ保存した開始時刻を
120秒以内で照合する。一致すれば`ALIVE`、PID不存在またはprocess名・開始時刻の明確な不一致は`DEAD`、
`WinError 87`、`AccessDenied`、開始時刻取得失敗、予期しない照会例外は`UNKNOWN`とする。

保存状態`RUNNING`を`INTERRUPTED`へ変更できるのは`DEAD`の場合だけとする。`UNKNOWN`ではstatusを成功終了して
read-only表示し、runnerの自動復旧はmanifest変更・worker再起動・次batch起動を行わず安全側で終了する。
これにより確認不能を死亡と誤認して同一workerを重複起動しない。PID再利用はprocess名だけで判断せず、開始時刻の
不一致で明確に拒否する。動作中Ablation campaignのsource provenanceを維持するため、この修正はrunner / test / docsに
限定し、model source、研究config、seed、feature、artifact、locked holdoutは変更しない。

### D077 — 1日modelはdevelopment軽量screenを通過した場合だけfull研究へ戻す

Goal 3の計算資源は、現時点のdevelopment baselineで相対的に強い5日・20日へ優先配分する。20日は中期の主alpha、
5日は短期補助alphaとし、1日は売買タイミング・短期リスクの補助Challengerとする。現在実行中の
`h1-lightgbm-s17`は停止・再起動せず完了させ、そのartifact、checkpoint、Experiment Registryを保持する。
方針のruntime反映は安全なbatch境界だけで行い、稼働中manifestを書き換えない。

1日のF1〜F12 full Feature Ablationは一旦行わない。既存のseed 17 development reportを再利用し、まずXGBoost / CatBoostの
seed 29 / 43だけを同一研究境界で追加する。LightGBM seed 17は保存するが、LightGBMの追加seedはscreen前に優先しない。
5日・20日は当初計画どおりLightGBM / XGBoost / CatBoost × seed 17 / 29 / 43のfull ablationを継続する。

1日をfull ablation / Final Candidateへ戻すには、同一のpurged development OOFだけで次の全gateを満たす必要がある。

1. XGBoostまたはCatBoostの少なくとも一方で、seed 17 / 29 / 43すべての主要OOF方向が正、かつ各seedでouter foldの60%以上が同方向。
2. 5日・20日の固定OOFそれぞれとの日付内Spearman相関の絶対値が0.95未満で、両者へcross-sectional線形射影した1日予測残差のRank ICが正。
3. 5日＋20日へ1日を追加した非負・総和1 OOF stackingが、同じ未接触meta-evaluation期間の主要scoreを厳密に改善。
4. 既存realistic cost控除後のDecision Engine objectiveが厳密に改善し、10 / 20 / 30 / 50 bps stressの全てで増分が非負。
5. OOS turnover、downside quantile、large-loss rateが5日＋20日構成より悪化しない。

不足値を0や推測値で埋めず、一つでも不成立または評価不能ならscreenは不合格とする。不合格なら1日をFinal Candidateから除外し、
以後の計算資源を5日・20日に集中する。合格しても1日は主alphaへ自動昇格させず、補助寄与としてのみ評価する。
この判定は1日の新しい複数seed結果を見る前に固定し、locked holdoutを一切使わない。

### D078 — Full Ablation前に比較可能なmulti-seed screenを置く

計算削減の目的は研究期間の短縮ではなく、認証済み計算の再利用と見込みの薄い追加探索の停止である。1日・5日・20日の
full Feature Ablation前に、同一Dataset、feature列、walk-forward split、preprocessing、objective、estimator / tuning設定で
seedだけを変えた最低3 seedのdevelopment OOF軽量screenを置く。screenではF1〜F12 ablation、大規模追加Optuna、SHAP全量を
実行しないが、multiple seeds、全walk-forward fold、cost / turnover / downside評価は削らない。

既存report、OOF、fold、Optuna trial、checkpointは全identityを認証できる場合だけ再利用する。code commit、split、feature、
parameterが異なる成果物は削除せず補助evidenceとして残すが、seedだけの安定性比較へ混ぜない。比較可能なseedが不足する場合は、
同じ軽量screen設定で不足seedだけを追加する。結果を見た後にこの互換条件を緩めない。

5日・20日のLightGBM / XGBoost / CatBoostをseed 17の順位だけで除外しない。追加の重い探索を停止できるfamilyは、
対象objectiveでpaired block-bootstrap 95%信頼区間が劣位かつseed × foldの80%以上で劣位、cross-fitted非負ensembleの
全split weightが0でscore改善なし、regression / ranking / quantile / large-lossの全役割で改善なし、さらにrealistic cost後の
Decision Engine objective改善がなくturnover / downside / large-lossにも追加価値なし、をすべて満たすものだけとする。

一条件でも不明・不成立なら`SCREEN_HOLD`、全条件成立時だけ`SCREEN_REJECTED`とする。削減family数の目標は置かず、
screen通過または保留のhorizon × familyだけfull ablationへ進める。Ablation後のFinal Candidateではhorizon、family、objective、
feature、parameter、downside / large-loss、ensemble weight、uncertaintyをdevelopment OOFだけで固定し、Rank IC単独ではなく
NDCG、seed / fold安定性、cost後改善、turnover、downside、ensemble追加価値を合わせて判断する。

計算削減の優先順は、認証済み成果物再利用、重複計算排除、screen不要探索の省略、明確な劣位familyの追加探索停止、
通過候補だけのFinal Candidateとする。locked holdoutは全選択固定まで開かない。

### D079 — seed 17後のscreen campaignを別Task Scheduler runnerへ予約する

稼働中の`h1-lightgbm-s17`を停止・再起動せず、既存research runner lockが解放されるまで計算を始めない
`goal3-phase-runner`を別Task Scheduler taskとして予約する。現在taskの定義・process・workerは変更しない。
安全境界後は1日XGBoost / CatBoostの比較可能なseed 17 / 29 / 43 lightweight screenを先に実行し、続いて
5日・20日のLightGBM / XGBoost / CatBoost × seed 17 / 29 / 43 screenを実行する。

screen設定は結果を見る前に、FeatureSet V2全列、3 Optuna trial、累積900秒、50 estimator、500 session initial train、
60 session validation / step、120 session locked holdout境界、`run_ablations=false`、`run_diagnostics=false`へ固定する。
report探索rootは既存認証済み成果物と共通にし、config / code / seedを含む完全identityが一致するartifactだけを再利用する。
一致しないseed 17は削除せず補助evidenceとして保持し、比較可能性確保に必要なlightweight seed 17だけを再計算する。

phase runnerはAPI keyを研究childへ渡さず、locked holdout評価を呼ばない。Codexの周期監視は行わない。
ユーザーが「進捗」と求めた場合は`goal3-phase-runner.ps1 -Action status`を一度だけ実行し、現在phaseとactive campaignの
horizon / family / seed / foldをread-only表示できる状態を維持する。screen完了後は`SCREEN_EVALUATION_READY`で、
D077 / D078の事前固定ruleによるdevelopment-only判定へ引き渡す。

### D081 — 20日研究のcausal期間不足修正と新campaignへの安全移行（2026-09-20）

20日Full Ablation v1は学習前にtuning期間579日／必要580日の検証で停止し、同一条件の再試行を10回行っていた。
性能結果を見る前に、従来の境界（60%または最小学習長の大きい方）を下限として、実際のtrading_dateとlabel_endだけから
必要なdistinct tuning日数を確保できる最初の境界まで進める、と固定する。label_end < outer開始を厳守し、
outerにも最低60日を要求する。不足なら引き続きBLOCKED_BY_VALIDATION。target値・モデル成績で境界を選ばない。
500日initial train、60日validation/step、120日holdout、3 family × seed17/29/43、20 trial/900秒、300 estimatorを変更しない。

完了済み1日・5日は元commit/config/report/OOFの認証だけ行い再学習しない。修正版20日はv2の別manifest/checkpoint/logを使い、
修正commitを固定する。旧v1失敗記録、全既存成果物とRegistryを保持し、古いcheckpointを新commitへ付け替えない。
異commitのhorizon成果物は同一条件のseed比較へ混ぜない。将来のfeature freeze/Final Candidateで必要なprovenance対応は
別途監査し、現行の不一致拒否を緩めない。

新workerの決定的BLOCKED_BY_VALIDATIONは固定markerを保存し、同じcampaignを自動再学習しない。
Windows再起動後の通常resumeと、ユーザー要求時1回のread-only status入口は維持する。
locked holdoutの評価・特徴量/ラベル定義・採否基準・実注文機能には触れない。

### D080 — 実測時間を踏まえ5日・20日はscreenを省略してFull Ablationへ直行する

1日lightweight screenの実測が1 batchあたり数時間となり、5日・20日は既存seed 17 development OOFで
LightGBM / XGBoost / CatBoostの各familyに少なくとも一つの役割上の有用性が確認されているため、D078 / D079のうち
5日・20日を事前screenへ通す部分を廃止する。これは結果を見ながらmodelを削る変更ではなく、重複計算を除きながら
3 family × seed 17 / 29 / 43のFull F1〜F12 Ablationを維持する変更である。

現在進行中の1日XGBoost / CatBoost × seed 17 / 29 / 43 screenは停止・再起動せず完走する。1日の判定にはD077で
事前固定済みの全gateをそのまま使用し、欠損・評価不能をpassへ補完しない。判定artifactはscreen campaign ID、
Production Build ID、code commit、全screen report ID、各gateの真偽、`locked_holdout_accessed=false`を固定し、
全gate成立時だけ`KEEP_FOR_FULL_ABLATION`、それ以外は`EXCLUDE_FROM_FULL_ABLATION_AND_FINAL`とする。

判定後は5日Full Ablation、20日Full Ablationの順で全3 family × 3 seedを実行する。1日を残した場合の1日Full Ablationは
この2 horizon完了後、特徴量固定前に実行する。Full Ablation後にだけ、複数seed / foldの一貫した劣位、ensemble追加価値なし、
regression / ranking / quantile / large-lossの全役割で価値なし、realistic cost / turnover / downsideでも追加価値なし、の
全条件が確認できたfamilyをFinal Candidateから除外できる。一条件でも不明なら保持し、削減数目標は置かない。

旧phase runnerがprocess内に保持するD079遷移は、現在の1日workerを変更せず、旧5日・20日screen manifest pathを
directory型fail-closed latchにすることで1日完了境界後の新規core-screenだけを阻止する。更新runnerは1日判定artifactが
存在しない間`ONE_DAY_EVALUATION_READY`で正常終了し、認証済み判定後だけ5日・20日Full Ablationへ進む。
locked holdoutは全選択固定まで開かず、認証可能なreport / OOF / fold / Optuna trial / checkpointを再利用する。

### D082 — 学習と独立したPWAの簡素化・タブ整理（2026-09-24）

ユーザーの「今のうちにUIだけ」「タブで整理」「細かい説明を減らしてシンプルに」に従い、
実操作画面である`web/`だけを改善する。`hosted/`の公開readiness companionの改修・配信は今回の対象外。
研究source、runner、worker、seed、採否基準、checkpoint、Experiment Registry、locked holdoutには触れず、
学習statusの監視・再起動も行わない。

- 固定5ナビは維持。設定は「口座・資金 / AI・データ / 通知」に分ける。ランキング・検証も同じタブ部品を使い、矢印/Home/Endキーと関連panelのARIAを揃える。
- Todayでは株数の変更とAPI由来の推定現金を主役にする。口座別現金・推定改善・モデル版は折りたたみ、情報そのものは失わない。
- 「提案を見る → 判断を保存 → 結果を記録」は現在ページの案内であり、未確認の保存済み状態を意味しない。
- UI_SPECに沿って白・薄灰・青を基調とし、グラデーション・過剰な影を除去。数値は等幅数字、主要操作は44px以上、360〜430pxとPC幅で確認する。
- 詳細説明は必要時に開く。fixture・未設定・stale・未観測・自動発注なし等の安全上の区別は省略しない。
- APIがstaleと明示した提案はTodayと直接review URLの両方で遮断する。Paper観測0件は成績0%に見せず未観測とする。時刻表示はJST固定。
- 既存API・100株判断・実約定記録の契約は変更しない。見た目のテストには既存の一時fixture DBのみを使い、実台帳・実データを補完しない。

### D083 — 更新したUIを既存の公開Sites companionへ反映（2026-09-24）

ユーザーの「sitesに公開して」を受け、D082のUI整理を`hosted/`へ移植し、既存の同一Sites projectへ公開する。
D067のpublic閲覧範囲、本人別の安全確認のみを保存する認証・D1、および既存のsocial previewは維持する。
ローカルPWA/FastAPIを公開・proxy化したり、口座台帳・実提案・model・J-Quants dataをアップロードしたりしない。
ホーム / 今日 / ランキング / 検証 / 設定を切り替えられるが、実データ接続がない欄は未接続、金額は`—`、
提案は`NO PROPOSAL`とする。古い固定の履歴取得期間や進捗表示を撤去し、現在の研究statusを取得・推測しない。

### D084 — 5日・20日のFeature voteを固定し、model familyは保留（2026-09-27）

D080の1日screen判定`EXCLUDE_FROM_FULL_ABLATION_AND_FINAL`を維持する。完了した5日・20日の
LightGBM / XGBoost / CatBoost × seed 17 / 29 / 43、計18件の認証済みFull Ablationだけで、
D075のstrictly-earlier tuning vote（各seedでmodel family過半数、3 seed中2以上）を適用する。
1日のFull Ablationを要求せずにfeature selectionを固定できるよう、5日・20日のみのartifactを認め、
除外判定の内容hashをartifactへ含める。従来の1日・5日・20日を含む完全matrixも引き続き認める。

- 5日: F2 MACD（3/3 seed）、F12 Candle / breakout（2/3 seed）を採用し、V0との和集合41特徴を固定。
- 20日: F6 Volatility / downside（3/3）、F7 Volume / money flow（3/3）、F10 Relative / market context（2/3）、F12 Candle / breakout（2/3）を採用し、V0との和集合51特徴を固定。
- 各feature familyの採否はtuning-period voteだけで決め、後続outer OOF・importance単独・locked holdoutでは変更しない。
- Model family削減はD080の全棄却条件を満たした場合だけ行う。今回の18件はrealistic cost評価がすべて`BLOCKED_BY_DATA_CAPABILITY`で、ensemble追加価値・各objective・turnover / downsideも全条件を満たす棄却証拠がない。このため5日・20日とも3 familyを`ABLATION_HOLD`とし、Final Candidateで比較する。削減数を目標にしない。
- Feature selection artifact `13c8676f84f24eaceaa2015395794cda0e1b2e249dfe5412640a31b6e8e9c81d`は18 source report、2 source commit、1日除外判定hash、Build / Dataset / Feature ID、holdout境界を固定し、`locked_holdout_accessed=false`である。これは特徴量の決定であり、Champion・ensemble weight・実運用採用の決定ではない。

### D085 — Final CandidateのWindows独立runner起動を修正（2026-09-27）

Task Schedulerの`powershell.exe -File`から`[bool]`parameterへ文字列`-RunDiagnostics:true`を渡すと、
Windows PowerShell 5.1がparameter bindingで終了コード1を返した。Task用CLI境界では値を`0 / 1`の
`[int]`として渡し、runner内で真偽へ解釈する。候補statusのPython JSONに日本語を含む絶対pathがあるため、
Windows PowerShellへ渡す前にASCII escapeして文字化けを避ける。Git実行ファイルはTaskのPATHにない場合、
既定のGit for Windows pathへfallbackし、source preflight失敗時は例外型だけをrunner logへ記録する。
model source、研究条件、seed、選択済み特徴量、locked holdoutは変更せず、既存workerを停止・再起動しない。


### D086 — Final Candidateのcopy ownershipを省メモリ化し、失敗時の自動再試行を一時保留（2026-10-02）

ユーザー承認の復旧作業で、candidate runnerの子Pythonだけにpandas 2.3.3の
`PANDAS_COPY_ON_WRITE=1`を設定する。既存snapshot認証のsort/reset-indexによる冗長な全件copyを
減らすためのruntime memory modeであり、float32化・特徴数削減・評価条件変更ではない。
RESOURCE_RUNTIME eventへ実際の設定を残す。OS環境や他アプリには設定しない。

- モデルsource/dependency、固定source pin、dataset/feature/config/checkpoint identityを保持する。
- 新copy modeでcheckpoint/advanced対象11 testとproduction対象4 testをpass。3種類のframeで
  production content hashが従来modeと一致し、保存済み11 outer foldも元の認証境界をpassした。
- これはcopy削減の検証であり、全campaignの収束・完了や十分なメモリの保証ではない。
  実データのattempt20は後続準備の2.64 GiB allocationに失敗したので復旧は未完了と記録する。
- 通常ブラウザなど他作業のprocessを勝手に終了せず、pagefile/OS設定や有料resourceも変更しない。
  元の失敗16:39 JSTと今回Solver再開19:07 JSTの時系列から、今回再開を元の失敗原因とはしない。
- 候補の自動再試行taskは一時Disabledとし、共有メモリ問題を解消してから単発resumeを確認する。
  完了artifact/checkpointは削除せず、モデルsourceや研究条件を変える案は別途比較・判断する。


### D087 — 前処理copyの局所パッチを隔離検証し、正式checkpoint互換を偽装しない（2026-10-03）

ユーザー承認の追加復旧調査で、同条件再起動を中止したまま初期3行フィルタの
`loc[mask].copy()`を列ごとのdtype-preserving array.takeへ置き換える未適用patchを作成する。
float64の低精度化、列削減、行/label/split/parameter変更を行わず、合成fixtureで値・hash・
OOF・評価指標・境界一致を検証する。大きな連続blockを分割しても総データ量と後続copyは残り、
実データ復旧・安全RAM・速度倍率・残日数を保証しない。

本体への適用でML source commitが変わるため、既存固定pinを名乗らせてcheckpointを流用しない。
今回本体src/runner/依存/campaign/checkpointは変更せず、検証overlayはworkspaceに保存する。
適用・11完了foldの新namespace再利用は、旧証拠を読み取り認証し、新split/入力/evidenceを照合した
import bridgeと旧新code・hashのreceiptを明示する別段階とする。元metadata/hashを編集して迂回しない。

外部CPU移行はdocs/CLOUD_CPU_PILOT.mdのdevelopment-only export manifest・path map・
import provenance・Linux/数値照合・J-Quants本人利用許諾を先に整える。多thread/GPUは別experiment。
公式価格は参考であり、外部upload、VM/契約/課金、holdout転送、学習起動の許可ではない。

### D088 — 値を保持する列単位fold copyと異なるcode_commit間の明示的import（2026-10-03）

承認済みの最小復旧に限定し、D087の初期行copyに加えてOOF/diagnosticsのfold copyを列単位へ変更した。
狭いtarget/date/symbol列で選択と安定sortを決めてから、全列を元dtypeで独立copyする。
データ、特徴量、精度、seed、モデルparameter、iterations、評価とholdoutは変更しない。
独立した旧実装との小規模OOF完全一致と、値/index/attrs/nullable/並び順/保存hashのparityで検証した。

ML source commitが変わるため、旧pinの偽装やmetadata/hash書換えによるresumeは認めない。
--checkpoint-import-planで指定した同一データ/config/特徴量順・CPU CatBoostの復旧だけを新namespaceへ受け入れる。
旧namespace/progress/foldは読取専用にし、split位置hash・日付境界・raw/effective parameter・byte/content hashを照合する。
新fold metadataは元foldの完全metadata、旧新identity、依存/runtime、passing fixture証拠、検証hashをlineageとしてatomic publishする。
Optunaの元DBはread-only backupを介し、trial内容/number/date/durationを再現して残りtrial/time budgetを維持する。
自動importは指定planがある時だけ動作し、不一致や改ざん、異なるdata/feature/thread/GPU、chained importを拒否する。
これは同一ローカルデータの復旧であり、development export/異OS/cloud pilotの互換性は別途必要である。

実データ15保存unitのevidence/OOF認証は01:39 JSTに成功したが、新namespaceへの実import・学習再開は未実施。
01:34 JSTの空き物理6.309 GiBに対し、初期数値buffer下限7.771 GiB、後段8.802 + 0.523 GiBで安全条件を満たさない。
下限には非float列/index/CatBoost内部などを含まない。必要RAMの確定や完了/残り時間は主張しない。
旧taskはDisabledを維持し、十分な資源と真正な新source pin/planを整えるまで起動しない。
旧h5 campaignの完成済み7 batchを新commitの結果へ黙って統合せず、採用は別途来歴付きで検証する。
外部転送、VM、課金、注文、プロセス終了、OS/pagefile変更、他アプリ変更は行わない。


### D089 — 全列認証後の入力投影と同値のファイル配列（2026-10-03）

承認済みの株式だけのローカル復旧として、全Parquetの物理hash・元logical IDとfeature/dataset整合を認証した後で必要列だけを露出する。元の90 float64列を常時保持しないが、除外列の内容も認証から除外しない。dtype・行・特徴量順・前処理・モデル条件・split・holdoutは保持する。

--memory-scratch-rootを明示した単独horizonのCLIに限り、所有する入力を独立development配列へ写した後に解放する。数値作業配列は同dtype/C-layoutのファイル配列へ置き、row-copyの書き込みをflushする。常駐しているmapped pageはRAMを消費する。拡張dtype/object/空配列は従来処理を保持し、生存viewを強制closeしない。失敗時の残存scratchはreceiptで識別する。

元94aab78系と新commitの同値比較、変更範囲のAST guard、同一lock/runtime、補助source hashをlineageへ結び、元namespace・FAILED記録・Optuna duration/budgetを保持する。実際の新namespace import/reloadと学習進捗は別の実測で報告する。保存済み7 batchのcommit/hashを書き換えたり、新しい結果へ混ぜて採用したりしない。

詳細・66/76/2件のpassing evidence・実全データ認証・合成native測定と制約はLOCAL_MEMORY_RECOVERY.mdに記録した。最大実foldのnative memory上限はまだ実証されていない。必要RAMの安全余裕を示せるまで大規模なOOM試行はせず、4 taskの一括再有効化はしない。Classic以外のアプリ、pagefile/OS、外部upload/VM/課金、holdout評価、注文は変更しない。

### D090 — モデル行列作成後の元配列解放とfit直前RAM条件（2026-10-03）

旧進捗15単位の真正なimport/reloadは09:59 JSTに成功した。新規学習完了とは区別する。元namespaceとcampaignは不変。続くsource変更は別の真正commit/namespaceで元94aab78成果から受け入れ、chained importや旧pinの偽装はしない。

予測に渡す前処理行列は変えず、作成後に不要な所有foldの元特徴量配列を解放する。--memory-scratch-rootと--minimum-fit-headroom-gib 3.5を明示する単独workerでは、native fit直前の実際の空きRAMが条件未満なら停止する。合成40k/80k/160k測定から既知fixture配列を引いた大きい増分を最大実foldへ換算し、固定0.1 GiBを足して2倍にしたnative保守推計約2.1 GiBに対し約1.4 GiBの余裕を残す。推計とhard上限保証は混同しない。

確認はfit境界の一回だけで、継続PID/CPU監視やOS/process hard capではない。設定不足の時はnative fitを始めず記録して停止し、無理なOOM試行や自動retryはしない。学習条件・CPU1・300反復・seed・評価・元成果を保持し、実起動/guard/最初のcheckpointを別に確認する。元task4本の一括再有効化、追加アプリ終了、新規認証/課金/外部送信/注文は行わない。


### D091 — one pandas feature block per owned numeric array view (2026-10-04)

For the explicitly authorized stock continuation, expose `_finite_numeric`'s unchanged float32 C-layout storage through separate column views. Preserve the FoldPreprocessor class and all model/split/evaluation definitions; independently verify statistics, feature retention, matrix values, OOF and report identity against archived a68 code. Require real code provenance and direct native-source imports for the original 15 units and newly completed ranking6. Do not chain previously imported folds, lower the 3.5 GiB fit guard, alter scientific parameters or infer fit safety from exit-time RAM. Production continuation remains conditional on the actual fit guard; never create an automatic restart loop or modify other apps/OS/provider/order state.


### D092 — one pressure-triggered unused Arrow pool diagnostic (2026-10-04)

For an explicitly guarded owned recovery run only, request one best-effort release_unused after gc/reap when fit headroom is insufficient. Record backend/live bytes and actual physical availability before/after; preserve live buffer bits/dtype and the 3.5 GiB guard. Cleanup error or insufficient after-RAM remains a pre-fit stop. No repeated trimming, automatic restart, other-app/OS action or guarantee from exit-time RAM. This is bounded resource debugging; verify unchanged native OOF and real live buffer preservation before use.


### D093 ? avoid ignored full OOF return with explicit part ownership (2026-10-04)

The recovery research caller may request parts-only collection when it already owns all emitted parts and does not consume the full return. Preserve prediction/identity validation, default return behavior, final research concat and every scientific definition. Verify against the independent archived native baseline; bind genuine source commit and native-source import proofs. Retain the 3.5 GiB guard. This is the final bounded attempt for the present continuation; insufficient actual guard headroom ends the attempt without automatic retries or further unrelated actions.


### D094 - adopt recovery through genuine pin-separated continuation campaigns (2026-10-04)

The user authorized verified seed29 research registration and only the unstarted seed43 of the same frozen plan. Preserve the original campaign bytes and failed history. The original94 manifest cannot truthfully authenticate the genuine8d recovery report. Existing development selection already accepts multiple strict v2 manifests and records their real source pins, so use a seven-success legacy94 view and a two-batch8d continuation with a hash-bound link to the original nine-batch plan. Reauthenticate all eight full report/OOF bundles, exact per-batch config/features/build, original16 bytes and native94-to-8d equivalence evidence before registration. Append a research_only linking experiment; never change old report pins or label the old7/9 manifest complete. No scientific source/schema/authentication changes are required.

The generic campaign checkpoint helper derives feature_manifest_hash from the current catalog (e7ac592d...), while the frozen production feature snapshot/report use83859eb6.... Derive actual recovery and fresh seed43 checkpoint IDs from the authenticated frozen snapshot provenance; record the actual paths explicitly. Do not modify either hash or claim the helper's nonexistent namespace is actual progress. The existing full report and selection authentication remain strict.

Fresh seed43 uses genuine8d, identical original config hash b5f608c4..., ordered41features, dtype, CPU1/300 iterations and3.5GiB fit guard. Its worker orchestration is separately hash-bound and archived, source/lock must match8d, single-attempt intent is exclusive, legacy tasks remain Disabled, and no seed29 learned units are imported. Verify actual firstfit before claiming native execution. Observe completion or safe stop without restarts, additional horizon/app/OS/account/billing/order actions. Registration is research evidence only; historical-vintage and locked-holdout/live-approval blockers remain.

### D095 — daily-first research and owner-private results (2026-10-15)

The user approved implementing the proposed Drive-informed plan: daily first, morning later; fixed seven-criterion manual research without new paid providers; PC computation and owner-private cloud results readable while the PC is off; manual owner adoption after authenticated holdout evidence, with no fixed sixty-day automatic promotion rule. Daily Prediction v2 retains only 5d/20d (1d is null); the daily decision policy is 0/0/1 with 20d risk. Original predictions and separate research are immutable, content-addressed records. JSON is canonical; CSV/Markdown use the same snapshot identity. Top20 plus all holdings are reviewed.

A separate private Sites project appgprj_6acfaa58a14c81919863e7e62f8a939c and private/ source were created. Existing hosted/ audience and implementation are unchanged. Only a bounded result projection is synced; raw data, model weights, account details and provider credentials stay local. Private deployment, idempotent insertion and exact-byte readback are required. No public fallback. Original campaign cost settings remain unchanged; new evaluation-policy scenarios are 10/20/30/50 bps. V04 SB20/SB60 confidence intervals reproduced miscalibration, so they are diagnostic only. Stateful daily NAV must precede economic adoption; overlapping forward20 labels cannot be added as daily returns.

This implementation does not complete all research gates: final selection, actual holdout evaluation, daily refit/live inference and authenticated adoption evidence remain unconnected. Store rejects adopt reviews until the actual evaluation evidence and personal execution settings are connected; record IDs alone are insufficient. See docs/DAILY_RUNBOOK.md and docs/evidence/daily-readiness-20261015.

### D096 — owner enters accounts and holdings in the private app (2026-10-15)

The user states they currently hold no shares and explicitly asks to enter account types and current holdings in the app. Add /portfolio to the existing owner-private Site. This updates D095's account-details-local-only scope: account labels/types, manually entered holdings and optional budget/risk preferences may now be stored in that owner's private cloud database. No account numbers, brokerage credentials, provider raw data or learned weights are collected. No holdings does not imply zero capital; missing amounts remain null. Do not seed production with fixture financial records.

Use preview-before-save, strict validation, owner-isolated append-only revisions and atomic stale-write rejection. The app input is available while the PC is off. Python portfolio import, execution settings and personalized comparison remain separate pending work; manual input alone cannot authorize model adoption or an order.

### D097 — research daily NAV accounting contract (2026-10-15)

Implement Drive v01 V18–V23 as a separate research ledger using explicit unadjusted prices, fixed session calendar and order decisions strictly before execution. No forward label aggregation, no writes to the manual execution ledger, no order submission. Daily-close proxy executions require the close time/price and remain labelled research proxies. Sells precede buys; same-side order IDs define priority; unknown tradability/capacity, invalid lots/ticks and unaffordable orders do not fill. Preserve account-isolated reserved cash, shared symbol capacity and explicit sale-buying-power release times. Unfilled day quantities expire; holdings persist.

Corporate actions require dated source declarations: split and fractional cash, dividend entitlement/receivable/payment, verified cash conversion. Unsupported fractional rights fail closed. Missing marks keep the holding, return null observed NAV and separate 0/50/100% haircut hypotheses. They never imply liquidation or zero return. Primary accounting is explicitly pre-tax; personal tax scenarios and authenticated market/action adapters are still required. Cash/HOLD comparison uses the identical initial portfolio. Fixed bps sensitivity is one-way all-in, charged once; it is not evidence of realistic costs. Details: docs/DAILY_NAV_EVALUATOR.md. No change to historical candidate configuration, source pins or holdout access.

### D098 — versioned development metric diagnostics (2026-10-15)

Fix the remaining V10/V11/V17 numerical conventions in daily-development-metrics-v1, separately from immutable historical reports. Ranking ties use symbol-ascending priority, IC requires at least three finite nonconstant rows, missing sections remain null and exclusions are counted. Preserve grade-based NDCG and top-K set-overlap Precision, explicitly not a positive-return hit rate. Probability Brier/ECE use original in-range probabilities; only log loss clips float64 at epsilon 1e-8. Retain historical clipped Brier reports unchanged. Quantiles preserve crossed predictions, report strict/inclusive coverage separately, and mark a single alpha as insufficient to check crossing. Diagnostics include source hashes and dependency versions.

The existing authenticated candidate audit gains an explicit --score-development option and a new v2 receipt. Authenticate original artifacts and frozen feature lineage before scoring development OOF; keep original report metrics alongside the new definitions. This does not select a model, open holdout, infer calibrated significance, adopt a model, or create an order. See docs/DAILY_EVALUATION_METRICS.md.

### D099 — causal daily OOF bridge to portfolio comparison (2026-10-15)

Add a separate 5d/20d research adapter with 1d null and 20d decision risk; preserve the legacy adapter and original reports. Authenticate the full dataset identity by logical hashing, then project only matching development label timestamps. Hashing protected source rows is source authentication, not holdout scoring. Rewritten file/metadata hashes must not bypass the frozen dataset identity.

Use one explicitly named family/seed pair for wiring verification, not as a selected winner. Risk scale is expanding 20d residual RMSE from strictly prior receipts and completed endpoint dates. Default minimum20 eligible feature dates is a versioned, configurable research cold-start guard, not evidence of calibrated uncertainty; the existing standard_error field carries an explicit RMSE warning. Keep missing horizons/history as named blocks. A missing held-symbol forecast stops the comparison. Compare explicit candidates plus every holding with known marks and the daily0/0/1 engine policy, preserving the input portfolio. No execution ledger writes, latest forecast claim, automatic selection or adoption. Stateful NAV integration and personal settings remain pending. See docs/DAILY_OOF_ADAPTER.md.

### D100 — stateful daily decisions over simulated fills (2026-10-15)

Connect daily0/0/1 research decisions to the existing NAV ledger. At each11:30 cutoff, apply only effective corporate actions and due settlements, then expose cash/positions/receivables to the decision callback without future execution/closing quotes. All current holdings join the explicit candidates. Missing forecasts, market/security/liquidity evidence, stale or pre-split unit prices, or the exact-search cap produce named blocked days, no orders and continued holdings. Any blocked decision marks the comparison incomplete. Actual simulated fills, not targets, drive the next day; retain all generated orders for fixed-order replay parity.

Receivables remain in NAV but outside deployable decision wealth until paid. Preserve account-bucket cash isolation. Initial integration uses explicitly synthetic pre-tax/no-withholding research account metadata, not the owner's account classification or NISA/tax settings. The same cost policy is estimated for decisions and charged once on actual fills. HOLD starts from the identical initial cash and holdings. Add DailyDecisionAudit and require research-only on daily proposals, correcting the generic engine's prior false default without weakening the morning lineage gate. No manual execution ledger writes or actual orders. Market/action authentication, realistic execution capability, personal tax, full baseline comparison and final selection/holdout remain necessary. See docs/DAILY_STATEFUL_STRATEGY.md.


### D101 — authenticated development daily-market projection (2026-10-15)

Read the bounded daily-price window through a read-only catalog transaction after authenticating the frozen feature selection and rejecting holdout dates. Reconcile successful eligible ingestion, catalog/manifest metadata, Parquet bytes, row lineage, raw/normalized keys and unadjusted values; reverify after reading. Preserve no-trade rows, unknown flags and empty partitions. Recover UL/LL from raw without inferring closing tradability. Preserve nonstandard five-character provider codes with null ordinary-stock symbol, avoiding collisions from dropping the final character. Original normalized/training artifacts stay unchanged.

The receipt is explicitly single-vintage research evidence. It does not prove historical availability, frozen dataset source-frame equality, universe/calendar completeness, corporate-action coverage or execution capability. Keep unknown capacity/ticks/settlement and evaluation_ready=false until separate evidence connects them. Do not manufacture NAV performance from this projection. Actual verification currently covers four development dates. See docs/DAILY_MARKET_PROJECTION.md.


### D102 — identical-fold regression baseline comparison (2026-10-15)

Compare all frozen 5d/20d family/seed candidates with zero-return, unscaled trailing20d momentum and V0 Ridge(alpha5), using the original candidate development folds, clipped first evaluation interval and exact symbol/date/as_of/target/label-end/fold keys. Preserve existing reports. Authenticate the full source dataset identity and candidate OOF, but never score holdout. Check training label receipts strictly before fitting and feature availability; fail rather than silently alter training or intersect away missing validation rows.

Use exact per-column training medians, centered block covariance merging, standardized Ridge with missing indicators and intercept. This bounds linear-model matrix memory without stochastic optimization or row sampling; full candidate OOF authentication still materializes one candidate at a time. Verify equivalence to the existing imputer/scaler/Ridge implementation. Save coefficients, split audit and immutable OOF. The all-candidate equal mean is a fixed diagnostic, not selected stacking. Zero prediction is not a cash NAV policy. Keep probability/quantile baselines, economic comparisons and final adoption as separate unfinished gates. See docs/DAILY_BASELINE_COMPARISON.md.


### D103 — same-fold probability and downside baselines (2026-10-15)

Extend daily baseline comparison with training-only empirical large-loss probability and quantile, plus V0 logistic regression. Use the candidates' exact threshold and alpha, and require risk task keys including as_of to match regression. Preserve v1 receipts and original candidate artifacts. Reuse authenticated expanding folds and training availability checks; no holdout scoring or model adoption.

The logistic objective is mean binary log loss plus squared L2 weights/(2*C*n), C=1, unpenalized intercept, no class weighting or tuning. Reuse train-only median/indicator/standardization, cache standardized features on temporary disk, and scan all rows in bounded blocks per L-BFGS-B evaluation. Require optimizer success and max absolute gradient <=1e-6. Single-class training returns an explicitly audited empirical constant. Empirical quantiles use linear interpolation. Fixed candidate means remain uncalibrated diagnostics, not learned ensembles. Record fold models, event counts, convergence and daily-development-metrics-v1 Brier/log loss/ECE/pinball/coverage. A single lower quantile does not establish prediction-interval coverage or absence of crossings. See docs/DAILY_BASELINE_COMPARISON.md.


### D104 — multiple forward ensemble/calibration evaluations (2026-10-15)

Add daily-forward-crossfit-v1 as a separate development diagnostic, preserving the existing selection pipeline and original candidate reports. Freeze three evaluation date blocks with boundaries 1/2, 2/3, 5/6 and 1 before the actual run. Each uses the preceding 1/5 of OOF dates for calibration and the earlier prefix for weight fitting; purge endpoints/receipt times and embargo at least the horizon's observed dates at both boundaries. Require 20 eligible dates in each fit/calibration block. All candidates and variants use the same later-half evaluation cohort; no evaluation row is scored twice.

Learn row-equal simplex weights for raw-return MSE, cross-sectional rank MSE and large-loss Brier. Accumulate exact block quadratic statistics and verify optimizer feasibility and convex dual gap. Unreceived peers cannot enter training target ranks. Calibrate rank to return with nonnegative OLS, probability with monotone isotonic and fixed-mean quantile with a calibration residual offset. Do not learn quantile weights in this version. Save models, splits, hashes, complete evaluated source predictions and per-block/pooled metrics. Rank score MSE against raw returns is omitted; uncertainty scales remain in return units and are not standard errors. Calibration is allowed to worsen future scores. No automatic component pruning, selection, holdout access, adoption or economic claim follows. See docs/DAILY_ENSEMBLE.md.


### D105 — owner-private manual portfolio import and per-revision receipts (2026-10-15)

Allow the user's accounts and holdings to be entered in the app, including no holdings and unknown budget/risk. Export only the pinned per-Site owner using the Site access boundary plus a service-token-derived scoped proof whose digest is stored as a runtime secret. Verify exact original revision bytes and strict schemas in Python. Pin the first imported owner, reject rollback/conflicting revisions and retain immutable local inputs in operational backups. Commit locally before acknowledging the exact cloud revision; repeat imports retain the first receipt timestamp. A later cloud edit returns to import-pending.

An import receipt is not application to the live execution/cash/tax ledger or personal recommendation readiness. Do not infer missing balances, tax state, drawdown guarantees or current forecasts. Preserve all holding symbols for a later explicit reconciliation/comparison adapter and keep historical original forecasts unchanged. No scheduler is installed by this milestone. See docs/MANUAL_PORTFOLIO_IMPORT.md.


### D106 — fixed exploratory Elastic Net and rule diagnostics (2026-10-15)

Extend the authenticated same-fold baseline comparison with fixed V0 Elastic Net (alpha0.001, l1_ratio0.5, unchanged target units, train-only imputation/scaling), and two dimensionless equal-weight rank rules. Momentum+revision uses trailing20d return and forecast revision; the four-factor rule adds sector-relative20d return and ROE. All directions are positive, within-date midranks are centered to [-1,1], and missing/constant/singleton components contribute neutral zero at their original weight. Rank all source feature peers at the common daily as_of before joining any future labels; reject unavailable peers and mixed cutoffs. Report ranking metrics only for rule scores, never raw-return MSE or order actions.

Elastic Net uses full-data Gram statistics and cyclic coordinate descent, not stochastic fitting or sampling. Require maximum minimum-norm subgradient <=1e-9, positive L2, finite objective and recorded objective-gap bound; max50,000 iterations, fail on nonconvergence. No parameter search or result-driven modifications. This is an exploratory diagnostic introduced after earlier candidate results, not a confirmatory adoption gate. Freeze the exact policy before new real-data scores, preserve v1/v2 artifacts, authenticate all18 candidates and compare exact development rows. See docs/DAILY_BASELINE_COMPARISON.md and docs/evidence/daily-simple-baselines-20261015/precomparison-design.json.


### D107 — read-only personal input reconciliation and research comparison (2026-10-15)

Connect latest verified app input to the existing portfolio and immutable daily snapshot without replacing execution/cash/tax records. Explicit one-to-one manual-account/bucket mapping must cover both sets; reconcile classification, cash basis, every holding/quantity/acquisition price and required explicit tax amounts. Preserve odd lots, unknowns and every held symbol. Known unapplied/open fills, missing applied-event evidence, stale/future input and non-current/non11:30 forecasts block comparison. Read all authoritative inputs again after computation and reject concurrent change.

Use explicit versioned cost/tax/daily20d policies and authenticated snapshot lineage. Interpret investment budget only with the declared maximum-total-equity-market-value basis, across all buckets; preserve HOLD and permit strict risk reduction when existing holdings already exceed it, exposing residual breach. Require explicit remaining NISA purchase-notional semantics; share the minimum annual/lifetime remainder across same-bucket buys without same-day restoration from sales. Do not substitute the budget for cash/wealth or guess drawdown-to-risk weights. Reviewed drawdown preference is retained without any drawdown guarantee. Supplemental settings and risk/execution evidence still need the app and adoption connection.

Return a content-addressed research receipt including inputs/settings/source hashes and named blocks or the cost/tax/HOLD result. Original PredictionSnapshot is the forecast authority; do not invent development report IDs for it. Local API uses server time and the existing origin/manual-intent boundary. No live ledger/proposal writes, automatic adoption, real orders or claim of market execution capability. See docs/PERSONAL_COMPARISON.md.


### D108 — optional supplemental settings tied to exact manual portfolio revision (2026-10-15)

Add manual-personal-settings-v1 as a separate append-only owner-scoped record referencing the exact saved portfolio revision and account IDs. Preserve unknown amounts and assumptions as null; require explicit zero and explicit acknowledgement for zero commission. Accept incomplete drafts and show named gaps. Do not infer legal tax rates, NISA limits, account balances or drawdown guarantees. Validate decimal cash comparisons without floating-point rounding and reject mismatched account types or stale portfolio linkage.

Keep supplemental settings, cost/tax assumptions and daily-decision-engine-v2 review separate from live execution/cash/tax ledgers. Saving or exporting a setting is not a PC import acknowledgement, initial-ledger application, model adoption or recommendation readiness. Require the existing authenticated owner boundary, same-origin/manual-intent writes and optimistic parent concurrency checks. Preserve exact export payload bytes and owner/parent identity. The local implementation is checkpointed unpublished at the user's explicit pause request; broader integration QA and all downstream application remain pending.


### D109 — Android APK with offline shared Python computation (2026-10-15)

The user's latest instruction supersedes the PC-required compute assumption: package the existing React UI with Capacitor and run acquisition, feature calculation, inference and portfolio comparison on Android; large retraining remains on PC. Preserve 5b7aa4d and all unpublished work before syncing the renamed public GitHub repository.

Bundle a hash-pinned Pyodide runtime and explicit shared Python source allowlist as offline APK assets. Execute the unchanged concrete feature/decision/ledger/API modules in a dedicated worker, adapting synchronous ASGI calls for threadless WASM. Exclude desktop ingestion facades and fixture bootstraps. Require PC/WASM golden parity and physical Android validation, independently. Keep API credentials in native Keystore-protected storage, commit encrypted local state before acknowledging mutations, and preserve app identity/signing identity across upgrades.

Automate signed main-branch Releases only after test/build gates, with increasing versionCode, hash and changelog. Pin update origin/package/signature and require Android installation confirmation. Do not publish market data, account state, credentials, signing keys or unreviewed learned models. No model is currently adopted; research-only display and explicit missing-model/data/403 blocks remain. Real orders remain out of scope.


### D110 — reviewed portable model import and staged Android verification (2026-10-15)

Export fitted scalar numeric LightGBM, XGBoost and symmetric CatBoost trees into a data-only format with the frozen fold preprocessor; never deserialize executable model files on Android or retrain there. Preserve float32 preprocessing and XGBoost cut precision. Require native-PC and WASM parity independently from final model adoption and physical-device evidence. Only an APK-pinned model hash with adoption/parity evidence, the exact frozen feature-selection identity and reviewed distribution scope may be imported. The approval list remains empty until those real prerequisites are met.

J-Quants source data, user state and private learned weights remain excluded from the public source/APK. Missing history, unauthenticated next-session calendars or unclosed 11:30 cutoffs block feature readiness. Public research APK distribution may proceed after automated gates, while physical Xiaomi 14T Pro tests remain explicitly pending. The owner's latest instruction accepts on-device manual operation and result reporting without USB; USB is optional for PC-assisted diagnosis, not a prerequisite for installation, use, updates or starting acceptance. Record owner-reported results separately from automated evidence. Report this distinction; do not represent browser checks as physical verification or research model outputs as adopted predictions.

Keep one appId and signing identity. Store the encrypted signing key locally with owner-only ACL and DPAPI credentials and send secrets via exact stdin without printing them. GitHub Secrets cannot be read back and do not replace an owner-controlled, independently recoverable offline backup; document that remaining owner action.


### D111 — mobile supplemental settings and explicitly confirmed initial ledger (2026-10-16)

Reuse manual-personal-settings-v1 for device-local drafts and compile complete, explicitly entered amounts into the existing PersonalSettings/cost/tax/daily decision contracts. Keep unknowns null, require confirmation for zero commissions, bind every supplemental account to the exact saved portfolio revision, and reject stale writes. Preserve the original 0.1.11 input table; migrate its latest saved input into the shared immutable manual-portfolio store without creating a balance ledger.

Create an immutable initial-balance preview before explicit owner confirmation. Include every account, reserved cash, tax amount, NISA remainder and odd-lot holding. Use authenticated stored unadjusted closes with an explicit reference date; refuse missing, special-code mismatches and stale prices rather than substituting acquisition prices. Initial prices are research references, not execution evidence. Refuse missing inputs, pending activity, outdated tax years and future settings. Expire previews after 15 minutes and reject changed inputs/settings/prices. Rebuild balances before confirmation. Write the initial portfolio and its confirmation receipt in one SQLite transaction, only while the ledger and execution history are empty. Confirmation retries are idempotent; later draft edits cannot replace confirmed balances.

Expose readiness from the shared read-only personal comparison and display named gaps. Preserve research-only/model-adoption/forecast/market-evidence blocks. This stage does not turn raw portable-model output into an authoritative forecast or claim the final personal comparison is ready. Home labels initial balances and the daily-close reference date. All new state remains inside the existing encrypted native persistence/backup; no personal input is synchronized to public GitHub.

### D112 — owner-authorized Android completion and independent ChatGPT research (2026-10-17)

The owner asks to finish the app with only provider-key setup remaining after prerequisite personal/model setup. Implement resumable initial history, mobile-data networking, business-day automatic updates, background computation and completion notifications. New candidates: market capitalization at least JPY30 billion and top300 by trailing20-session mean trading value; retain every holding and preserve the historical market/sector context population. Use one privately imported reviewed model bundle; exclude private weights from public distribution.

The owner accepts ChatGPT/Codex shared plan usage through the documented public-client Sign in with ChatGPT flow, with app-side model and reasoning selection. Keep credentials native, encrypted and outside portable backup; never reuse another app's credentials or silently switch to paid API billing. Actual Android/account/model/search compatibility is a required live check, not an assumption of success.

Research top20 numerical-model candidates plus all holdings. First investigate the company and time cutoff without numerical rank/return/Action, then compare against the frozen numerical forecast. Seven criteria are a minimum, allowing additional issues, counterevidence and insufficient-information conclusions. The owner explicitly chooses side-by-side judgment and evidence: research must not alter numerical forecasts, candidate selection or share quantities. Timestamp later research separately from the11:30 alpha freeze. Missing/failed/limited research stays visibly incomplete and resumable. Preserve original records and setting/prompt/model versions.

Keep the UI simple, with details disclosed on demand, touch targets at least48px and adjacent actions at least12px apart. Separate destructive/restoration actions from normal actions. Completion and evidence requirements are tracked in docs/FINISHING_PLAN.md; do not equate APK publication, fixture success or development metrics with actual model adoption or live readiness.

### D113 — immutable two-phase ChatGPT research receipts (2026-10-17)

Persist independent and comparison phases separately, linked to one exact frozen prediction snapshot and versioned research context. The independent provider request contains only company identity and research cutoff, without model rankings, returns, holdings or account data. The comparison request includes the completed independent findings and the original numerical prediction. Retain the selected model, effort, prompt version, actual served model, execution times, citation URLs and request/response hashes. Do not invent publication times from search citations.

Accept only completed, non-refused output. Independent research additionally requires an observed completed search and HTTPS citations. Save each accepted phase immutably before saving the combined record; retries of the identical receipt are idempotent. Validate prompt hashes, phase ordering, prior-phase references and the original numerical prediction on write, read and backup verification. SQLite schema4 adds separate research tables; schema3 backups remain verifiable and migrate without changing old forecasts. This receipt layer does not claim native research scheduling, live search quality, account eligibility, retry-state persistence or duplicate provider-request prevention is complete.

### D114 — durable research dispatch, recovery and owner-authorized draft PR (2026-10-17)

The owner explicitly authorizes GitHub push and PR creation in this chat. Push reviewed implementation commits to android-completion-chatgpt and maintain draft PR2; this does not authorize main merge or APK publication. Keep pre-existing research edits and private artifacts out of this PR.

Reuse a research context for the same frozen snapshot, symbol, model, effort and prompt version. A new explicit reanalysis references the prior run and receives a new revision, preserving prior findings. SQLite schema5 stores runs and attempts before provider dispatch, prevents concurrent claims for one run and requires explicit retry after failure/interruption. Commit an accepted phase, its attempt outcome and the combined comparison record in one transaction. Preserve and verify schema3/4 backups.

Native research dispatch pins the canonical request hash and saved model/effort, forces store=false and stream=true, and allows only web_search. Persist encrypted response receipts outside portable backup until the shared ledger confirms persistence; keep acknowledged tombstones so a repeated caller cannot send the same attempt again. Native recovery checks the live process reservation and seals an absent attempt before declaring interruption. A transient observation failure must leave the attempt pending. Accepted research calls finish after Activity destruction when the process remains alive; business-day background scheduling and real OS process-death testing remain separate unfinished requirements.

Display original numerical forecasts, independent findings, comparison findings and prior revisions separately. Show the numerical cutoff and research execution time with year and timezone; unknown publication dates stay visibly unknown. Render model text as escaped text and citation URLs as clickable HTTPS links. Do not rewrite numerical predictions, eligibility or share proposals. A candidate with a saved numerical forecast must have a detail page even when unheld and absent from the trade proposal.

### D115 — recoverable ChatGPT session rotation and explicit reauthorization (2026-10-17)

Keep the owner's verified subject/client mapping separately from tokens in one atomically written encrypted native envelope. Migrate the earlier credential key without exporting it. Reuse the issued client ID and host ID after logout or terminal refresh failure. A late authorization or another identity cannot replace the registered owner. Clear retained ID-token hints with the credential set on logout.

Serialize token renewal across native consumers. Save replacement credentials even if refreshed scopes remove plan permission, then prevent inference. Confirm terminal refresh failure by the documented machine-readable code and4xx status before clearing unusable tokens; temporary network/5xx failure preserves credentials. Keep bounded diagnostic metadata (HTTP status, body shape, code, parameter and request ID), excluding raw messages and credentials. No automatic alternate-model or paid-API fallback is introduced.

Explicit logout blocks new inference, disconnects in-flight inference connections, clears local tokens and attempts renewable-session revocation. Resolve the revocation endpoint from official OpenID discovery, validate issuer and HTTPS origin, and retry only a bounded temporary failure. Retain account registration and report whether remote revocation was actually confirmed. Rejected/late authorization grants receive a best-effort revocation attempt and are never activated. The UI supports explicit reauthorization and cancellation from a connected state, keeps model settings after expiry and distinguishes permission, eligibility, app usage-limit and temporary errors. Actual account and device acceptance remain required.

### D116 — resumable mobile history and explicit liquidity candidate preview (2026-10-17)

Keep a native SQLite page journal for each closed source day. Persist page data in bounded chunks and atomically advance the endpoint/cursor after each accepted response; retain the same acquisition across temporary failures, app restarts and plan errors. Complete calendar-only holidays without fabricated market rows. Publish the five canonical datasets and supplemental valuations only after shared validation. Retain per-page receipt times, row counts and digests with the committed acquisition; acknowledge native pages only after the encrypted shared state commits. Reconcile a lost acknowledgment from saved acquisition identities. An explicit fresh acquisition retires the prior active pointer and retains its page evidence. Do not silently retry forever or claim foreground acquisition is background scheduling.

Use a persisted initial date range (default 420 days through yesterday, at most two years per operation), skip committed days, and stop after the current source day. A one-day correction/recovery operation does not replace the initial date range. Validate, preserve and atomically migrate earlier daily snapshots. Complete daily snapshots supersede removed rows; distinct later observations with identical content remain distinct, including A -> B -> A. Actual receipt time and observation order resolve versions without backdating.

The candidate preview uses /v2/equities/valuation MktCap in million JPY (30,000 equals JPY30 billion), not the deprecated bars field or inferred shares. Rank TSE common issues by Decimal arithmetic over exactly the latest twenty calendar-authenticated business sessions, require twenty known trading values, break ties by symbol, take at most300 and union every recorded holding. Keep exclusions, input hashes/receipts and the exact window inspectable; preserve unknown holdings status. Do not restrict broad feature contexts to the selected300. The preview uses the latest closed-day master and is not yet authenticated current-day membership or the final numerical proposal integration.

Official provider evidence: [valuation specification](https://jpx-jquants.com/ja/spec/eq-valuation), [plan capabilities](https://jpx-jquants.com/ja/spec/data-spec), [pagination](https://jpx-jquants.com/ja/spec/pagination). Actual account access, source completeness, long-run storage/performance, OS background execution and current-day master acquisition still require acceptance evidence.

### D117 — authenticated current-day membership without historical-universe contamination (2026-10-17)

Fetch the exact decision day's calendar and security master under a native journal profile isolated from closed-day historical acquisition. Use the same bounded page receipts, restart and post-commit acknowledgment rules; the profile's keys and identities cannot acknowledge another profile's acquisition. A holiday calendar terminates acquisition without fetching the following session's master. The official provider returns next-session membership for a holiday date, so that response cannot represent the holiday's membership.

Store current-day membership separately from the five canonical historical datasets. The forward candidate universe requires an exact matching business-day snapshot received no later than the alpha cutoff, uses prior closed-day valuation and twenty completed sessions for liquidity, preserves every recorded holding even when absent from today's master, and never infers a new code's history. A late correction remains a separate observation and cannot replace the pre-cutoff view. Retain the original receipt text, page provenance and immutable acquisition identity through backup. Round native sub-microsecond receipt precision forward when converting to Python datetime so truncation cannot admit a late receipt at11:30.

Expose the most recent receipt time separately from the receipt eligible at the alpha cutoff. Reuse an already committed eligible observation after cutoff and recover an unacknowledged native receipt before dispatching again. The previously implemented closed-day universe remains an explicitly named preview; final numerical generation must request current membership. Source: [official security-master specification](https://jpx-jquants.com/ja/spec/eq-master). This transport and universe integration does not approve a model, supply missing calibration, replace the bounded optimizer or prove Android OS background execution.

### D118 — calibrated private bundle and immutable mobile numerical publication (2026-10-17)

Package exactly four data-only heads (5d/20d regression, 20d downside quantile and large-loss probability) with the frozen feature identities, training chronology, return/label semantics, risk thresholds, received-past-only residual RMSE and the owner's review of the same selection. Validate all trees and preprocessing even for zero rows. The PC packager creates one private file and a pending pin proposal; it cannot approve its own artifact. Verify the exact file hash, review/calibration lineage and PC/device evidence pins before import. Keep approval empty until actual evidence exists. Paper review, an import or a pin alone cannot bypass authenticated adoption gates.

Import all heads transactionally and retain explicit bundle-selection events. An unavailable, revoked or post-cutoff current selection must not silently fall back to an older model. Repair a corrupted cache only from the same exact pinned file, record the old hash and actual repair time, and reject a backward repair clock. A read-only bundle parity probe can inspect all four heads before pinning; it never imports, approves or publishes predictions. Synthetic PC/WASM vectors remain test-only, outside APK assets and model policy.

Generate research-mode 5d/20d PredictionSnapshots from current-day membership, the full feature-context population, selected candidates and every current holding. Require model selection, personal inputs, confirmed ledger and source receipts no later than11:30. Keep actual received time separate from numerical generation time; never invent1d forecasts, calibration, morning inputs or share quantities. Retain source/feature hashes and original head outputs. Explicitly exclude and record new candidates lacking history; missing held predictions block the complete snapshot while preserving usable output. A truly empty equity universe is a cash-only result without a fabricated snapshot. Preserve four- and five-character holding codes even when unsupported for new purchase.

Persist a computation intent before appending the shared immutable snapshot. Reuse the same frozen scope, numbers and timestamps on retry. Guard current personal revisions inside the snapshot transaction, and recover a lost completion marker only from an identical already-published snapshot. The new forecast source can feed the existing independent ChatGPT research flow, but does not change its numerical results. Quantity optimization, daily background execution, actual adoption and physical-device acceptance remain incomplete. See docs/MOBILE_MODEL_BUNDLE.md for the private handoff contract.

### D119 — deterministic SQLite connection closure before mobile state restoration (2026-10-17)

Python's SQLite transaction context commits or rolls back without closing its connection. Explicitly close all device-local database connections after their transaction or read, including personal-settings reads against the WAL ledger. Also close backup source/target and validation probes on exceptions. Retained handles must not depend on garbage collection before repeated backup restoration. Preserve transaction commit/rollback behavior, stored schema and payloads. Test repeated restore while retaining strong references to every opened connection, requiring them all to be closed. This corrects the restore-time WAL lock observed in CI run38946144536; do not dismiss it as a retry-only test failure.

### D120 — explicit finite daily quantity search for the full mobile universe (2026-10-17)

Introduce research policy daily-decision-engine-v3-bounded and coordinate-exchange-v1, independently from unchanged legacy exhaustive policies. Never switch a saved policy silently after the exact-search cap is reached. New settings start with the bounded policy unreviewed; retain old settings as saved, expose explicit method selection and clear UI acknowledgment on change. Keep20d weights, risk/cost/tax/position/cash/liquidity/budget constraints and no-trade threshold intact. This is not model adoption; actual NAV/holdout/owner/device gates remain required.

Search from HOLD, legal all-cash and liquidity-bounded liquidation seeds. Consider every symbol/account key, then bounded coordinate and sell/buy exchange moves, with at most32,768 trial evaluations, three coordinate passes, two exchange passes and twelve upper-feasibility bisections. Share grids preserve existing odd-lot remainders and value caps without allocating an unbounded share range. Retain the best accepted feasible result when a quota expires. Resolve equal utility by lexicographic targets in stable code/account order. Do not claim a global optimum. Reuse the existing full cost/tax evaluator, omitting only unheld zero targets during trials; recheck the selected result with the complete universe. Preserve the aggregate bucket-sale tax calculation, not a sum of standalone tax estimates.

Save actual search coverage, budget, counts, cash-seed availability and explicit non-optimality in each new-policy proposal. Require the audit to cover exactly the proposal's keys. Omit the new optional field for legacy proposals so old canonical payloads and backups retain their identities. Include decision/bounded.py in the personal-comparison implementation hashes and offline package. Synthetic PC/WASM parity and timing are test evidence only, never private learned weights, model approval or Xiaomi acceptance. The frozen-market-to-saved-quantity integration remains a separate unfinished part of the daily pipeline.

### D121 — frozen evidence to recoverable personal share publication (2026-10-17)

Connect the selected immutable numerical forecast to the shared personal comparison and archived share proposal. Use the exact original current-membership observation, previous-session raw close and twenty-session mean trading value for every predicted candidate and holding. The 100-share lot is an explicit research assumption. Freeze raw historical security-master observation identities in the numerical data proof; resolve holdings absent from current membership against those exact original observations. Verify dates, receipts and raw payload hashes, never replace them with later corrections or runtime-dependent Pandas frame hashes. Missing held prices, liquidity or metadata stop publication.

Keep original personal revisions, ledger, execution records, forecast, market evidence, comparison and decision policy in a private device-local computation receipt before publication. Atomically recheck current personal/settings/execution/numerical references with the shared proposal, archive receipt, policy and ready status. A retry preserves the original quantities and generation times; startup acknowledges only an identical existing archive and never generates a missing proposal. Numerical and decision selection journals identify the current result explicitly, including when it is a previously cached result. An incomplete or blocked selected numerical run cannot fall back to an older snapshot. Historical archives remain readable by identity after inputs change, while current proposal display and manual review reject stale inputs.

A truly empty eligible universe with no holdings is a completed CASH_ONLY result after cash/tax/ledger/execution reconciliation. Save its immutable receipt and ready status without a fake forecast, security proposal or balance change. Reactivate a cached verified result only after rechecking its guards; retain saved user decisions, original computation time and the actual recheck time. Validate publication pointers and cash receipts during integrity checks and backup restoration. Keep optional publication guards absent from legacy canonical payloads.

The foreground UI uses one prediction-and-quantity button, with each stage resolving only after the native encrypted state commit. Show saved quantities through Today, the original JST timestamps, incomplete saves and changed inputs. Cash-only completion has its own readable state. Test-only PC/WASM fixtures remain outside APK assets and production model approvals. This milestone does not complete the Start/background/notification flow, adopt a model, authorize orders, or satisfy live-account and physical-device acceptance.

### D122 — application-owned serialized mobile computation (2026-10-17)

Move the authoritative interpreter and native generation counter out of the Activity's JavaScript runtime. Use one application-context compute owner per canonical database path, serializing API operations and validated restoration on a bounded native queue. All current Android UI API requests use that owner; native callers can reuse it without another Python state or competing generation counter. An accepted operation belongs to the owner rather than its Activity consumer. A native write must commit before the API result is acknowledged; discard the interpreter after failed persistence and reload the last durable state. Compare external generation changes before reads and reject changes during a read.

Host the same offline worker in an Activity-independent WebView using a separate internal HTTPS origin. Serve immutable APK assets only, block navigation and network fallback, disable file/content access, restrict frames and connections with CSP, and expose only request/reply readiness to the trusted compute page. Keep provider credentials and requests in existing native components. Preserve the current encrypted filename, Keystore alias, old-envelope reads, chunk format, AAD and CAS writes; read the encrypted envelope and chunks in one SQL transaction across independent handles.

Apply that same APK-only handler and blocked-network/file/content settings to Android's application-wide Worker resource loader. Disable Capacitor's Activity-side replacement of this loader so recreating a UI cannot redirect an existing interpreter's imports to the UI origin. Both loaders reject unknown origins and paths rather than falling back to a network. Runtime failures report only fixed stage/category/resource-presence codes to native diagnostics; raw worker exceptions remain hidden in production. See [Worker settings](https://developer.android.com/reference/android/webkit/ServiceWorkerWebSettings) and the pinned Capacitor Bridge/CapConfig sources.

Validate restores in a newly initialized isolated host before replacing durable data. Close the previous host first to avoid retaining two WASM heaps; failed validation leaves durable state unchanged and the next request reloads it. Do not recreate or retimestamp original forecasts, proposals or ledger entries. The compatibility write API also validates through the owner. Test the actual packaged interpreter on Android, independent callers, durable restart, invalid restore, rejected native commit, old envelopes and cross-handle consistency. Emulator proof is not Xiaomi acceptance. Scheduling, OS stop/reboot recovery, initial-download orchestration and notifications remain separate required work. See [Android local-content guidance](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content) and [WebView interception](https://developer.android.com/reference/android/webkit/WebViewClient).

### D123 — bounded persistent Android daily work (2026-10-17)

Start is explicit device-local opt-in. Persist a session identity and status independently of the portable shared capsule; stop and restore invalidate old sessions before further dispatch. Use unique WorkManager requests with CONNECTED (mobile data permitted), one periodic recovery wake and bounded chained acquisition slices. Request notification permission from the visible Start action; denial does not prevent computation or remove saved results. Notification text contains no holdings or balances. API-key deletion and backup restore stop scheduling. Do not restore automatic execution from a portable backup.

Reuse the same application-owned interpreter, encrypted writer, native page journal, provider credentials and application-wide request pacing. Fetch at most four pages per acquisition in a worker slice, persisting each accepted page/cursor. A partial slice exposes no datasets. Ingest a complete receipt through the shared core and wait for encrypted native commit before acknowledging pages. Reconcile a lost acknowledgment from committed acquisition IDs. Check session cancellation between calls and pages. No foreground service, unrestricted background loop, exact-alarm exemption or unbounded retry is added. Unknown/transient failures have at most three attempts per JST day; 401/403 waits for an explicit resume after correction. OS stops retain the current page receipt; the periodic request can wake a lost chain.

Prefer the current-day membership acquisition between 10:30 and 11:30 JST before continuing long initial history. Actual receipts and shared validation remain authoritative. If Android starts late, do not fetch a late current-day master and pretend it met the cutoff; mark the missing cutoff information. After closed-day history is complete and the cutoff is reached, save immutable numerical forecasts and guarded quantities through the existing two committed core stages. Closed sessions and inactive/blocked decisions cannot emit a completion claim. Show numerical saved and independent ChatGPT research separately. This milestone still uses manual research dispatch; it does not complete automatic research.

Read authoritative device-local results on Android offline/visibility/focus events, including returning from a notification. Preserve the web client's existing offline stale-proposal suppression. Keep Start/Stop on Home, Today and device settings.

WorkManager is deferrable: 11:30 is a data boundary, not a promised exact job start. Expose the actual state/day and delayed waiting state. Android force-stop requires reopening the app. Preserve all existing stale/future, personal-versus-ledger, execution/cash/tax/NISA, model adoption and market-evidence gates pending the owner's answer about ledger continuity. OS reboot, screen-off, Xiaomi performance and real-account acceptance need independent evidence; mocks and an emulator cannot satisfy those gates. Sources: [WorkManager 2.12.0 release](https://developer.android.com/jetpack/androidx/releases/work#2.12.0), [unique work](https://developer.android.com/develop/background-work/background-tasks/persistent/how-to/manage-work), [constraints and periodic scheduling](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work).

### D124 — daily independent research through the shared native account client (2026-10-17)

Move noninteractive ChatGPT transport, renewable session access, account/model selection and accepted research execution to an application-owned client. The Activity retains system-browser sign-in and catalog UI. Both manual and scheduled dispatch use the same bounded queue and encrypted native research journal; a repeated attempt reuses its exact receipt or tombstone. A rejected competing request must not release another accepted reservation. Sign-out blocks new credential use and disconnects both kinds of in-flight inference. Preserve the existing client ID, subject, Keystore alias, preference names, refresh serialization and revocation behavior. Do not import another app's token or use a paid-key fallback.

After a current active numerical/share publication, read its exact selected snapshot and top20 candidate symbols plus every holding from the shared core. Reject missing/old/future/inactive publication and preserve its forecasts, quantities, ledger and receipt times. An actual cash-only publication needs no provider call. Reuse this validated read to avoid repeating feature generation while research slices continue. Pin one encrypted native batch per JST day to snapshot, symbols, account identity hash, model, effort and prompt version. Keep its run IDs and progress outside portable backup. Changed settings or a missing shared record after restore require review; a completed local cursor is not sufficient proof of shared research completion.

Schedule one research phase per slice: shared claim and native commit, native response/recovery, shared receipt and native commit, then response acknowledgment. Do not show numerical rankings, returns, holdings or Actions in the independent request; comparison uses only the completed independent findings and the original immutable forecast. Store actual research timestamps separately from the alpha boundary. Preserve completed responses across an interrupted consumer. Return the canonical request hash for an already-running shared claim without returning a dispatchable request body. Validate that hash against recovered native output as well as newly dispatched output; a missing or different hash cannot be accepted as completed. Recover a known completed response without another network call, retain an ACK failure for later cleanup, and never automatically retry an unknown/failed attempt. An invalid response for one company remains incomplete while the other companies continue; a usage/auth/connection failure waits for explicit owner recovery. Subsequent manual completion can satisfy the pinned run. Show numerical saved, research running, research incomplete and all research saved separately.

Use ordinary store=false, stream=true Responses requests from the Android scheduler, not the unsupported Responses background field. Bound the native HTTP stream to315 seconds in addition to the read timeout; a waiting consumer does not establish non-dispatch. Check Stop/session boundaries before dispatch and shared writes; accepted native execution may finish into its protected receipt after Activity/worker loss. Do not start a new old-day phase after a day rollover. Live account search/plan access, OS process death/reboot, physical-device timing and actual model adoption remain required acceptance gates. Official OpenAI documentation: [inference completion](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference), [refresh and protected credentials](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions), [supported request fields](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

### D125 — real Android lifecycle acceptance on disposable emulators (2026-10-17)

Add a separate controller-driven acceptance suite after the existing instrumented regression suite. Require GitHub CI, the workflow's disposable AVD directory, an emulator serial, qemu identity, primary user0 and API35 before installing or clearing the exact debug package. Refuse physical devices and local execution before adb mutation, including diagnostics on guard failure. Guard the test APK again by explicit arguments, debug package/flags, emulator hardware, absent provider credentials, absent personal inputs and absent imported bundles. Fixtures are compiled only into the test APK; do not add fixture transport, clock changes, model approvals or test routes to the application APK.

Prepare actual-receipt calendar-only synthetic sessions and an uncommitted pagination cursor in the native journal. Use the unchanged application owner, encrypted capsule, real DailyWorker/DailyWakeWorker, network constraint and unique requests. Destroy a real Activity, turn off the screen, terminate the application process without force-stop, and separately reboot the actual emulator. Observe native page acknowledgment and generation change from a read-only host copy before injecting any verification instrumentation. A failed snapshot observation is not evidence of a stopped worker and must not cause a new dispatch. Verify the original request reaches SUCCEEDED, periodic reservation remains present, shared acquisition IDs and original receipt timestamps survive, the original manual revision stays identical, partial pages/cursor survive, notification denial remains harmless and no forecast/proposal/order is invented.

Treat Android force-stop separately: observe beyond the scheduled delay with no process or capsule change, then explicitly reopen the app and verify the same saved acquisition resumes. Do not claim automatic execution while a package is force-stopped. Use API31+ no-restart instrumentation on an already running debug process: normal instrumentation force-stops its target on finish and would contaminate the lifecycle proof. Preserve existing regression coverage; exclude only the controller-only suite from the ordinary invocation and run its prepare/verify methods explicitly for all three lifecycle phases.

No-restart instrumentation uses a different runtime package from the already loaded application. Keep a reflection bridge in the test APK only, resolving package-private application components and the existing WorkManager singleton through the target application's loader. Do not widen production visibility, create a second scheduler singleton or alter the production dispatch path to accommodate the test.

The first unforced OS-loss run retained the original jobs and pages but did not dispatch within200 seconds. The API35 scheduler reported a31-minute batching limit; minimum delay does not promise delivery at that time. Preserve the controller's default unforced200-second acceptance and expose it as a manual workflow choice. Add a separate, explicitly selected CI recovery mode: observe unforced for90 seconds, then ask JobScheduler to run only the recorded original system job with `-s` (all constraints satisfied), never `-f`, replacement enqueue, instrumentation dispatch or changed power/clock policy. Observation errors must still fail without dispatch. Record the selected policy and actual delivery per phase, retain pre-dispatch diagnostics, and verify the same original WorkRequest reaches SUCCEEDED. A passing controlled mode proves persisted recovery and commit/ACK, not natural scheduling within the window. Keep natural timing and physical-device scheduling acceptance open. See [delay semantics](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work) and [AOSP scheduler command semantics](https://android.googlesource.com/platform/frameworks/base/+/0c76f06eb78f772a865a998045c38bd5fdfb7750/apex/jobscheduler/service/java/com/android/server/job/JobSchedulerShellCommand.java).

API35 also retained an overdue TIMING_DELAY while the display slept; strict `-s` correctly refused it. In the controlled mode only, briefly wake the display for2 seconds to allow ordinary alarm delivery and return it to sleep before ACK observation. If it remains pending, use the same constraint-satisfied scheduler command. Record this screen intervention separately from unforced delivery and continue to fail on unreadable observations or rejected constraints. This does not prove automatic wake-up from sleep. The default unforced mode is unchanged. API35's strict command behavior is verified in the [Android15 source](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android15-release/apex/jobscheduler/service/java/com/android/server/job/JobSchedulerShellCommand.java).

Extend the same three OS-loss phases to encrypted native research reservations, completed responses and acknowledged tombstones. Leave reservations active before actual process loss; do not simulate death with release. Re-enter the real application client with an intentionally nondispatchable request body and absent credentials, require repeated calls to reuse the exact retained state/timestamps, and reject changed request hash/model/effort without changing the original receipt. A completed response must still be available after loss, and acknowledgment must remove its output while retaining its tombstone through later OS losses. Retain earlier batches as each new phase is added. This verifies native receipt recovery and no-resend control, not a live provider stream or completed independent/comparison research against an actual account. Report original WorkRequest/system job identity, prepared generation and recovery counts without raw response payloads.

This verifies lifecycle delivery and durable handoff of cached native receipts, not live J-Quants networking, adopted-model daily quantities, live ChatGPT search, OEM scheduling or production deployment. Keep those acceptance gates open. Sources: [persistent scheduling](https://developer.android.com/develop/background-work/background-tasks/persistent), [adb process controls](https://developer.android.com/tools/adb), [instrumentation invocation](https://developer.android.com/studio/test/command-line), [Android15 instrumentation finish semantics](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android15-release/services/core/java/com/android/server/am/ActivityManagerService.java).

### D126 — lossless mobile market columns within existing storage limits (2026-10-17)

The synthetic full-market probe observed the previous representation exceed the unchanged native capsule limit at its90-session checkpoint:137,959,496 base64 characters against134,217,728. Retain all raw observations, revision order, actual receipt timestamps and the broad market/sector population. Do not solve capacity by keeping only the300 candidates, deleting old revisions, reducing numerical precision or increasing the native/restore limits.

Store scalar raw and normalized columns under content-addressed SHA256 references, with constants inline and missing-field presence separate from null. Preserve source_record_hash with the unchanged v1 raw-record hash algorithm. Compact normalized table JSON only if its exact original bytes can be reconstructed; otherwise keep the legacy representation. Verify column checksums, expanded-size limits and the original normalized hash on read. Share stable columns across datasets/dates without changing row order or scalar types. Continue to read the shipped zlib row representation, including nested provider extras. Mixed old/new databases must work during migration.

Before export, transactionally repack at most5 old batches, retaining observation identities/hashes and bounded cursors. A failure rolls back both new columns and prior updates in that transaction. Zero freed legacy blobs so their obsolete physical copies do not inflate later capsules; retain the SQLite files and reuse freed pages. Export must reject a database larger than the existing256MiB per-file restore limit before producing an unrestorable capsule, and remove the temporary snapshot on failure. Native chunk encryption, CAS/generation, AAD and128MiB character limit remain unchanged.

For normalized PIT materialization, verify the original row JSON before using the pinned Pandas scalar parser/schema conversion directly on columns. Reuse decoded immutable columns in a bounded128-entry cache for one read, avoiding one new copy of every repeated string per row. Preserve Pandas values, dtypes, indexes, ordering and source identities. Exercise the actual bundled Pandas implementation in the WASM migration/restore parity test whenever the codec or runtime dependency versions change.

Keep an isolated, reproducible synthetic5000-symbol/300-session ingest/export/restore check in CI. Publish only its report with source hashes and measured limit checks. Its checkpoints do not measure every Android encrypted commit, live-provider row distributions, full feature-generation memory or physical-device performance. The PC PIT read still peaks above2GB; the existing1,500,000-row read guard and longer ongoing-history capacity remain separate limitations to resolve. Do not present this storage fix as completion of Xiaomi or live-market acceptance.

### D127 — latest causal features without a retained historical feature matrix (2026-10-17)

Keep the public full-history transform for research and an internal shared calculation for daily snapshots. Validate the complete inputs and give every symbol's indicators its complete original causal history, including session gaps and warm-up. In latest mode only, copy each symbol's final calculated row before continuing; do not retain its historical result matrix. Keep market and sector contexts, financial as-of matching, feature formulas, manifests, selected41/51 columns and numerical precision unchanged. Verify exact values, dtypes, ordering and input immutability against the full-history tail for V0/V1/V2, including older final rows, missing financials/shares, late context, same-day bars, gaps and duplicate financial timestamps.

Validate all financial rows before grouping them once for symbol lookup. Preserve original row order, exact-match as-of semantics, missing-symbol outputs and duplicate index handling; ignore unused category groups. Release temporary PIT parts/cache after concatenation and use equivalent in-place sort/deduplication without changing keys, timestamps or source identities. After source-vintage verification and hashing, release each source frame when its derived build is finished, including the validation dictionary that otherwise retains all frames through later merges. Existing forecasts and share publications remain immutable.

Add a bounded PC-only verifier over a completed isolated synthetic capacity dataset. Record source hashes, database identity, source/context and feature row counts, elapsed time and measured process memory; refuse changed data and stop only the dedicated probe on a time/memory limit or failed observation. Keep the reference-history mode for explicit comparisons. Run latest mode for5000 symbols/300 source sessions in CI and upload only reports. This is direct ProductionDataBundle→FeatureEngine evidence, not the mobile JSON conversion, full forecast pipeline, adopted model or physical-device acceptance. Keep those gates and the longer-history limit open.

### D128 — reject portable backups that exceed the existing restore envelope (2026-10-17)

Use one128MiB envelope limit for portable-backup encryption, decryption and file reading. Before key derivation or cipher allocation, reject cleartext larger than that limit minus the unchanged69-byte envelope overhead (magic9 + salt32 + IV12 + GCM tag16). Check the actual UTF-8 JSON bytes, not only the native payload's character count. Keep the existing password rules, KDF, encryption format and native capsule limits. A rejected export must not open/truncate the selected output stream or change the durable state. Verify overhead against a real roundtrip and reject the first oversized cleartext before even validating the password; native/real-device verification remains separate.

### D129 — bound mobile feature conversion while preserving records precision and source identity (2026-10-17)

The direct FeatureEngine probe does not cover the application's records JSON conversion. After freezing the identities of all complete sources, project only columns consumed by FeatureEngine and pass DataFrames on the in-process runtime/forecast path. Keep the default records interface for compatibility. Retain every symbol and historical row, global validation, broad market/sector context, receipt timestamps and the frozen41/51 selections. Do not bypass the shipped JSON numerical conversion: reproduce its default decimal precision, ISO millisecond timestamps, null handling and DataFrame type inference one column at a time. Share repeated immutable strings/datetimes after the same JSON conversion; do not factorize mixed objects or change negative-zero/boolean semantics. Preserve input frames.

Calculate source identity from the same canonical schema and ordered uint64 row-hash bytes as before, updating SHA256 in10,000-row chunks instead of factorizing all high-cardinality strings simultaneously. Do not version or silently change source IDs. Compare the exact previous definition over multiple chunk boundaries, typed/null/category/text inputs and empty frames. Verify original records versus projected frames and full feature JSON in PC and bundled WASM, including export/restore and unchanged source IDs.

Use an explicit synthetic initial-download fixture: all history is received at a declared virtual11:00 and evaluated at that day's11:30, with synthetic future calendar entries. Never backdate actual receipts or use this fixture as production transport. CI must exercise feature_inputs→calculate with5000 symbols/300 sessions at the existing600-second/3500MiB probe budget, rather than only the direct library path. Upload reports and hashes only. Thread-based self-observation may overshoot while a C extension holds the GIL; it is not a hard OS memory cap. Model inference, share generation, every native encrypted commit, longer ongoing history, live providers and Xiaomi performance still require separate acceptance.

### D130 — daily source verification and projections beyond the legacy row guard (2026-10-17)

Keep every raw/normalized observation and the full historical market/sector population. On the mobile V2 feature path, read the selected complete master and price snapshots by source day instead of assembling their unused audit columns across all dates. First obtain provisional concat dtype/all-null evidence, including optional older schemas and numeric promotion. Compact profiles may use schema-only representatives, never market/feature values or identities. In a second pass of the same SQLite transaction, fully reconstruct and authenticate every selected normalized table, deriving its record hashes when the compact representation requires them, before hashing its exact canonical rows or retaining the required production columns. Empty/legacy profiles also use the verified reader. A bad historical batch must prevent a completed source identity.

Keep the original complete-source identity definition and byte order; source-day boundaries must not change the ordered row-hash stream. Verify that each batch belongs to its declared source date, apply the same latest complete receipt selection and duplicate-key ordering, and include rows outside the decision candidates and fields omitted from the projection in the full-source identity as the previous PIT reader would. Pass the complete identity through the explicit trusted source-identity interface, bind it to the returned projection's object and content hash, and reject replacement/mutation before the production build. Use weak references so the adapter does not retain consumed inputs. Do not reduce the universe to the300 decision candidates or truncate indicator history.

Retain a768MiB combined budget for the master/price projection arrays, including their per-batch indexes, before concatenation. This is an array retention budget, not a process RSS or phone guarantee. Keep the original full-reader1,500,000-row guard, native128MiB character limit,256MiB/file restore limit and portable-backup envelope unchanged. The actual app feature path uses the projection adapter; increasing a legacy row guard alone is not a capacity fix. Test the supported two-year download scale with5000 symbols/520 synthetic sessions and the unchanged600-second/3500MiB feature-probe limits; verifiers may generate at most525 sessions. Longer continuous retention and physical-device acceptance remain separate work.

For initial ledger valuation, verify historical dtype evidence without assembling every historical price, and retain only the same latest closed common-issue snapshot with its original record hashes. Keep same-day exclusion, no per-holding fallback to older dates, staleness and finite-price checks. Once a ledger exists, skip the redundant initial-ledger price scan; do not reprice the saved ledger or refresh the manual72-hour confirmation receipt. Preserve initial confirmation/restore semantics and the existing order prohibition.

### D131 — yield between numerical commits and request foreground execution for long calculations (2026-10-17)

Separate forecast generation, share generation and provider research into bounded durable slices. Reuse the selected published/cash_only forecast only when its as-of Instant equals the current JST day's11:30 cutoff. A successful encrypted forecast commit yields to a new WorkRequest before generating shares; a successful share commit also yields before research. The next research-plan read must remain validated by the shared core. Keep all existing personal-input, model-pin and frozen-market validation; never refresh receipts or alter the saved forecast to resume. Reject malformed saved timestamps, do not claim completion after a JST day rollover, and require the exact cutoff for share completion too. Partial progress must remain distinct from completion.

Before either long numerical stage starts, await WorkManager foreground admission with a dataSync service and the required manifest permissions. Use a fixed private ongoing notice containing no holdings, balances or provider text. Admission failure must prevent the numerical call and enter the existing bounded retry policy with an explicit waiting status. This does not promise precise scheduling, actual OS admission, Android16 quota exemption or physical-device performance. Official references: [Worker execution limit](https://developer.android.com/reference/androidx/work/Worker), [long-running workers and Android16 quotas](https://developer.android.com/develop/background-work/background-tasks/persistent/how-to/long-running), [dataSync requirements](https://developer.android.com/develop/background-work/services/fgs/service-types#data-sync).

Exercise the existing native encrypted store using96,870,524 synthetic ASCII characters, the measured520-session capsule length, without raising storage or heap limits. Verify reopen, generation conflict and the entire content digest. Collect only phase, character count, maximum Java heap and elapsed seconds. The opaque-store test cannot prove valid SQLite restoration, the complete owner/WebView bridge, every production commit, model inference or Xiaomi acceptance. Keep failure evidence and repair an actual capacity failure before counting it as passed.

### D132 — release consumed WASM request payloads (2026-10-17)

The bootstrap capsule and request JSON are transient inputs. After initialization completes or raises, replace Python's saved_state global with None and drop the consumed worker message state. After a request completes or raises, clear the Python request_body global and consumed message body before exporting durable state. Preserve the serialized queue, result/error protocol, SQLite contents, export/restore verification, immutable forecasts and every personal/model gate. Releasing these buffers must not clear or reinitialize the active runtime's authoritative databases.

Verify the compiled compute host under the native CSP, including malformed JSON followed by a successful read of the same saved portfolio. Use the actual synthetic520-session SQLite capsule for restore→POST→new-context restore and compare every mobile table's schema, ordered typed-cell hashes and acquisition receipts. Distinguish the mocked desktop native bridge from Android Java/Keystore and physical-device acceptance. Separately profile the full5000-symbol WASM feature-input path under unchanged600-second/3500MiB observation budgets; do not count a PC feature result or a state-only roundtrip as that path's success. Preserve failed attempts and numerical/source identities.

### D133 — observe the original WorkRequest through current scheduler mappings (2026-10-17)

An OS scheduler integer recorded before process loss/reboot is not sufficient to identify the original WorkRequest later. The disposable-emulator controller must read an observational copy of the current WorkManager DB/WAL, verify the original UUID and DailyWorker class, and select SystemIdInfo only for that WorkSpec's current generation. Keep the prepared scheduler identity and every current observation in evidence. Reject invalid UUIDs, ambiguous mappings and foreign workers. Copies may be read from the no-backup path or the older database path; never open a device DB as a second writer. [AndroidX generation-aware mapping](https://android.googlesource.com/platform/frameworks/support/%2B/44f40c685c0814c5a866c0ef37f18350165043d3/work/work-runtime/src/main/java/androidx/work/impl/model/SystemIdInfoDao.kt).

Only run an existing mapped original job with all constraints satisfied. If that job disappears between observation and dispatch, re-observe the same UUID once; never select an arbitrary pending job. Running/finished/blocked or not-yet-registered work and unsatisfied constraints remain within the existing bounded ACK observation. An unsuccessful terminal original WorkRequest fails acceptance. Preserve the original WorkInfo SUCCEEDED check, receipt/portfolio equality, absence of credentials, sleeping-display observation, existing90/3/200-second windows and explicit intervention policy. Record actual satisfied dispatch separately from observation without dispatch. Do not enqueue replacements, force a run, alter clock/power policy, or invoke instrumentation to cause delivery. A local controller test does not prove real OS recovery.

### D134 — index financial disclosure groups without changing PIT calculations (2026-10-17)

Daily financial expansion may index the sorted disclosure frame by symbol once and select groups by positional row indices, instead of scanning every disclosure for every symbol. Preserve disclosure ordering, actual receipt times, both historical revision policies, same-timestamp tie handling, missing-symbol behavior, asof joins, numeric formulas, output types/order and the original input frames. Clear the temporary per-symbol frame list after concatenation before making the two output projections. Keep the full market population, history, source identity definition and verification, feature formulas, model/adoption gates and existing capacity/time budgets.

Verify correction ties, categorical/unused symbols, duplicate source indices and missing financials in public tests. Compare the exact previously committed function on deterministic fixtures, then check all full-market latest features and source identities under the unchanged resource guards. A small fixture parity test or input-only performance profile does not establish full-market WASM, native bridge, forecast or phone acceptance.

### D135 — decode numeric columns without per-scalar row containers (2026-10-17)

The mobile input transport may read a single column through Series values JSON instead of constructing a one-column DataFrame JSON with one nested row per scalar. Preserve the shipped records JSON's exact scalar values, inference, precision and null behavior, including nullable numeric/bool, large values, nonfinite input, Decimal and nested values. Keep the existing string/date deduplication and fallback cases, all input frames, source identities, frozen feature selections, formulas and forecast/decision gates.

Use the independent records reference and PC/WASM feature/quantity/restore comparisons. Measure large deterministic numeric columns in isolated processes against the exact prior function and distinguish that narrow memory/CPU result from full-market or phone acceptance. Retain failed full-market attempts and unchanged resource limits.

### D136 — release completed PIT join and OHLC inspection frames (2026-10-17)

After the daily-price membership join finishes, drop its no-longer-used membership frame. After constructing the no-trade mask, drop the OHLC/OHLCV inspection frames before adjustment reconstruction and later copies. Change only temporary reference lifetimes; preserve input copies, provider-code joins, adjustment reconstruction, missing/no-trade behavior, validation, source identities, formulas and full market/sector populations.

Run the production and mobile numerical/source regressions, then measure the complete synthetic history under the unchanged limits. Keep the preceding Linux memory-budget failure and WASM time-budget failure as separate evidence; successful small tests or a Windows result do not establish their resolution.

### D137 — follow native retries while preserving one controlled delivery (2026-10-17)

A WorkRequest observed RUNNING may lose connectivity and return to ENQUEUED with a different scheduler mapping during the existing ACK window. If no `run -s` command has yet been sent in that phase, observe the same UUID/current generation every 10 seconds within the same 200-second window. Only an ENQUEUED original DailyWorker whose native `get-job-state` output is exactly `ready` may consume that unused controlled delivery. An already attempted command, including a constraints refusal, prevents another command through this observer. Preserve the existing disappearing-job race handling, guard, original WorkInfo SUCCEEDED, receipt/portfolio equality and 90/3/200-second windows. Record native readiness, retry mapping and actual intervention; compute the delivery label after observation completes. Do not reenqueue, force a run, change clock/power policy, or accept a different work item.

The fa45b94 emulator log identifies stop reason 7, followed by RETRY and an original ready job 8; this does not establish natural delivery timing or Xiaomi behavior. References: [WorkInfo connectivity stop reason](https://developer.android.com/reference/androidx/work/WorkInfo#STOP_REASON_CONSTRAINT_CONNECTIVITY), [AOSP job-state command and flags](https://android.googlesource.com/platform/frameworks/base/+/c7f321a19798fad6277ff31d13b461d928bf6f4d/apex/jobscheduler/service/java/com/android/server/job/JobSchedulerShellCommand.java). Preserve the separate manual-unforced 200-second observation without a retry observer; do not lengthen any window to accommodate this failure.

### D138 — construct PIT membership intervals in one ordered frame (2026-10-17)

Construct intervals from symbol boundaries and consecutive authenticated session positions in one ordered frame. Deduplicate dates before building the observed-date set and format each successor date once, retaining the existing ISO parser. Preserve the complete historical population, exact snapshots, gaps and relistings, whole-symbol exclusion when any date lies outside the requested calendar, null/unused-category behavior, optional columns, values, dtypes, ordering, exceptions and input immutability. Compare with the exact previous implementation across categorical/string/object symbols, shuffled or duplicate indexes, timezone-aware dates and empty/invalid inputs. This changes execution only, not membership or source identities.

### D139 — evaluate only the final complete drawdown window in latest snapshots (2026-10-17)

For latest snapshots, compute the final 60/120-session maximum drawdown with the same kernel over the complete final window instead of evaluating every historical rolling window whose value is discarded. Preserve missing/nonfinite handling and warm-up, reset across trading-session gaps, all other indicators and recurrent history, full source validation, and the full-history transform used by research. Compare latest results exactly against the unchanged full rolling history, including window boundaries, missing prices, gaps and older last dates. Keep formulas, feature manifests, all symbols/history, immutable predictions and share proposals, and the 600-second/3500-MiB acceptance limits unchanged; measure PC/WASM full-market results separately.

### D140 — reuse verified column tokens only while current compressed bytes match (2026-10-17)

Within a PIT read, retain immutable verified reference tokens and their UTF-8 expansion length in the existing bounded LRU, sharing its limit of 128 entries with parsed scalar columns. For each document and referenced digest, query the current SQLite BLOB even on a cache hit. Reuse only when its compressed bytes exactly match the verified entry; otherwise inflate and validate its full digest/types again. Missing columns, changed data, trailing compressed content and expanded-size violations still fail closed. Preserve descriptor/tag/presence/count validation, raw record hashes, exact normalized row-JSON verification, complete source identities, wire format and both PIT passes. A constant already validated as a string and an immutable tuple already validated element by element do not need another per-cell type scan.

Compare raw records, original normalized bytes, dtype profiles and complete materialized frames with the previous implementation, and exercise cache-hit corruption and recompression explicitly. Rebuild the shipped archive and check actual WASM before measuring full-market effects under the unchanged 600-second / 3500-MiB limits. This read optimization does not alter feature formulas, histories, source populations, immutable forecasts or shares, adoption gates, research state, or native encrypted-state behavior.

### D141 — batch canonical daily financial joins with the same PIT semantics (2026-10-17)

For non-null string symbols, unique UTC/ns cutoffs and plain int64/float64 closes, join all financial rows once using temporary int64 symbol IDs and the same backward asof/exact-match and disclosure tie rules. Calculate every disclosure's existing fiscal/revision features before selection. Keep absent-source rows in their original typed partition before concatenation, preserve ratio arithmetic and symbol/cutoff output order, and drop temporary IDs. Release consumed frames and avoid copying a single partition. Other input layouts retain the existing per-symbol path, including categorical empty groups, unusual numeric types and duplicate cutoffs. Validate against the exact previous function, including empty/future/missing/nullable sources, both revision policies, index duplication and actual fast/fallback dispatch. No population, history, source-identity, formula or acceptance-budget change.

### D142 — assemble each symbol's feature frame once (2026-10-17)

Keep the existing indicator Series and their insertion order in a dictionary, then construct one DataFrame instead of inserting every column into a growing frame. Preserve all calculations, recurrent history, full-history and latest modes, column/index/dtype order, attrs, duplicate-label flags and input immutability. Compare all returned cells with the frozen previous engine across manifests, date gaps, missing inputs and nondefault metadata; rebuild and verify the actual WASM/PC feature, model, quantity and restore paths. This changes frame assembly only, not feature definitions, selections, source proofs, forecasts, shares or resource limits.

### D143 — batch the same indicator formulas over matching session grids (2026-10-17)

For latest snapshots only, compute independent stock columns together when their entire trading-date arrays match and any explicit trading-session indexes are consecutive. Bound all pending groups together to128 stocks, including distinct IPO grids. Keep irregular histories on the previous per-symbol path with the same segment resets and validation. Keep the full-history transform and every input row, source identity, feature, warm-up rule, missing-value convention and output dtype/order unchanged.

Share one indicator expression implementation between Series and matrix inputs. Wilder recurrence must seed each column using the original one-dimensional NumPy mean and preserve multiplication/addition/division order; missing rows preserve the previous state without advancing event counts. True range and candle bounds must reduce within a stock, never across stocks. Latest drawdown still uses the entire exact final window. Compare independent columns and frozen Git implementations exactly, then rebuild the bundled WASM and run full5000-stock/520-session PC and WASM probes under the unchanged600-second/3500MiB limits. This does not prove native Java bridge, physical-device, model or live-account acceptance.

### D144 — exercise a valid full-history SQLite capsule through the actual native owner (2026-10-17)

Add a separate controller-only API35 emulator suite for a valid5000-stock/520-session synthetic SQLite capsule. Prepare it from the same run's completed initial-download capacity fixture, verify the exact generation-source hashes, normalize copies with the current runtime, and prove restoration preserves all17 mobile table schemas and canonically ordered typed cells. Keep the capacity source untouched. A historical fixture with different source hashes must be rejected rather than relabelled as current evidence.

Seed the isolated native encrypted database in256KiB fragments using the existing authenticated chunk format. Do not allocate the complete test input String; the first full read, JSON transfer, WASM restore, export and commit must be the production owner's actual path. Check health/order prohibition, all520 received days, a synthetic empty-profile POST and recreation of the owner, then export authenticated native chunks incrementally for independent PC verification of all mobile tables and the saved profile. Keep the existing native192MiB heap and128MiB character limits and all production timeouts. Record phase-only metadata and relevant capacity stacks; an opaque-store or desktop mock result cannot substitute for this test.

For this isolated test only, allow a same-run artifact containing the newly generated synthetic capsule and separate debug/test APKs, retained for three days. Never commit or package the capsule, include private data/models/keys, or use another run's artifacts. Download with read-only Actions permission after the original Android job; exclude the controller suite from the existing regular native tests, retain those tests, and require the new job before any existing release workflow can proceed. A missing fixture, failed production bridge or incomplete typed-cell proof must fail this gate. Actual execution is required before claiming native full-history acceptance.

Gate execution of the independent full-history job on successful upload of the same-run compiled APKs, so a later OS-delivery failure does not suppress the additional capacity evidence. Keep the OS failure and every original acceptance condition intact. Release still requires verify, the original Android job and the full-history job all to succeed. Do not widen delivery windows or change scheduler constraints to obtain a passing result.

### D145 — assemble frozen table JSON with column iterators (2026-10-17)

When validated columns are lists/tuples of the exact requested length, zip the columns into rows and join key/token pairs with the standard native map/add iterator. Preserve the exact existing token spelling, escaped names, schema text, field/row order and returned bytes. Retain the previous indexed path for empty columns, other containers/count types, requested-count truncation and mismatched lengths so legacy results and exceptions remain unchanged. Keep full raw-record and normalized-table authentication, column rereads and cache bounds, all source identities, numeric formulas and the existing capacity/time limits.

Verify exact byte/error parity against the frozen prior implementation and real persisted batches before measuring the compiled WASM and full5000-stock/520-session path. Input-only samples are diagnostics, not full native/model/phone acceptance or a universal speed guarantee. Preserve the earlier archive and failure evidence.

### D146 — transfer native owner state through bounded authenticated chunks (2026-10-17)

The first actual full-history native baseline failed in JSONObject/JSONStringer while allocating the initialization command under the existing192MiB Java heap. Replace complete capsule strings in Java command/reply JSON with sequential256KiB bridge calls. Authenticate the incoming envelope/generation, each AES-GCM chunk, exact total/hash and final chunk count before posting assembled input inside the renderer to the worker. Keep legacy inline and valid variable-length stored chunks readable. Do not increase the heap, character, timeout or acceptance budgets.

Stage outgoing chunks as authenticated ciphertext in an application-private, single-use cache file. Bridge callbacks must not write authoritative SQLite tables. On the serialized owner queue, check generation CAS and revalidate every bounded frame, authentication tag, total length, hash and EOF inside the existing atomic state transaction. Only acknowledge after durable commit. Abort or close removes the spool; a new process removes abandoned files with the owned prefix. Reject incomplete, duplicate, reordered, stale, corrupted and trailing data while preserving the previous state. Keep the existing encrypted storage format and full-state backup interface; the latter still requires its own full-history acceptance.

Test the production browser host with actual offline Python and bounded protocol failure cases, add isolated native rollback/legacy/cryptographic tests, then repeat the unchanged real full-history owner/recreation/all17-table gate on CI. Desktop mocks or the earlier opaque-store result cannot establish native full-history acceptance. Preserve the original OOM evidence and all OS-delivery gates.

### D147 — transfer one owned byte buffer and distinguish renderer exits (2026-10-17)

The bounded Java protocol passed the regular native/OS suite, but the actual full-history baseline next exited through onRenderProcessGone during initialization. The previous collection did not distinguish a renderer crash from an OS kill or identify the worker stage. Preserve that failure without asserting a memory cause.

Capsules are ASCII base64. Encode authenticated input fragments directly into one bounded byte buffer, then transfer its ownership to the worker instead of retaining, joining and cloning complete host strings. Decode inside the worker and keep the existing Python validation, database bytes and state export. Transfer output ownership back as bytes and decode only256KiB at a time in the host for native encrypted staging; reject full-string native worker responses. Check the128MiB bound before encoding output and preserve the direct worker string interface. Verify real offline restore in a new page, actual buffer detachment, valid variable-length chunks and failures before allocation or dispatch.

Track only fixed stage enums; retain crash/kill and the last stage in the internal renderer-exit error. Debug builds may record aggregate Java/system memory, never state contents. The guarded CI controller may retain bounded fixed-stage and renderer/LMK events while excluding general console/application payloads. Keep all emulator, heap, timeout, OS-delivery and full-history acceptance conditions unchanged. Require actual native success before claiming full-history support.

### D148 — connect saved development predictions and raw market prices to pretax NAV (2026-10-17)

Reuse the existing daily strategy and NAV ledger; do not retrain or recreate the candidate matrix. Pin the market projection bytes/windows and saved daily forecast bytes/times, authenticate the frozen feature selection, and require exact forecast/dataset identity and unadjusted closing valuations. Keep closing outcomes separate from historical decision inputs. A non-unit adjustment factor requires an independently evidenced split with a matching ratio; unit factors and empty event arrays never establish complete corporate-action coverage.

Require reviewed, pinned evidence for decision-time inputs, corporate-action coverage including no-event intervals, execution/settlement and costs. Missing evidence produces a measured BLOCKED receipt without inventing a performance result. Preserve missing marks and future listings; do not select a surviving universe or drop unavailable holdings. Use the same initial state and cost/settlement rules for strategy and HOLD. Personal taxation is a separate step and does not delay pretax research. Freeze model, trading rules and adoption criteria on development data before the existing single-use final evaluation; this connection never opens holdout, adopts models or sends actual orders. See REAL_MARKET_NAV.md.

### D149 — stream state export and portable backup through authenticated bounded stages (2026-10-17)

The49c6994 full-history native run restored Python but crashed the WebView renderer at export; retain that failed result and the separate OS reboot connectivity failure. Stream SQLite backup files into the existing ZIP and encode only196608 raw bytes per256KiB native base64 fragment. Wait for each native staging acknowledgment before producing another fragment. Preserve the desktop/legacy capsule interface, database contents,128MiB native/backup limits, generation CAS, authenticated encrypted staging, atomic commit and all existing acceptance budgets.

Keep the STOCKAIB1 wire format, PBKDF2-SHA256 parameters, AES-GCM header/AAD/tag and legacy interoperability. Use the pinned Bouncy Castle1.86 lightweight streaming cipher without registering a global provider. Its decrypted fragments remain in encrypted application-private quarantine until complete JSON/length/EOF/GCM authentication. The UI receives only a single-use preview token and character count; confirmed restore consumes it, verifies the current generation, validates the SQLite capsule in the actual interpreter, and acknowledges only the durable commit. Cancellation, stale previews and failures discard quarantine while retaining the preceding committed capsule.

Extend the actual full-history CI gate to export/preview/restore the same large B1 backup, recover the prior profile, recreate the owner and compare every original typed table. Pin the new crypto/backup/build/test sources in that same-run fixture. Keep the192MiB Java heap and original native/OS time windows. PC/JVM/browser results do not establish Android full-history acceptance; require the unchanged real gate before claiming support.

### D150 — observe native bridge completion independently of JavaScript dispatch (2026-10-17)

The8cea2d0 CI passed Android78 tests and all three OS recovery phases, but a browser transfer test returned the async dispatch Promise to Playwright. Chromium reported that Promise garbage-collected in the non-ASCII rejection case before the bridge reply assertion. Native evaluateJavascript dispatches without awaiting that return; the authoritative completion is the existing authenticated bridge callback.

Make the test dispatch return void and retain every completion, rejection, output, ownership-transfer and ACK assertion. Do not change the product, time windows or retry policy. Verify all10 transfer cases repeatedly and run the unchanged real offline host path on CI. Preserve the failed run; it produced no full-history fixture because Web verification failed before capacity preparation. Its subsequent missing-artifact failure is not a native full-history execution result.

### D151 — preserve dividend notice chains and dated entitlements (2026-10-17)

Connect pinned J-Quants V2 dividend responses to the existing NAV action contract. Keep forecast and decided series separate, resolve corrections/deletions through their original CARefNo, and use independently evidenced availability rather than reference-number order or publication time alone. Require decided terms known at entitlement, matching record-date/entitlement share units and separately evidenced actual cash release. Never add special/commemorative breakdown amounts to the declared per-share total or convert unknown amounts to zero.

A later correction, deletion or changed ex-date cannot replace an already accrued historical entitlement. Report the need for an explicit ledger adjustment and withhold the action list until supported. Preserve pending future entitlements, ambiguous/missing chains and unsupported capital distributions as explicit states. An empty or successful dividend projection never certifies complete corporate-action/no-event coverage. Keep the development boundary, source hashes, existing accounting, personal-tax separation and no-order rule. See DIVIDEND_DATA.md.

### D152 — distinguish filing loss relief from spendable sale proceeds (2026-10-17)

Keep the existing user-supplied, versioned tax policy and economic filing estimate. Estimate broker cash withholding independently from the current account's year-to-date gain change, without prior-year loss carryforward. Never turn estimated loss relief into an immediate cash refund. Allocate each aggregate once in its own decimal quantum using integer units and exact weight ratios; preserve signed economic totals and nonnegative cash totals without charging a zero-weight loss line for rounding residue. This is not a broker-specific yen rounding rule.

Expose economic tax and withholding separately through the existing API and cash/stock details. Preserve the simple layout, original predictions, old immutable proposal receipts and current tax-input gates. Existing implementation hashes distinguish new calculations. Verify the corrected cash budget through ordinary/bounded search and actual offline WASM. Keep pretax NAV independent. Actual tax basis, eligibility/annual carryforward, account/dividend netting and dated tax cash flows remain required before claiming a complete personal after-tax evaluation.

### D153 — import native capsules without a complete Python base64 string (2026-10-17)

The0a5d342 full-history Android run initialized, committed and recreated the real SQLite state, exported B1 and authenticated its preview, then crashed the renderer at the archive stage of backup restore. Preserve that partial result; neither a Java OOM nor a specific system memory limit was established. The worker still converted the entire native byte buffer to a JavaScript string and then a Python string before decoding the ZIP.

Keep native input as the transferred byte buffer and pass at most256KiB of base64 to Python at once. Strictly check total length, order, fragment length, alphabet, padding and completion while decoding into one temporary ZIP. Stream each SQLite member into temporary files, validate every member and its integrity before replacing any database, and close all temporary files on failure/cancellation. Retain the legacy complete-string interface and its format. Native generation CAS, encrypted quarantine/commit, B1 authentication,128MiB capsule/256MiB database limits and existing heap/time/full17-table/OS gates stay unchanged. Require the actual Android gate before claiming full-history support.

### D154 — distinguish ChatGPT connection failures without changing account or model (2026-10-17)

Use the provider's structured error code to distinguish unsupported model/reasoning/search combinations, invalid client/route, signed permission/identity failures, absent search/citations, incomplete streams and cancelled authorization. Display the corresponding next step in both connection settings and research. Preserve selected settings and prior results, and require the existing explicit actions for retry, sign-in or model changes. An admission401 alone does not prove a revoked refresh token; never start an OAuth loop or silently switch billing/model. Existing native credential/refresh behavior stays unchanged.

The2026-10-17 official [Errors and recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery) and [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference) support these distinctions. Documentation/source correspondence and mocked tests do not establish this account's entitlement or search capability; completed real inference is still required. Add the cost/tax unit suite to CI so the independent withholding and aggregate allocation checks run there as well as locally.

### D155 — preserve manual execution input and make exact record retries harmless (2026-10-17)

Separate initial-load failures from record/apply failures so an invalid entry keeps its editable fields. Serialize UI mutations, retain one execution ID and frozen input for an unchanged retry in the open page, disable an acknowledged entry until edited, and disable repeated portfolio application after acknowledgment. Keep the existing manual-record intent and no-order boundary.

Exclude the same immutable execution ID from the cumulative-fill comparison, then enforce the existing full payload/hash equality. A different record ID still counts toward the selected quantity and changed content under the same ID still conflicts. The manual API commits a new execution and its daily status in one SQLite transaction; an exact replay changes neither balances nor a later status. Verify failure rollback and single application to the next portfolio. Keep original proposals and saved receipts unchanged. Preserve48px controls,12px spacing, unbroken share quantities and a full-width execution timestamp at320/390px with150% text.

### D156 — retain bounded compute stages in OS recovery failure evidence (2026-10-17)

The6b250b9 run passed ordinary Android tests but its reboot delivery observation ended with the original pending acquisition unacknowledged. Preserve the failure and do not infer a memory, connectivity or application cause from that alone. In the guarded disposable-emulator controller, retain only the existing fixed compute-stage enums and aggregate memory fields from their dedicated log tag, up to500 complete records. Exclude console text, unknown stages and appended payloads. Keep all deadlines, original-work identity/dispatch checks, native capacity and release gates unchanged.

### D157 — consume NISA capacity on actual fills and use JST tax years (2026-10-18)

Apply the declared remaining-purchase-notional basis to manual NISA fills. Subtract only actual filled shares times price from each known annual/lifetime capacity once, not ordered shares or commission/other expenses. Preserve null inputs; floor known exhausted capacities at zero while retaining the actual recorded trade. Do not replenish capacity on sales or infer next-year allowances/reuse, eligibility or filing carryforward. Keep the existing manual-input reconciliation and immutable execution replay guards. This is a ledger correction, not a complete personal after-tax NAV or certification of broker capacity. The [FSA explanation](https://www.fsa.go.jp/policy/nisa2/know/index.html) says sold book-value capacity can be reused in following years; verify the actual year/account evidence separately.

Determine execution and next-state tax years in Asia/Tokyo, including CSV balance reconciliation. Equivalent UTC/JST timestamps must produce the same YTD reset and preserve the current year's actual gains. Keep the existing user-supplied carryforward/capacity review requirement and dated tax policy; do not silently renew tax inputs. Verify actual manual record/replay/application, durable state, next-decision purchase limits and offline backup restoration. Keep pretax research independent; no training, holdout access, adoption or actual order.

### D158 — cancel the stopped worker's own queued or running core request (2026-10-18)

Bind cancellation of each LocalComputeOwner result to its executor task. A cancelled queued operation must not execute; release its queue allowance once. Interrupt a running operation's wait and let its existing host/staging cleanup finish on the serialized owner thread before the next caller runs. Never roll back an already committed generation or interrupt a different caller. Keep the64-operation limit and native commit/authentication/CAS guards.

DailyWorker retains only its current local-core future under a lock. On the OS stop callback, interrupted wait or timeout, cancel that future; an already stopped worker must not enqueue another core request. Keep the existing660-second wait and bounded journal retry policy. Do not cancel/reissue a provider request or discard its durable recovery journal. Verify queue cancellation, running interruption, capacity accounting, committed profile preservation and an unaffected neighbouring caller. This repairs a reproduced cancellation defect; the repeated reboot ACK failure still requires the unchanged emulator delivery/identity checks and cannot be declared solved by a JVM probe.

### D159 — reject invalid manual execution times before saving and return recoverable apply errors (2026-10-18)

Use the API's aware clock to reject naive/future manual execution and application times before writes. Map invalid execution-model input to422 with a fixed Japanese explanation. Enforce a strictly later portfolio cutoff against the latest state inside the store transaction; report stale/repeated applications as409 and invalid transition inputs as422. A rejected request preserves the ledger, pending executions and NISA capacity, and a corrected record may use the same previously rejected ID.

Keep the existing manual-intent header, immutable record/content checks, atomic execution/status save, actual-fill-only application and no-order boundary. Do not turn a rejected duplicate application into a success or clear its pending input. Existing UI errors retain editable fields; add no controls. Standalone research/simulator inputs remain explicit and are not restricted to the API clock.

### D160 — keep personal tax NAV causal and distinguish broker tax accounting from the simplified ledger (2026-10-18)

Implement the full connection described in [PERSONAL_TAX_NAV.md](PERSONAL_TAX_NAV.md) separately from pretax research. Tax recognition, cash settlement, buying-power release and refund dates are separate inputs. Same-day specified-account acquisition accounting must use actual daily fills after they occur, without reordering cash execution or exposing future fills to the decision. Current chronological average costs and execution-year YTD bookkeeping are not a broker annual-report certification.

Carry dated loss cohorts/eligibility and NISA purchase book values under explicit frozen policy, and never fund a purchase with an unreceived filing refund. Reuse the event-based ledger and Decision Engine; a posthoc tax overlay cannot stand in for a causal after-tax strategy. Preserve unknowns and the existing adoption/holdout gates. This decision fixes the implementation contract and authoritative references; the personal tax NAV integration is still unfinished.

### D161 — compute exact daily acquisition basis from received actual fills (2026-10-18)

Add a pure research component in `ml/tax_acquisition.py` for the specified-account daily buy pool. Require a day-opening tax book before the JST trading date, separate opening/receipt timestamps, a source identity and unique actual-fill IDs/execution sequences. Validate actual chronological share availability before applying the tax pool; a later buy must not make an earlier unheld sale valid. Return each sale's signed proceeds/cost/basis/PnL and the remaining book by account bucket and symbol, available only at the declared known time.

Use exact Fraction amounts for tax basis, including purchase expenses, and preserve the total basis through repeating fractions and next-day carry. Do not silently apply broker monetary rounding, derive a tax year from execution time, move cash, infer NISA eligibility or update the operational ledger. The next integration must supply the D160 tax-recognition/payment/year policies and connect actual tax state to subsequent decisions. Keep current runtime/feature/model source unchanged; this component alone is not an after-tax NAV result or adoption evidence.

### D162 — daily evaluation and manual ChatGPT integration take priority (2026-10-18)

Apply the owner's revised scope in [DAILY_INTEGRATION_CONTRACT.md](DAILY_INTEGRATION_CONTRACT.md). Preserve the current branch, private artifacts and D161's tested component; defer further personal-tax NAV/advanced optimizer development. Work on Android recovery, market readiness and the existing 18 daily 5d/20d candidates independently under the existing resource limits. Reuse authenticated OOF/manifests; do not restart training or open final holdout. Compare candidates with common fixed research trading/allocation rules, separate price-only after-cost, dividend-inclusive and personal after-tax evidence, and retain every incomplete candidate and missing-data reason.

The primary ChatGPT path becomes manual prompt copy/share plus strict answer JSON import. Supersede the old qualitative-only/no-allocation scope for this new path: ChatGPT may suggest target shares and allocation, while the app computes deltas/costs and validates all configured constraints. Do not alter original model evaluation or operational balances on import. Preserve existing optional account integration and safe features, but apply the same external-data permission checks before sending real data.

The official J-Quants FAQ now explicitly allows generative-AI input only under four personal/private/non-training/non-publication conditions. Pin the reviewed source and exact exported field projection; owner/service settings remain unverified until confirmed. Default real external export off while proceeding with synthetic integration. Aggregation alone is not permission. Keep adoption, unseen final test, PC/device parity and actual-fill-only ledger gates unchanged; a research-only or no-adoption result is valid.

### D163 — bind manual ChatGPT target shares to the exact input and current data entitlement (2026-10-18)

Implement [MANUAL_CHATGPT.md](MANUAL_CHATGPT.md) on the existing local SQLite/native owner and Decision Engine evaluator. Export only top20 plus every actual holding, account aliases, known predictions/risk and necessary owner constraints. Bind schema, times, source snapshots and validator hashes to a content-addressed input; require a complete unique target-share answer. Reject malformed/duplicate-key/nonfinite/oversized JSON, stale or changed inputs and constraint violations without repair. Store the raw answer and immutable review separately; never apply it to balances or tax records. Preserve actual-fill-only application, serialization and backup integrity. The existing optional provider claim must have service-specific dated permission before creating an external request; cached completed reads remain local.

The owner confirmed the manual ChatGPT privacy/non-training/personal-use conditions, then reported that the current J-Quants subscription is unconfirmed and may be inactive. This is not data entitlement. Pause additional acquisition, real-data export/transmission and new real-market PnL computations until the applicable contract/data-use scope is confirmed. Preserve saved originals and evidence without unconfirmed deletion, retain the existing403 response, make no repeated entitlement probe or new paid subscription, and continue synthetic implementation/tests. Do not transfer manual ChatGPT attestation to the optional account service.

Reuse the18 authenticated OOF candidates and retain396 reconstructed fold intervals; provenance proves the linked report/checkpoint metadata, not a complete holdout access audit or inference-weight availability. Freeze a separate simple research trading policy before NAV results:10million yen,top20,90% equal allocation,100-share lots,20bps one-way all-in costs and separate5/20-session rebalance schedules. Keep existing stateful NAV and prefunded buying power. Synthetic hand checks certify arithmetic only; missing market actions/fills/settlement/PIT/rights keep real NAV and final adoption pending.

### D164 — resume the exact saved manual input and revalidate immediately before copying (2026-10-18)

A recreated Android page must resume a still-valid saved prompt with the original input ID, bytes and expiry. Return it from the existing local status route only after authenticating the metadata, matching the current comparison/snapshot/validator and rechecking the original service-specific permission. Reading must not generate another export, extend permission or change the ledger. Keep expired originals and answer history but do not reoffer an expired or changed input for copying.

Before the explicit clipboard action, re-read that local status and require the same record ID, snapshot ID and prompt. A missing/expired/changed context or a failed local check must prevent clipboard writes; retain the editable answer and serialize page operations during the check. Reuse existing storage/native ownership and schema, with no new data acquisition, external provider request, model adoption or order capability. This closes a reproduced handoff recovery gap; data entitlement remains unconfirmed and synthetic tests do not establish actual-account or Xiaomi acceptance.

### D165 — compare daily model families across all seeds and predeclare the inference seed (2026-10-18)

The legacy development selector picked the strongest individual seed. For new daily5d/20d freezes, compare complete family/task groups using the arithmetic mean across every declared seed: higher daily Rank IC for regression, lower pinball loss for quantile and lower Brier score for large-loss probability. Compare regression/ranking fallback groups on their mean meta-evaluation Rank IC. Reject missing, duplicate, mixed-horizon or nonfinite seed evidence rather than selecting a surviving subset. Retain per-seed reports and stability evidence; a family mean is not a performance certificate for its representative.

Predeclare the minimum declared seed as the single inference representative, independent of observed scores (17 for the existing17/29/43 set). This keeps inference size bounded without selecting a lucky seed or adding retraining. Store the explicit `family_seed_mean_*__fixed_min_seed_v1` metric name and family mean in the existing hashed selection artifact. Keep historical artifacts readable and the legacy three-horizon behavior unchanged; do not relabel old selections as this policy. An ensemble must still beat the strongest individual meta-evaluation component, not the weaker fixed representative or family mean. Preserve all existing NAV/adoption/holdout gates.

This specifies the development OOF selector before any new real-data selection. It does not freeze an actual family, create weights, run market NAV, open holdout or certify adoption. Applicable J-Quants rights remain unconfirmed. Operational development comparison must still precede the full candidate/rule/criterion freeze and the one-shot unused final test; failure of the predeclared seed is not permission to try another seed on that final period.

### D166 — explicitly separate price-only market NAV from dividend-inclusive coverage (2026-10-18)

The owner prioritizes a price-based, after-cost, pre-tax comparison without dividend data. Extend the existing market NAV connector with an explicit `price_only_research` evaluation tier. Keep the historical default `dividend_inclusive_research` for older requests; never silently narrow their evidence requirements. Return the tier and dividend treatment in both CLI output and complete/blocked receipts. Price-only means `excluded_not_assumed_zero`, not proof of zero distributions or a total-return evaluation.

Require reviewed non-dividend action coverage for splits/consolidations, cash conversions and other rights across the full interval, with all scoped event IDs and pinned evidence. Reject dividend events in price-only input before opening market files rather than silently dropping them. A narrowed coverage scope cannot satisfy a dividend-inclusive run. Keep unadjusted prices, unresolved-adjustment rejection, directional fills, settlement/funding, costs, point-in-time and saved-forecast identity checks unchanged. Preserve research-only/non-adoption and locked-holdout boundaries; do not change the trading/allocation rules or add optimization.

This is contract-independent implementation verified only with synthetic accounting evidence. It does not authorize saved market-data use, invent missing action evidence, execute the18 real-model comparison, freeze candidates/rules, open final holdout or send any order. Existing dividend accounting and the optional dividend-inclusive route remain available under their original evidence conditions.

### D167 — resume Light-scoped research with a separately pinned market vintage (2026-10-18)

The owner confirmed a new Light subscription. A single TOPIX request succeeded with HTTP200, followed by acquisition of the five supported core datasets into a separate private store for July2024–February2026, before the locked final boundary. Supersede D163's blanket entitlement pause for confirmed current-plan operations. Preserve the earlier403 and Standard originals; do not overwrite, delete, mix old raw/targets into the new market evaluation, claim that all former Standard data is now authorized, or assert that reacquisition is a contractual requirement or resolves historical use. Choosing a new acquisition provides explicit current entitlement/source/version evidence. Keep credentials, model artifacts, market rows and derived comparison details private.

Reuse authenticated stored predictions without relabeling their original training source identity. Rebuild next-session-close5/20-session labels from the fixed new Light prices, with adjustment factors applied once and exact exchange-session endpoints. Compare all18 regression heads on identical within-horizon keys, retain all seeds, missingness, per-period stability and descriptive dependent-sample uncertainty. Other heads, stateful after-cost NAV, baselines/ensemble, candidate/criterion freeze and unseen final remain separate unfinished steps. A current corrected single vintage is research evidence and cannot certify historical known-at inputs or adoption.

The first common full month is a source/authentication connection check, not a selected profitable interval. Preserve unknown directional execution, tick/capacity, settlement/funding, non-dividend action coverage and decision PIT evidence. Record prerequisite failure and elapsed time without manufacturing a NAV return or marking the strict evaluator complete. Personal balances and dividends are not prerequisites for the price-only research route. Keep service-specific external-export permission/snapshot checks, actual-fill-only ledgers, resource guards and all final/adoption gates; do not auto-enable the app's permission checkboxes, retrain, send an external AI request or place orders.

### D168 — recover dated domestic lot/tick rules without replacing unknown execution evidence (2026-10-18)

The saved Light raw master includes `ProdCat`, although the older normalized master does not retain it. Reuse immutable raw/normalized authentication and the existing pre-open holdout guard in a separate instrument-rule projection. Authenticate product/date/code lineage rather than rewriting frozen sources or defaulting all eligible-market stocks to domestic shares. Select one full master snapshot per source date under the frozen receipt cutoff, including empty snapshots; a newer snapshot must not inherit removed members from older versions. Preserve price-only and master-only keys.

Apply the published domestic100-share rule only to proven domestic ordinary-share codes and supported dates. Derive tick size from the same day's size category and unadjusted reference price using the published TOPIX500/other table. Bound the supported tick regime to2023-06-05 through2027-02-28 because a different regime is announced from2027-03-01. Keep foreign/missing product classes, nonordinary provider codes, missing prices and unknown size categories unresolved. Do not round prices, infer a missing category, treat an observed close as an executable trade or silently remove a held security.

Keep dated rule references, original source object/record hashes and later-vintage timestamps. The projection is research-only, as-revised and not adoption/evaluation-ready; it cannot satisfy corporate-action coverage, directional status/capacity, buying-power release or historical known-at evidence. Keep existing NAV/adoption/holdout constraints and raw price/feature identities unchanged. Do not add optimization, training, external AI transmission or orders.

### D169 — predeclare conservative research funding independently from broker settlement evidence (2026-10-18)

Before any new market NAV result, fix the common research policy `t2-equity-calendar-proxy-t3-0900-jst-v1`. Use the authenticated cash-equity business calendar as an explicit settlement-calendar proxy to derive the T+2 date; delay buying-power release until09:00 JST on the third following cash-equity session. The latter is an additional conservative research assumption, not an exchange/broker rule or proof that settlement completed. Retain `broker_verified=false`, historical known-at limitations and existing NAV/market/adoption gates. Do not introduce same-day funding, change capital/allocation/costs or depend on unentered personal balances.

Require every civil day and valid holiday division. Do not treat OSE holiday-only trading as a cash-equity session, infer missing days from weekdays or extrapolate missing calendar tails. Preserve the proxy settlement date separately when release remains unresolved, and keep those sale proceeds receivable in NAV. Bind a content-identified schedule to the existing NavSession timestamps and validate it before replay rather than silently correcting them. Reuse the existing ledger, including actual released cash, reservations and account buckets; do not modify actual executions or personal cash. Old explicit-input fixtures and contracts remain readable.

Continue all18 saved candidates' remaining ranking/probability/quantile research evaluations on the same pinned Light labels independently of the market NAV prerequisites. Reuse fixed report thresholds/alpha and original prediction identities, retain every seed and incomparable head, and do not train, tune, choose a winning seed or open final holdout. Completing these prediction metrics is not the cost-inclusive model selection or final evaluation.

### D170 — replay saved baselines/ensembles and enforce pinned funding at the NAV entry (2026-10-18)

Reuse authenticated saved baseline predictions and forward ensemble weights/calibration without refitting. Before metrics, declare the existing comparison columns and later-half meta-evaluation boundary. Rebuild labels from the fixed Light price vintage; require exact within-horizon date/symbol/as_of/label_end/fold matches and verify every saved ensemble component against its original candidate prediction. Compare all seeds, family means and dispersion on the same cohort; retain the full baseline cohort and burn-in separately. Undefined IC remains undefined. Date-paired20-session block intervals are descriptive development evidence, with row-equal aggregate losses distinguished from date-equal contrasts. Do not change weights, calibration, thresholds, seeds or adoption criteria after seeing results.

Connect D169's funding projection to `MarketStrategyRequest.research_funding_receipt`. Guard declared final boundaries before opening market/calendar files, authenticate the receipt, match feature/model/calendar/window identities and the same market source vintage, and call the existing funding validator before the existing NAV replay. Record the applied policy and `broker_verified=false`; reject modified, early or unresolved funding instead of repairing inputs. Preserve independently reviewed legacy explicit-funding inputs with a null policy marker. Funding consistency does not replace corporate-action coverage, directional execution/capacity, historical decision evidence or costs. Keep final/adoption gates, private data, Android state and actual-fill-only ledgers unchanged.

### D171 — verify pinned legacy-source APK replacement without clearing prepared data (2026-10-18)

Add acceptance for the last published source, not two differently numbered builds of current code. Export the pinned0.1.12 source into a new isolated directory; authenticate its original files and build its debug APK. Use the same debug certificate/application ID with a higher test-only versionCode for the current APK. Seed only synthetic test-APK assets through the actual legacy plugin, replace using `adb install -r`, and verify UID, certificate, Keystore decryption, native generations, current WASM restore and process reopen. Refuse physical/non-CI devices under the existing disposable-AVD guard. Never uninstall/clear after preparing the old state to repair a failed update, and never use the release key or publish these APKs.

Keep every legacy typed cell, column and schema object; explicitly declare the existing empty-market-table sequence-key migration and the new technical compaction cursor `(1,0,0)`. Require other new model/forecast/decision tables to remain empty. The fixture contains27 legacy tables plus one typed sentinel table, no acquired market history or fitted model, and a single already-applied synthetic execution. Reject same-count content/type changes or unreviewed progress, and never apply the fill twice. Share the existing typed SQLite proof as a dependency-free utility so device controllers need no scientific runtime. Keep fixture bytes pinned with LF endings and outside product APK assets. PC evidence, the controlled debug upgrade, full-history migration, release-signed updates and Xiaomi acceptance remain distinct; adding CI alone proves no device success.

### D172 — capture the same frozen fitted estimator for private portable export (2026-10-18)

The existing frozen-component fit discarded its estimator and fold-local processor after returning predictions, leaving a separate inference/export step liable to require another fit. Add an optional synchronous fitted-model consumer to that existing path. Its default remains absent for OOF and holdout callers; keep estimator factories, parameters, seed, single-thread settings, training-only preprocessing, prediction order and resource controls unchanged. Consumer errors propagate without retry or fallback.

Connect it to the existing PC data-only tree exporter for explicit5d/20d absolute-return regression/quantile/loss-probability heads. Use the same fitted estimator and processor, project probe inputs to features only, bound them to1..1000 rows and compare native/portable predictions with the existing rtol1e-6/atol1e-7 before returning an export. Do not repair mismatches, change weights or fit again for export. Preserve the existing one-class probability shortcut; refuse its portable export because it supplies no fitted estimator. Ranking research and legacy1d paths remain available under their existing contracts but are not mobile return heads.

This helper does not authenticate a frozen selection or supplied training dataset, choose a candidate, create private production weights, persist files, edit a model policy or approve distribution. The caller retains selection/source/label-time/resource responsibilities and the existing bundle/calibration/owner/parity/adoption gates. Verify the bridge and four-head packaging only with synthetic test inputs while real cost-inclusive development comparison and final selection remain incomplete. Reuse the existing13-fold source-label audit rather than retraining or repeating completed research.

### D173 — pin canonical legacy source and test actual isolated SQLite-full rollback (2026-10-18)

CI39123795307 compiled the current APK and passed its ordinary persistence/OS recovery steps, but legacy preparation rejected the Java source pin before building the old APK. The Windows-generated pin described CRLF while the Git blob uses LF; converting only LF to CRLF reproduces the old hash exactly. Pin the original Git blob and force `core.autocrlf=false`/`core.eol=lf` for archive creation. Require byte-exact pins and identical archives under both external checkout settings rather than normalizing unknown differences or bypassing authentication. Correct only the synthetic fixture's source metadata; preserve its capsule bytes, typed cells and all prior evidence. Keep the failure and require a new actual upgrade result.

Existing injected database failures do not prove handling of a real SQLite-full result. Add two native tests against a fresh test-only DB with a bounded maximum page count: direct chunk writes and sealed encrypted staging commits. Require `SQLiteFullException`, unchanged old generation/content, read-lease and integrity checks after reopen, staging cleanup, then recovery and stale-generation rejection after restoring capacity. Do not fill device storage, alter an existing DB or modify production storage/ledger logic. This controlled DB quota test is narrower than whole-filesystem exhaustion, UI handling or Xiaomi acceptance; compilation and device success remain unproven until the corresponding CI executes it.

### D174 — preserve reported corporate-action types before market NAV review (2026-10-18)

The raw/normalized daily source already retains ExRT, but the market projection dropped it and flagged only non-unit/unknown adjustment factors. Preserve the authenticated raw type and distinguish an absent source column from a reported null. Compare the normalized type when present, accept legacy partitions without that optional column using their authenticated raw source, normalize CSV empty strings to null, and retain unknown codes. A reported type requires review even with a unit factor; no null establishes complete no-event coverage. The [official daily specification](https://jpx-jquants.com/ja/spec/eq-bars-daily) identifies split/consolidation/rights types and product classes whose rights issues are not price-adjusted.

Keep existing reviewed split/consolidation accounting, with a matching non-unit factor and dated inverse share ratio. Explicit rights issues or unknown types must not pass as an ordinary split even when a caller supplies rehashed coverage. Preserve the existing independent action coverage, directional execution/capacity, settlement, costs, point-in-time and final-period gates. A full-window private flag inventory is a review aid only: it creates no actions, NAV results, adopted model or complete event coverage, and performs no training or final scoring.

For saved additional evidence, confirm the source before assuming reuse rights. The [current official usage FAQ](https://jpx-jquants.com/ja/help/usage), reviewed today, explicitly disallows continued use of previously acquired upper-plan data after downgrade; it does not state an overlap exception for fields also offered by the lower plan. Non-reconstructible derivatives may be retained privately under the stated conditions. Do not infer this exception for every derived file, delete the owner's originals without authorization, or use unconfirmed saved evidence. Continue the already frozen current-Light work independently, and do not treat fetching again as proof that old files are authorized.

### D175 — retain the primary storage failure when Android rollback also fails (2026-10-18)

The real bounded SQLite-full tests in CI39126183830 compiled and ran, but both write paths failed because Android's endTransaction exception replaced the original SQLiteFullException after SQLite had already rolled back. Keep the failing JUnit/logcat and the existing tests unchanged. In direct writes and staging commits, use a try-with-resources transaction closer so the primary write/input failure propagates and a secondary cleanup failure remains suppressed. Still close exactly once; propagate cleanup/commit failures when no primary failure exists, and never acknowledge an unsuccessful save.

Preserve encrypted bytes, schema, generation conflict checks, staging ownership, old-data requirements and actual-fill-only ledger semantics. Verify actual product Java using an isolated injected transaction driver and real Android API compilation; those host checks are not SQLite durability or device evidence. Require the unchanged native quota tests to confirm old generation/chunks after reopening, spool removal, recovery and stale-write refusal on the revised APK. Do not substitute an arbitrary exception, skip the capacity tests, fill device storage, clear the DB or treat previous native successes as evidence for this fix.

### D176 — close the fixed daily scope with explicit assumption research (2026-10-18)

The owner's latest instruction fixes completion to the existing18 candidates' cost-inclusive research comparison, separate5/20-day selection or HOLD, and the personal Android real-data path. Preserve capital/history/secrets/holdout, same-input device parity and strict market defaults. Stop expanding full retraining, completed accuracy work, model/features/horizons, allocation searches, generic corporate actions, dividends/personal-tax completeness, intraday execution, advanced optimization or optional account routes. Classify evaluation, implementation and owner/device acceptance separately; none substitutes for another.

Add an explicit assumption-only request/CLI over the existing pinned market reader, saved OOF, fixed rule and stateful NAV. Freeze inputs before calculating outcomes. Keep strict price-only evidence checks unchanged. Record verified source identities separately from declared close/volume/limit/funding/single-vintage assumptions and unresolved coverage. Reject unknown entitlement, corrupt inputs, known future information and known unsupported actions affecting held or ordered assets. Do not require complete historical fill or unreported-action evidence just to label an explicitly limited research result. Never fabricate reviewed evidence or authorize adoption from these results alone.

Use the existing10m/top20/90%/100-share conditions,20/40bps only, separate5/20 holding rules, and existing funding schedule. Preserve missing marks and orders; do not silently filter failed exposures. Use a rational reported split factor only when its float representation matches exactly; keep this interpretation out of strict certification. Extra sizing references may cover held assets outside top20, while every score still requires a valid reference. Guard held/ordered unsupported events on every session, including no-rebalance dates.

The first25-session real-data smoke check finished both horizons at both costs and all four daily balance/cost audits passed. This is not candidate selection or actual execution reconstruction. Save real derived results privately. The18 authenticated OOF containers have no linked native inference weights; only selected roles are fitted once and exported from that same fit, with measured times. Keep final holdout closed until independent adoption conditions are met. Candidate APK creation is authorized; main merge, public release, paid services, actual orders and unapproved external transmission are not performed.

### D177 — freeze one A-E comparison and reuse the authenticated candidate APK (2026-10-19)

Before full NAV results, freeze all available saved forward-ensemble development sessions:177 for5d and140 for20d. Within each horizon use identical days/eligible keys for every family/seed/strategy. Authenticate all18 candidates' four output key sets against saved ensemble and simple baseline; do not repeat the completed accuracy study or read target/label-end columns. Preserve each seed and report family stability rather than choosing the best seed.

A ranks the saved ranking score; B ranks the saved regression. C equally averages the existing daily percentile normalization of regression and ranking. D is one fixed equal-weight combination of return rank, ranking rank, q10 rank and reversed large-loss probability rank. Normalize over original same-day OOF peers before common domestic eligibility; no calibration or learned weights. C/D are dimensionless. E reuses saved forward-crossfit weighted_return and the simple baseline reuses saved momentum20d. All nine candidates per horizon receive A-D, then E/baseline, at20/40bps:152 cases. Pin both original benchmark receipts and D170's authenticated unchanged replay. Preserve source byte checks and duplicate/date validation when retaining only needed market symbols. One sequential worker retains RAM guards.

Store missing held valuations as incomplete with symbol/date/related exposure/affected cases/needed evidence in one private issue list. A null daily quote/volume proves absence in the pinned source, not a verified halt, price or cash liquidation. Do not change periods, remove inconvenient symbols or certify stale marks to improve results. Assumption research alone still cannot unlock adoption/final holdout.

The successful ba69655 CI provides the installable debug candidate; bind its exact APK hash, embedded46 Python sources, unchanged app product tree, native84 tests, legacy debug upgrade and full17-table/520-session B1 evidence. Reuse this component evidence without rebuilding unchanged Android repeatedly. Keep private models/keys/market data out of the APK and Git. Debug update compatibility with the owner's release key and real-model/Xiaomi acceptance remain separate. Consolidate owner operations in one runbook checklist; never uninstall/clear real holdings to bypass a signature mismatch. No main merge or public release.

### D178 — retain incomplete full-comparison results and build an owner-signed private candidate (2026-10-19)

All152 preregistered cases were executed with the unchanged rules in5,028.760seconds:56 complete assumption-research cases and96 incomplete cases. Retain every family/seed/variant/cost and consolidated exposure reasons. The simple momentum baseline is incomplete, so leave its differences undefined. Reuse the completed four-task accuracy study and record separate role-level HOLD decisions; neither the strongest accuracy family nor an observed endpoint becomes an adopted model. Keep final holdout closed and do not start speculative whole-candidate fits.

After observing partial results, add only a reporting diagnostic for an observed initial-to-final NAV return when every declared session was processed and both endpoints are actually known. Explicitly identify this as posthoc and not a new preregistered selection criterion. Preserve original status/results, missing daily marks and undefined MDD/turnover. Do not impute quotes, change rules/periods or add another accounting engine. Diagnose missing-reference exceptions using the same frozen inputs and existing code to capture affected exposure; no normal result or guard is changed.

The owner already has a usable private signing identity. Reuse it without modifying keys and build a normal nondebuggable jp.stockai.app candidate with increasing code10013. Bind it to source329cecd and authenticated successful app assets, verify the existing release certificate, package contents and absence of credentials/market data/private models, and preserve debug/failed-build artifacts. This authorizes a local candidate, not public distribution, main merge or installation over owner data. Existing synthetic CI remains distinct from real-model and Xiaomi acceptance.

Preserve the original500-session training minimum and warm-up instead of lowering it to the405 sessions acquired for evaluation. Append only missing permitted current-Light older history to immutable storage through a separate cloned catalog, reusing the405-day cache and protecting all frozen NAV inputs. Do not use the unconfirmed older Standard raw data or access final-period prices. Data preparation is not a role selection/adoption or a fit. Once roles are frozen, fit only necessary heads once and export from those same fitted estimators, retaining calibration/feature/data/code hashes and measured time/RAM. The existing return-only and four-head conditional fit counts do not presume adoption of risk tasks.

### D179 — create two research heads once and verify real native Android arithmetic (2026-10-19)

Keep the original18-candidate OOF/accuracy/cost evidence and formal HOLD unchanged. Permit read-only real-model integration while adoption is unresolved. Before fitting, freeze only the5-day CatBoost and20-day LightGBM regression configurations from the existing three-seed family comparison and the previously fixed seed17. This is an integration role choice, not final adoption, best-seed selection or a new model search. Keep the original500-session minimum, single worker, CPU1 and1GiB OS reserve. Run heavy Android work after fitting.

Build real features through the existing production/FeatureEngine/label functions with bounded partitions, global market/sector context and the complete-panel adjustment lineage. Preserve exact numeric/timestamp/missingness/type parity, original failed attempts, immutable raw inputs and explicit projection-version identity. A coverage anchor only satisfies the existing date guard and is removed outside its owning partition. A verified absent premium field remains null; it never becomes an invented price. These single-vintage later-retrieved inputs do not certify historical PIT or resolve NAV corporate-action evidence.

Fit each of these two heads once, save the native estimator and preprocessing, and export portable trees from that same fitted object. Authenticate saved-model reload and PC/portable/APK-WASM/Android-emulator predictions on the same1000 feature-only rows per head with unchanged tolerances. Record real time and RAM; never treat training arithmetic probes as out-of-sample performance or backdate the new model. An ASCII temporary runtime path may be used for the isolated Windows AVD, retaining the failed first boot and actual emulator RAM increase. Private instrumentation assets may contain the model; the product candidate must not. No owner database is used or altered, and stop only the owned emulator.

These are two new research refits, not rediscovered weights from the old OOF folds. Reuse them if the final frozen roles/configuration/data boundary are authenticated as identical; do not refit only for export. Do not invent risk outputs, calibration, a locked-holdout report, OwnerAdoptionReview or policy pins to satisfy the current four-head import contract. Four-task adoption is not required: separate minimal handling of genuinely unavailable risk from any fits for actually selected risk heads. Normal bundle, necessary-volume real feature/restoration/daily-flow tests and Xiaomi acceptance remain distinct from this arithmetic proof. Keep one owner acceptance checklist, the signed candidate and tested runtime unchanged; no new public release or main merge.

### D180 — verify real daily-volume features and scope freshness to current decisions (2026-10-19)

Reuse the existing730-calendar-day window, shipped codec and exact packaged feature library for a private real-data arithmetic probe. Retain all1,854,462 daily/financial rows, missing values, insufficient-history exclusions and immutable source/plan/code hashes. PC and APK-WASM agree on every serialized feature value for3820 symbols per horizon, with296507 numeric cells and maximum error0. Record time and memory under the existing3500MiB/1GiB guards. This is a later-retrieved single-vintage snapshot before protected final-period prices, not historical PIT, current daily updates, owner-state restoration or Xiaomi acceptance. A private Android volume harness prepared on disk is not a passed native test.

The real feature output contains125 rows older than its latest timestamp; this does not classify all125 securities as inactive. Reproduce the concrete runtime bug separately: retained old history outside the already frozen current candidate-plus-holdings scope prevents a fresh selected forecast. Require exact cutoff equality for every selected symbol, while allowing older nonselected feature rows to remain in the original all-row provenance hash. Continue rejecting future/naive/duplicate rows across the complete feature output, and keep stale held/candidate rejection, source-receipt timing, model/adoption/calibration checks and accounting unchanged. Do not change NAV inclusion or choose research periods based on this correction.

The before-fix reproduction fails and the five selected-stale/future/naive/nonselected-history boundary cases pass. Keep the running related-test process and subsequent pinned-commit CI distinct from completed evidence. Fix only this necessary daily-integration fault, preserve the prior candidate and every private patch/artifact, and make a replacement candidate after the required CI/source-asset checks. No new fits, adoption, locked-holdout access, main merge or public release.

### D181 — bound real daily feature work without changing its arithmetic (2026-10-19)

The private API35/WebView124 full-data harness completes the same489-session/1,854,462-row input and matches every serialized PC feature value for3820 symbols per horizon, including296507 numeric cells with maximum error0. Preserve the2.5GiB guest renderer-kill failure; the successful4GiB guest keeps Java heap192MiB, application/renderer RSS guard3500MiB and host reserve1GiB. Record717.019s overall,85.155s decoding and608.963s feature calculation. This is an arithmetic harness, not normal owner-state/daily acceptance or Xiaomi success;608.963s exceeds the unchanged600s normal request deadline.

Optimize only latest-row calculation. Full input validation remains before computation. For session-indexed histories, retain the final contiguous segment because the unchanged full-history engine resets every indicator at each gap. Batch equally long contiguous segments as independent numeric columns, retaining each symbol's own date/time metadata. Keep the global128-stock pending limit. Do not change feature formulas, source window, validation/training transforms, feature manifests, tolerances, adoption policy or request timeout. Verify against the unchanged full-history transform for mixed dates, gaps, recurrent indicators, missing shares/financials and invalid older rows, then against the already frozen full real-data JSON. Direct PC decoding is31.668s and optimized feature calculation133.312s; this is not a new native timing result. The overhead-heavy diagnostic profile was cancelled and is not passed evidence.

The related83 tests and the four invalid-history boundary cases pass; Ruff and mypy75 sources pass. Preserve the initial batch-width expectation failure: the unchanged total128 pending cap can flush a length before its individual batch reaches128. Check the bound, all133 inputs and exact full-history output rather than require one incidental flush size. Additional pinned-commit CI and packaged native timing remain necessary.

Source682ec49 CI39158693769 has verify/android-history success and android failure at OS reboot delivery; current old-APK upgrade steps were skipped. Its84 native tests and full17-table restore216.802s are successful components, not an overall pass. Cancel the redundant local test only after the same-commit Python CI succeeds and record it as cancelled. Preserve owner-signed0.1.14-candidate/code10014, package/hash/secret checks and the older candidate; no public distribution or Xiaomi install. Diagnose autonomous versus manual cold recovery separately without bypassing original acquisition/WorkRequest identity or manufacturing an ACK. Formal model HOLD,152 comparison results, unresolved cases and locked holdout remain unchanged.

### D182 — pin the verified candidate and keep owner adoption separate (2026-10-19)

Pin product source cc3d2d5 and tested merge0345ae7 to CI39164164508: verify/android/android-history all succeed and public-release job is skipped. Authenticate current reports and APK hashes, not prior test counts. Preserve the source682ec49 CI failure and the bounded local diagnostic which subsequently passes all three lifecycle phases under the unchanged controller policy. Current CI also passes process loss, OS reboot, force-stop/reopen and actual legacy-source debug APK upgrade. A successful synthetic debug upgrade is not an owner-release/Xiaomi update.

The same4GiB API35/WebView124 profile now completes the full real-data arithmetic harness in375.870s, including74.980s decode and285.055s features, compared with717.019s/608.963s before the latest-only optimization. Every serialized value, missing value and exclusion matches the frozen PC reference for3820 symbols per horizon and296507 numeric cells (maximum error0). Keep Java heap192MiB, application/renderer3500MiB guard and host reserve1GiB; observed app/renderer RSS maximum2,990,034,944bytes and minimum host free1,970,909,184bytes. The2.5GiB renderer failure, initial batch-width test failure and cancelled detailed profile remain failures/cancellation. Do not change source windows, formulas, tolerances or normal600s request timeout to pass.

Preserve owner-signed normal0.1.15-candidate/code10015 from the same43 CI public assets, with30 shared and16 mobile source modules authenticated. Build172.615s,23,957,697bytes, SHA2561312c1c521e21121f55c1a84535429c14d0e0098ce8ddd4c171ce2fda3b52aa4, same existing owner certificate, no keys/private market data/models. Keep previous candidates and the unchanged signing key; do not publish, install on the owner phone or merge main. Public code is independent of the private native test fixture.

Record A/B/C separately. All152 fixed research conditions have results and formal HOLD reasons, but96 are incomplete and not fully comparable; do not turn56 completed assumption-based runs into adoption evidence. B's pinned source passes its required CI and arithmetic checks. C still needs the normal private model bundle, owner-state daily path including source reconstruction, and the one Xiaomi acceptance procedure. The normal bundle currently requires four heads plus calibration/review/pins. Do not fit two unselected risk heads merely to fill that schema or fabricate review/holdout evidence. Reuse the existing two research fits if final roles/data boundaries match; selecting return-only also requires an honest missing-risk contract. The private two-head backup is not a normal import bundle. Locked holdout remains unopened and no model is formally adopted.

This checkpoint records evidence only. The product/runtime source remains cc3d2d5, so do not rerun heavy checks for unchanged documentation or describe those checks as having tested a different runtime.

### D183 — separate streamed state capacity from inline memory limits (2026-10-19)

The pinned real cache for2024-02-27 through2026-02-26 (731 calendar days plus two calendar-only observations) produces188,857,904 base64 characters and a159,989,760byte mobile SQLite snapshot. Desktop export/restore matches all17 typed tables. This exceeds the previous128MiB native transport quota; it is not evidence that the Java heap or feature-memory budget should grow. Preserve source records, types, receipt timestamps, hashes and the existing window instead of dropping history or adopting a new speculative codec. A private lossless-delta prototype is not a production format change.

Permit up to256MiB base64 characters only through the existing256KiB chunked state import/export, encrypted store and streamed STOCKAIB1 backup. Allow4096bytes of bounded JSON/header/tag overhead around the stream. Keep128MiB for whole-String request/legacy state operations and whole-byte-array crypto, rejecting oversized legacy reads before constructing a complete String. Keep SQLite256MiB/file, Java heap192MiB, application/renderer3500MiB guard, host reserve1GiB, CPU/worker policy and normal600s request timeout. Existing small backups remain readable; old applications with128MiB restore limits cannot restore a new larger backup. No schema, encryption, accounting, formula or model-policy change.

The real source reconstruction is a cache-to-typed-state test, not a successful REST/network ingestion. The bounded official historical REST schema probe separately passes validation. Current daily prediction must reject the stale February price window; adding current calendar observations does not make old prices current. Never backdate receipts or weaken freshness/holdout checks for a positive test. Keep formal HOLD, the unopened holdout, the existing two private research fits and normal bundle prerequisites unchanged.

At this checkpoint, related Python runtime tests33pass (26.30s) and scoped Ruff passes. Add native preallocation/quota tests and streamed-writer incomplete-content checks. New source CI, real188MB native restore/backup/reopen proof, signed candidate and Xiaomi acceptance are not yet verified. Previous cc3d2d5 CI/candidate evidence remains pinned to that source. Record subsequent outcomes separately, including failures.

D183 follow-up: the first actual188,857,904-character native input reaches the normal owner but is rejected before asset loading (`COMPUTE_state_other_ASSETMASK_0`). Inspection identifies the remaining128MiB streamed guards in compute-host/compute-worker. Align only those ArrayBuffer/streamed-output guards to256MiB as well. Keep the legacy String paths and Java request/reply caps at128MiB. Preserve the failed native run and the earlier controller-only import/headroom failures. The lightweight launch probe uses the same GlobalMemoryStatusEx API and unchanged6GiB threshold without loading the unrelated research import tree. Source c328d31 Android CI succeeds, including compiler/crypto/lint and native/lifecycle/upgrade checks, but its whole workflow and real-volume acceptance are not reported as successful. The corrected source requires its own CI and native proof. Local lint/typecheck passes; no evaluation/holdout/model-policy changes.

D183 verified checkpoint: pin product59ea01e/tested merge42e95cd to CI39187276127. verify/android/android-history all succeed; release is skipped. This run has native86 tests210.244s, shared Python group529 tests549.88s, Ruff/mypy75 source files, browser/offline checks, PC5,000-symbol/520-session storage788.919s and latest features304.299s/peak3,124,248,576bytes. The same CI APK completes full synthetic17-table B1 restore223.613s/Java192MiB; lifecycle and actual legacy debug APK upgrade pass. Counts across groups overlap and are not summed as unique tests.

The actual188,857,904-character cache passes native JUnit438.815s, including owner recreation,188,858,862byte STOCKAIB1 export, authenticated metadata-only preview, restore and reopen. All17 mobile typed tables match the source. The one manual_portfolio_imports row intentionally added by the profile test is authenticated by payload/revision/time/hash, and all other operations tables are unchanged. Preserve the original controller failure from expecting that intentional row to be absent; independently verify its saved native output rather than rerunning the heavy test. Preserve earlier controller/import failures, c328d31's remaining JS128MiB guard failure and the local Gradle Unicode-path worker launch failure. Source c328d31's whole workflow was cancelled as superseded, not counted as successful.

Actual observed app/renderer RSS maximum1,673,953,280bytes, VM working set5,199,069,184bytes and host available minimum1,745,833,984bytes preserve every existing RAM threshold. The native feature request422 occurred before11:30 and does not isolate freshness from cutoff; the PC explicit11:30 request separately rejects the old next-session mismatch. This is typed real-cache restoration with an empty test profile, not owner data, normal REST initial acquisition, current daily model inference or Xiaomi acceptance. Reuse the old full real-feature/model parity only for unchanged authenticated calculation source.

Normal owner-signed nondebug0.1.16/code10016 is23,957,789bytes, SHA25624be5bc660a4fd075397526e896100bf5951ba4d8ce23ae9752f2c730039a2f1, same existing certificate,43 CI assets/30 shared/16 mobile sources authenticated, no private models/market data/keys. Build93.375s with one worker/Java768MiB; retain old candidates and key, and do not publish/install/merge main. Add the matching256MiB browser rejection threshold plus a zero-input-read assertion; its10 related cases pass locally8.7s with lint/typecheck. This checkpoint changes only docs and that test; product source remains59ea01e, so reuse the complete same-source CI without another heavy run.

Keep A/B/C separate: all152 research cases recorded but96 incomplete and formalHOLD; normal private bundle/owner current-day path/Xiaomi remain pending. Two real regression heads can be reused only when final roles/data match. Do not fit unselected risk heads or fabricate calibration/review/holdout records. Retaining the current four-head contract conditionally needs two selected risk fits; choosing return-only requires an honest missing-risk import/prediction/display contract, still pending. Consolidate the owner procedure in the existing Xiaomi acceptance file, with USB optional and prerequisites explicit. No new model, fee replay, API/AI export or broader feature work in this checkpoint.

### D184 — align daily forecast metadata with the actual quote-close training label (2026-10-19)

The existing dataset generator, both the original OOF source2bf1dc4 and full-fit source329cecd, computes `adjusted_close[T+h] / adjusted_close[T] - 1`, where T is the input quote session and h is5/20 trading sessions. The conservative `as_of` is the next session11:30 and is not the denominator session or execution time. Correct the previous `next_session_adjusted_close_to_h_sessions_later` description to `quote_session_adjusted_close_to_h_sessions_later` for newly created snapshots/bundles; do not change targets, weights, numerical predictions or the NAV execution engine/rules. Do not repeat the18-candidate comparison for this metadata correction.

Keep explicit legacy-label archives readable with their original content/IDs. Reject their new model import/selection, personal proposal and ChatGPT input with `FORECAST_LABEL_DEFINITION_UNVERIFIED`; do not rewrite old receipts or manufacture new approvals/pins. Propagate the bundle semantics into new forecast receipts and cross-check them on reload. The stock view indicates only whether the label description is supported, never certifies adoption. Display the quote-close basis and distinguish it from execution profit. Both existing ChatGPT routes add static meaning alongside the unchanged numerical prediction object: this label excludes trading fees, tax and dividend cashflows, and does not certify zero dividends. No new external service or market-data field is introduced.

The two private real research heads retain their original plans, native/portable weights and preprocessor hashes. Separate correction sidecars bind the actual dataset/helper evidence to those immutable artifacts; they do not turn research heads into approved deployment bundles. The saved20d development OOF error has been reconciled read-only against its original fold metrics, with original availability timestamps preserved. Its descriptive residual error and the existing ensemble's rank-space uncertainty are not interchangeable with a received-past-only raw-return deployment calibration. No Calibration, OwnerAdoptionReview, normal bundle, final test or additional fit was created.

Related latest local verification:29 tests pass, Ruff and mypy(src75 files) pass, frontend lint/typecheck pass. An earlier broader related suite passed172 tests before the final API/optional-route edits; it is not whole-current-code proof. New source CI and candidate APK are required; prior product59ea01e/0.1.16 remains preserved. Evaluation stays152 recorded cases,56 assumption-complete/96 incomplete, formal HOLD and unopened holdout.

D184 verified checkpoint: sourcec7103f8, tested merge8e9cdc1, CI39194492545 all required jobs succeed; public release is skipped. The latest CI includes the quote-close label regression, legacy archive identity/new-use rejection, ChatGPT numerical-object preservation, API and portable import regressions, native86 tests (125.941s), lifecycle3 phases, actual old-source debug upgrade, and full17-table restore (216.967s). PC5,000-symbol/520-session capacity and latest features pass (172.632s, peak3097714688bytes). Counts across groups overlap and are not added as unique tests. Private signed0.1.17/code10017 is package-authenticated against the same CI assets, same owner certificate, no private model/market data/credentials; SHA256fc018fb22d1d666baf4d2045df63edf38b2914878512f29b91c69e0f2e3098db. The unchanged calculation/stream-storage components retain their prior real-input evidence; no new whole-owner actual-model/Xiaomi success is claimed. No extra fit, calibration, adoption review, holdout access, real order, new fee, merge or public distribution.

### D185 — verify actual production label lineage and withdraw the generic-builder inference (2026-10-19)

Correct D184 explicitly: it inspected `ml/dataset.py::build_supervised_dataset`, which is the basic research builder, and incorrectly applied that quote-close target to the saved production campaign and full-fit heads. The actual producer is `ml/production.py::build_production_supervised_dataset` and `_add_horizon_labels`. T is the input quote session; entry is calendar[T+1] and exit is calendar[T+1+h], so the actual target is `adjusted_close[T+1+h] / adjusted_close[T+1] - 1`. The next-session11:30 availability is before that entry close. The original plan's `next_session_adjusted_close_to_h_sessions_later` was correct.

Authenticate the original dataset identity and its metadata/source commits2bf1dc4/329cecd, then compare original development labels, each selected head's own saved OOF and the current fit inputs. Each horizon's10-row samples match the next-session formula; none of the corresponding original/fit samples matches the quote-session formula. Original dataset reads are restricted to an entirely pre-holdout row group, OOF and fit inputs are guarded by footer date bounds. Hashing the full immutable file does not decode protected outcomes; no protected outcome rows are read. This sample/producer evidence does not certify full cross-vintage equality or point-in-time availability. Preserve the first audit attempt (it incorrectly queried the5d family in the20d report), and the successful per-head follow-up.

Restore the next-session metadata default and supported-value check for new model imports/proposals/ChatGPT input. Keep both descriptions readable as immutable archives; quote-session description from c710/0.1.17 cannot certify new use of these production models. Preserve the original numerical predictions and the bundle-to-receipt semantics checks. Explain the daily-close research proxy in the UI/prompt and distinguish it from actual execution, fees, tax and dividend cashflows. The basic quote-close research builder remains unchanged and separately tested. Add a regression through the actual production builder with nonlinear prices that gives different signs/values than the generic builder, and align metadata against that result rather than a duplicate expectation.

Withdraw private candidate0.1.17 for its incorrect description and preserve its APK, CI receipts and prior report. The earlier green tests proved their encoded expectation, not the true producer lineage. Preserve D184 and the incorrect private sidecars as history, and add explicit revocation/confirmation sidecars binding the correct original plans and unchanged weights. New source CI and candidate0.1.18 are required. No target regeneration,18-candidate replay, extra fit, calibration, review, adoption pin or holdout access. Local related155 tests87.32s and final2 description tests2.19s pass; Ruff/mypy75 and frontend lint/typecheck pass. A stays152 recorded/56 assumption-complete/96 incomplete/HOLD; C remains pending genuine bundle/current owner path/Xiaomi.

D185 verified checkpoint: source11957b2, tested merge41f0a44, CI39197573498: verify/android/android-history all success; public release skipped. The actual production-pipeline metadata regression, generic/production target distinction, immutable unsupported archives/new-use rejection and unchanged numerical prediction contracts pass. Native86 tests 163.397s, lifecycle3 phases, old debug APK upgrade and full17-table restore 213.939s pass. PC5,000-symbol/520-session latest features 300.976s/peak3124273152bytes pass. Private signed0.1.18/code10018 is source/CI-asset/signature authenticated, SHA256cf462fc0cdf9d58a59175710a3b66aeaee54c7e809731489e9923c3594a0bdb1; no private model/market data/credentials. Preserve withdrawn0.1.17 and D184 records. Actual weights, targets and152-case results are unchanged; no new fit/calibrator/review/holdout. The unchanged real-data math and storage components reuse their prior scoped evidence, not a new whole-owner/Xiaomi claim.


### D186 — separate missing-reference sensitivity from the frozen comparison (2026-10-19)

The owner asked to continue feasible historical-evaluation work without a supplemental archive. The original152 runs, their frozen periods/universes/scores/costs,56 assumption-complete/96 incomplete results and formal HOLD remain preserved. No post-result rule change replaces that comparison or unlocks final holdout.

An explicit assumptions-v2 entry may skip the entire scheduled rebalance when any held stock lacks a valid prior reference. It retains holdings and released cash, generates no orders/costs for that decision and retries only at the next scheduled horizon rebalance. Existing settlement and reported actions continue normally. It never imputes a price or deletes an illiquid holding. Default fixed-rule and assumptions-v1 behavior still stops. V2 requires post_result_exploratory_sensitivity, saves the full input/decision-policy hash and skipped-decision reasons, and remains adoption-ineligible.

Unknown daily valuations remain unknown/incomplete with no certified MDD/turnover. Supplemental pinned public evidence may block a known unresolved delisting cash event from its effective window, even if no market row exists and even on a no-trade session. It only blocks accounting; it does not certify an action, infer cash receipt or act as historical alpha. Strict market NAV, actual cost/settlement checks and locked holdout protections are unchanged.

Targeted JPX/issuer investigation confirmed delisting of3347 on2025-08-20 and7623 on2025-08-18, matching the last frozen exchange quotes. Public cash-out/consolidation notices establish relevant terms but do not establish verified payment dates or complete accounting. Keep their exposed runs incomplete until appropriate share/entitlement/valuation/cash-release treatment is implemented. Evidence and derived amounts remain private. The existing5721 rights blocker remains; no ordinary-split or zero-rights substitution.

Related accounting/funding/market tests205 passed; the strengthened source-row-absent assumption tests38 passed (overlapping). Ruff and typing passed. The initial four real-data sensitivity probes crossed the original reference stops but retained missing marks; no formal adoption resulted. Final-source bounded replays of the50 originally reference-stopped cases are a separate exploratory artifact, not a new18-model selection. Android/model bundles and the private0.1.18 candidate are unchanged by these PC research modules.


D186 follow-up: All50 reference-stopped cases were replayed under the pinned exploratory rule. Unknown marks and known unhandled actions remain incomplete. JPX evidence identifies all six absent-record exposures as delisted securities, matching quote terminals. Four facts discovered during execution are a separate retrospective exposure audit; running inputs were not modified. Known unhandled events suppress numerical scenarios.

A read-only postprocessor uses the existing NAV's last-mark100%/50%/0% fields for conditional valuation metrics without changing orders, cash, costs or the accounting engine. These are hypothetical marks, not observed NAV, executable prices, probability intervals or guaranteed loss bounds. They do not unlock adoption. The152-case index distinguishes50 new replays from102 reused receipts; it does not claim all152 were newly executed or independently tested. All seeds and formal HOLD are retained; final holdout stays closed.


### D187 — connect reviewed cash conversions without inventing payment dates (2026-10-19)

Reuse the existing NAV receivable/settlement ledger for supplemental cash-only events in explicit assumptions-v3 exploratory research. Pin the reviewed terms and, when payment timing is specified, separate payment evidence; require the exact same action in the accounting input. A hash binds document bytes but does not certify its meaning. Announced schedules, conditional fractional proceeds, rights, and unverified actual entitlement must not be relabelled confirmed unconditional cash. Preserve the original152-case comparison, all periods/candidates, final HOLD and unused holdout.

An explicit cash_conversion_pending_payment event represents an authenticated cash entitlement with unknown payment timing. Remove the converted shares once, retain the nominal receivable in its own account, and never release it for reinvestment or invent a payment timestamp. Mark affected daily NAV, return and MDD unknown; the nominal-claim sensitivity is only a conditional valuation. Strict market evaluation rejects this pending-payment event. Specified-payment cash conversions retain the original settlement behavior.

The supplemental adapter accepts only explicit v3 scope, authenticates pinned evidence, matches each blocker by symbol and delisting date, and refuses reported share/rights events rather than overriding them with cash. Window declarations are checked before supplemental evidence is read. Evidence discovered after the historical period is accounting-only, never model input. Later confirmation should create a new pinned input, not mutate a running evaluation.

Local related216 tests30.73s, separate dividend24 tests2.85s, Ruff and mypy75 pass. These are synthetic accounting/adapter proofs, not a new completed real-data comparison. Two additional official documents are retained privately; the six affected cash cases have a concrete readiness list. No newly confirmed real cash action is asserted, and the original56 assumption-complete/96 incomplete results remain unchanged. No model fit, holdout read, owner-ledger write, real order, APK rebuild or public distribution.


## D188（2026-10-19）：未採用の2回帰headで通常の研究用相談経路を接続する

- 正式採用と本人用統合試験を分離する。既存4headの採用review/校正/承認pinは維持し、別schema `stockai-mobile-research-bundle-v1` に認証済み5日/20日回帰だけを格納する。research専用pinでbyte/hash/特徴量/前処理/出所とPC・端末計算証拠を固定し、正式採用0件を変更しない。新しいfitは行わない。
- 原予測の内側schema3はresearch限定。下振れ、下落確率、不確実性、risk horizon/閾値/校正器はnullであり、ゼロや架空値へ置換しない。旧schema1/2・旧保存原本のhash互換性を保つ。riskあり/なしの混在は拒否する。
- risk欠如時は自動株数proposalを作らない。他の照合が全て成功した場合だけ、価格反映済み口座・原予測・設定へ結び付いた相談contextを保存する。ChatGPTの固定目標株数は既存engineの資金/費用/税/単元/口座/保有/集中度等で検算し、モデル効用を計算しない。設定済み制限を外さず、モデルrisk未検証を明示する。
- 相談時にも最新の原予測run、model pin、本人設定/台帳revision、実約定を照合する。15分超は拒否し、明示再照合だけで新しい相談contextを作る。原予測の時刻/値や旧相談原本は変更しない。回答取込は提案保存だけで、現金/保有/税台帳を更新しない。
- 日次処理はrisk欠如だけが残る認証済みcontextを `consultation_ready` と表示する。数値/株数自動判定の完了に偽装せず、他の不足は従来どおり未完にする。20日回帰で上位20と順位外の全保有を表示し、5日値を足さず併記する。
- 実2weightの通常PC取込と同梱WASMの取込/再読込が成功し、各horizon1,000行の最大差0。これはブラウザーWASM証拠であり、Android nativeの通常bundle取込・実市場の現在の日次一連・Xiaomiの合格ではない。以前の個別head emulator証拠もその範囲に限定する。元152条件/採用HOLD/未使用holdoutは維持する。


## D189（2026-10-19）：事後会計根拠と現在の実利用入力を分離して検証する

- 元条件と実施後資料を照合した現金権利だけをD187の研究経路へ接続する。日付しかない効力/公表情報を実測時分に変えず、日単位の会計conventionを別記する。事後確認を当時のPIT証明や予測入力へ転用せず、入金不明/後続の既知イベントによる不完全を維持する。
- モデル入りの通常Android取込/保存復元は、全量の現在の日次処理/Xiaomiと分けて証拠を残す。今日のLightを既存検証/不変保存へ通したが、過去の試験cache終端を現在の履歴として表示しない。実際の取得/モデル取込より前へ時刻を戻さず、保存済み原本の再利用を先に確認して不足分だけ追加する。


## D190（2026-10-19）：現在の実利用入力と、評価用holdoutへのアクセスを明確に分ける

- 現在の日次統合試験に必要なLightだけを新しいimmutable入力版へ固定する。既存Light原本を再利用し、不足履歴/公式valuationを補完する。PC研究の全5年を端末へコピーせず、730日/485営業日の必要範囲と翌日calendarだけを新しい試験cacheへ射影する。Bulk原本/実受信時刻を保ち、再構成したcacheをnative HTTP page/acquisition receiptや本人DBと表示しない。
- CSVの空欄は既存Data Contractどおり欠損であり、候補抽出でもゼロ円や有効20日へ数えない。原raw/hashを変更せず読取境界で扱う。空白だけの不正金額は拒否し、欠損理由と全保有の保持を維持する。これは資金/銘柄条件の緩和ではない。
- 今日の実受信/モデル取込を今日11:30以前と扱わない。翌10月20日11:30を明示した読取専用の特徴量/推論参照を準備するが、未来の当日membershipを作らず、通常現在日次の成功とは表示しない。実際の時計も変更しない。
- 現在運用の市場価格日付はlocked final-test calendarと重複する。このアクセスを記録し、最終target/保存最終予測/成績の読取やモデル/基準選択とは区別する。「市場価格も一切未閲覧」とは報告しない。ML評価の固定版・元152結果・正式HOLDは保持し、最終採用の独立性は既存のアクセス/固定条件確認を省略しない。
- 現在のPC入力/特徴量からnativeと端末tree各3,781行/最大差0、PCのモデル入り17table復元は試験済み。最初の候補抽出例外と未保存の正確な特徴量秒/最終peakを保持し、保存済み特徴量からだけ再開する。新しいfitや架空の実測値を作らない。関連universe/membership27件とRuff成功を、新sourceの全体CIやXiaomi成功へ読み替えない。


## D191（2026-10-19）：中間入力の一致と全量SQLiteからの端末完走を分けて判定する

- 認証済みの中間frameからの特徴量一致、実weightの個別予測一致、通常bundle取込、全量保存復元はそれぞれ有効な証拠だが、その組合せだけを全量SQLite→現在の日次予測の完走証拠にしない。最新データで製品のinput readerを通す範囲を直接検証する。
- d150b07/同計算sourceの4GiB guest試験は591.172秒、入力生成中にAndroid lowmemorykillerがrendererを終了した。sampled app/renderer RSSやhost reserveが設定guard内でもguest OSのwatermark/swap不足は発生し得る。OS killと、設定上限の超過・600秒timeout・モデルの数値不一致を混同しない。
- 実装の次の優先は全量入力生成の保持量/不要copyの削減と同一入力での再検証。RAM/時間上限、入力の意味、数式、元hash、採用基準を緩めて合格にしない。準備済みの追加試験を実行済みとせず、ユーザーの区切り報告では現行試験の終了後に新たな重い試験を始めない。
- 非公開候補0.1.20/source d150b07の内容と署名は検証済みだが、全体CI/実データ全量/本人通常日次/Xiaomiの成功とは別。旧候補と失敗ログ、私有入力/weight、元152条件/HOLDを保全する。新しい有料サービス・追加fit・実注文・実台帳更新・公開配布は行わない。


## D192（2026-10-19）：入力の意味と出所IDを保ったまま全量読取の同時保持を減らす

- 全量入力のmemory修正は、既存のSQLite reader/production変換を再利用する。期間・市場母集団・特徴量・欠損・PIT/全出所検証・通常時間/RAM制約を維持し、元hashと全特徴量/実weightの一致で確認する。
- Source IDのv1 byte streamを保ち、全幅frameのsort copyをキー順序とbounded row hashへ置き換える。分割の累積係数とlineageのsortは必要列へ絞り、入力sourceの全列コピー/index再作成を減らす。列の変換は新しい配列へ代入し、元sourceの変更を試験で拒否する。
- mobileのprojected日次入力では、同じimmutable文字列の値/型/nullを保って列ごとに共有する。共有poolは一回の読取内・各列8,192値までとし、永久cacheや全履歴の文字列無制限保持にしない。全raw/normalized照合と既存array budgetを通す。
- PCの段階計測/互換性成功とAndroid guestの全量成功を別に記録する。旧CI全成功、関連96件成功はそれぞれの対象sourceと範囲に限定する。新しい全量照合、通常owner/daily、Xiaomi受入と正式採用HOLDの残件を維持する。

- 同じ実SQLiteの修正後PC照合は全特徴量JSON/7,562実予測最大差0、元source IDs/件数/hash不変。入力process peakは3,500,724,224→2,322,100,224bytes（33.668%削減）。診断profile付きの秒数を通常Android日次時間とせず、0455e48の同条件native再試験/CI結果を待つ。


## D193（2026-10-19）：新しい入力の出所IDを元PC64bitのv1定義へそろえる

- 旧wasm32のPandas masked NA hashとPC64bitの差を、値の差やデータ破損と混同しない。新しいsource-row hashは元PC v1の64bit欠損hashをmasked整数/浮動小数/booleanへ適用する。型/値/列順/全履歴/未使用列をhashから除外せず、入力ID一致の検査を残す。新schemaへの再採番や保存済み履歴の書換えはしない。
- 既存のplatform別期待値は旧IDのoracleとして保存し、今後のWASM入力・予測data proofはPC共通IDを要求する。実32bit WASMの少量再現、32bit欠損を模したunit検査、旧PC v1のchunk/missing-key/index検査と全量PC/実model一致を分けて記録する。少量成功を全量Android/Xiaomiへ読み替えない。
- 原本の行hashは同じv1 canonical JSONのbyte列から計算する。検証済みscalar tokensを使って行dictとJSON再変換の重複を減らし、不正JSONを受け入れない。legacy/疎なfieldは元のdecodeへ戻す。raw columnと正規化全byteの照合、128cacheとRAM/通常600秒の上限を維持する。
- 全量Androidは入力作成後のID assertで614.262秒に失敗し、実際に異なるfull IDsの初回記録は欠けた。次の私有workerにはdataset/変換段階とID/timerの記録だけを追加し、同じfixture・model・assert・予算で再試験する。全体CI/全量推論/owner/daily/Xiaomi・候補releaseが未完の間は全完成としない。追加の研究学習と採用基準の緩和は行わない。


## D194（2026-10-20）：明示dtypeの非null定数を一度だけ型変換する

- 性能のために同じmetadataを各行で再解釈せず、64行以上の定数のみ同じPandas scalar castから独立配列を作る。各列で所有し、参照cacheや他列へ変更を共有しない。最終DataFrameは不要copyを抑えるが、元のschema cast/index操作を残す。
- schemaの未指定dtypeはDataFrame mappingでは推論維持、Series.astype(None)ではfloatを意味するため、未指定とnullは元経路を使う。欠損をゼロ/文字へ置換しない。raw/normalized原本と全入力identityの検証を省略しない。
- 少量実データのpaired timing/出所IDと関連62件の成功は、通常600秒や全量・Xiaomi合格の証拠にしない。新sourceを固定した全量検証、通常owner保存復元/日次、候補APK/実機受入を続け、旧失敗と元152条件/採用HOLDを保持する。

## D195（2026-10-20）：効果測定の後に、共通母集団を保つ最小の候補限定計算へ進む

- 本人の最新指示を優先し、D192以降を保全して同じ実データで効果を先に測る。d1b0479のAndroidは入力404.607秒へ短縮したが、全市場特徴量255.063秒が残り要求662.793秒/600秒超過。数値一致とOS終了なしを全体合格へ読み替えない。
- 市場・業種の騰落/平均/coverageは全母集団のまま、時価総額300億円以上/20営業日平均売買代金上位300と全保有の条件を変えず、詳細特徴量の計算対象を限定する試作へ進む。既存の全市場共通入力を維持した小さい射影から検証し、入力構築前の限定や日別統計cacheが必要かは実測で判断する。全EMA/MACD等の再帰更新や汎用cache基盤を一括導入しない。
- 同じ入力/時点/モデルで候補集合と順序、共通統計、5/20日全特徴量/欠損/前処理、予測、上位20、出所を比較する。不一致で許容誤差を広げない。小規模PC→実730日PC→Android/予測保存→日次差分/再表示/訂正/入替/保有/再開の順に範囲を広げる。小規模合成試作の一致を実データ/実機の性能達成としない。
- 開き直しは既存の保存結果GETを使う。同じ入力の再実行cacheを早める場合は入力版/更新範囲/コード/特徴量/モデルを認証してから再利用し、未実装のcacheや日次数分を達成済みと報告しない。旧18候補の学習/OOF/152条件/採用基準/holdoutを変更しない。必要CIの成功後に候補APKを更新し、Xiaomiは同じ一括票で別確認する。


## D196（2026-10-20）：日次の個別特徴量だけを固定候補+全保有へ射影する

- D195の小規模/実730日PC試作で旧対応行との完全一致を確認したため、mobile.feature_inputsのoptional decision_symbolsを通常forecastsへ接続する。全市場の原本/出所を確認し共通市場・業種指標を作った後、個別daily/financialsをモデル用copy/JSON変換前に絞る。既存の履歴長・候補条件300・全保有・共通母集団・特徴量式・前処理・weightは変えない。default全市場の診断/既存経路を保持し、src研究用の18候補/holdout経路は変更しない。
- 新しい予測proofは計算対象と固定universeの一致も認証する。既存receiptを移行・再採番しない。未知/履歴不足の対象に予測を補わず、保有不足/有効候補なしは既存の停止とする。射影で空になる財務表はschemaを保って同じ欠損を出し、source schema不足は拒否する。
- PCの完全一致/速度とAndroidの実測・保存・日次更新は別判定する。全市場共通入力の構築前の限定や全指標の差分化、共通context cache、未測定の日次数分を実装済みとしない。通常600秒/RAM guardを維持して次の全量試験を行い、必要CI成功後に候補APKを更新する。正式採用HOLDと既存のデータ/保有保護を維持する。

## D197（2026-10-20）：実測で600秒以内へ収まる最小方式を固定する

- D196の候補+全保有の詳細計算が、共通母集団/元入力/実モデル予測を維持して実Android要求452.336秒で完走した。初回安定化のためだけの大規模な市場入力再設計は追加せず、通常保存/日次差分/再表示/再起動とXiaomi受入を先に締める。600秒/RAM guardは維持し、単一の完走を日次数分や本人実機成功へ読み替えない。
- 共通統計のhost検査は、転送前WASMの固定hashに加え、Java JSONが整数値floatを整数表記へ変換した場合だけ、完全に同じ有限値へ型を戻して比較する。元の失敗/回収byteを残す。特徴量/予測の許容誤差は変更せず、値差やnegative zeroの消失をこの経路で隠さない。
- 同じsourceの全量owner/B1保存復旧と署名候補を別の証拠として管理する。実モデル予測の通常保存/差分/再起動を未確認のまま完了扱いにしない。入力段階のpeakは候補限定前とほぼ同じで、次の短縮案は版/訂正/分割/対象変更を認証するcache等に限り、必要性を日次実測から判断する。

## D198（2026-10-20）：bulk履歴とAPI差分の時刻表現を読込時に合わせる

- 実1営業日の追加で、bulkのTimestamp日付とAPIのISO文字列日付の混在が停止を起こすことを確認した。混在日付keyとaware timezoneだけを明示的に同じ型/UTCへcastし、元原本・受信時刻・修正履歴を更新しない。同型の既存入力はそのまま読み、元の全source IDs/全特徴量/予測一致を維持する。生のbulk列をAPI列へ架空補完しない。
- 既存の価格/予測/会計や18候補/最終採用条件は変更しない。PCの141関連件と旧730日/実API追加の一致がそろったsourceを次のAndroid/CIへ固定する。0.1.21やD197の成功をこの変更後のAndroid/通常日次/次候補/Xiaomiの合格とは表示しない。

## D199（2026-10-20）：候補限定方式で締め、共通cacheの追加を保留する

- 全市場の出所検証・市場/業種統計は保持し、個別計算だけを候補300+全保有へ絞る。600秒内の実API差分計算と通常forecast保存が成立したため、永続共通cacheや全指標の再帰更新を今回の必須追加としない。入力構築前の履歴限定や日次数分以内を達成済みと表示しない。
- 通常forecast/save/process再起動の締切分岐は隔離Worker時刻制御で試験し、実OS時刻・実取得時刻を改変しない。clock bootstrapを通常候補へ含めず、実時刻のOS配送/Xiaomiの合格とは分離する。研究用モデル/採否/holdoutと既存安全制約は維持する。

## D201（2026-10-20）：Android TOPIXのqueryを公式契約とPCに合わせる

- TOPIX四本値はfrom/to省略で全期間となり、dateは対応queryではない。日別取得はfrom=to=指定日とし、範囲外応答の日付検査は維持する。Calendarの将来営業日窓と他endpoint、CPU/RAM/時間/rate上限を変更しない。根拠は[公式仕様](https://jpx-jquants.com/en/spec/idx-bars-daily-topix)、既存PCclient、nativeの保存位置3と実API再開試験。
- 既に保存したpage/取得IDを維持し、暗号化owner保存後だけackする。観測用sidecarの不備で停止した試験は原記録を残し、独立したDB/別起動probeで検証する。APIキーを平文file/ログ/portable stateへ出さず、試験で保存したnative credentialを使用後に除去する。通常候補は修正後CIを通して更新する。
- 範囲外TOPIX応答のraw価格受領はdebugアクセスとして記録する。最終target/予測/成績の未採点と、raw市場価格のアクセス有無は分ける。モデル/採用条件/最終testの扱いを変更しない。

## D202（2026-10-20）：CI全体の直列実行枠と個別性能条件を分ける

- 既存の容量15分/特徴量12分を与えるには、実測約39分の先行工程へ加算した親枠が必要。45分で2回中断した証拠に基づき、親verify jobだけ60分とする。個別試験の時間・データ規模・判定、アプリ600秒、CPU/RAM/worker数、Android/native history jobの制限を維持する。試験を省略せず、特徴量が実際に通ることは新CIで確認する。
- モデル・金融計算・端末の計算コードは変更しない。旧verify中断と成功済み証拠を保全し、同一内容の自動再試行を増やさない。通常候補の署名は必要CIの全成功後とし、モデル採用HOLDとXiaomi未確認を別に扱う。

## D203（2026-10-20）：修正版候補の固定と本人端末受入の境界

- 通常0.1.23候補は製品c2fa278/必要CI39330817573成功と同梱source/hashへ固定する。0.1.22は実API不具合による受入取り下げを維持する。追加保有範囲の算術照合は同じ特徴量/前処理/研究2回帰・730日で行い、本人台帳の変更やXiaomiの証拠へ読み替えない。
- 全市場共通指標と候補条件を保ち、既存の日次/保存/手動相談を同じ一括票で確認する。入力構築が主な残存コストであり、日次数分以内と実機のメモリ余裕は未達/未確認として維持する。未測定の改善やモデル採用を完成扱いにしない。

### D204 — actual-clock daily acceptance reuses the unchanged candidate (2026-10-20)

Use unchanged product c2fa278 and its successful required CI/normal private 0.1.23 candidate. Real-clock API35 instrumentation now covers the existing WorkManager path, pre-cutoff refusal, OS dispatch, foreground calculation/encrypted commit, actual daily notification, and a separate read-only process/AVD reopen. Preserve original native receipt times; this run does not claim new HTTP acquisition or unattended Xiaomi delivery.

The observed forecast/save state interval is544.795s under the existing600s bound. All feature-value hashes and590 predictions match PC; all17/27 typed tables are checked, and market/model/personal ledger inputs remain immutable. Keep incomplete diagnostic observations and the interrupted original reopen separate from the passed additional probe. Tolerate only unavailable/partial intermediate sidecars; final proof and DB checks remain strict. Preserve boot/wait/probe-setup failures, all resource guards, and the unmodified signed APK. No new model fit, final scoring, automatic external AI send, real order, merge or public distribution. Xiaomi and daily performance improvements remain open.
