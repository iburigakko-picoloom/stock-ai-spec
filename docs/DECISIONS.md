# Decisions and Open Questions

更新日: 2026-08-22  
状態: v0.2

## 確定事項

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
