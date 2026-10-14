# 日次版の実装と残作業

2026-10-15。日次版を先に進め、前場版は別工程とする。現在は研究用の基盤段階であり、全計画の完了・実用採用を意味しない。

## 現在使えるもの

- 学習済み18候補（5日・20日×3方式×3seed）のreport/OOF認証。成功・失敗履歴、元のsource pinを保持。
- 日次Prediction v2。5日・20日の原予測を保持し、1日は未提供（null）。Decision Engineの日次設定は重み0/0/1、リスクは20日。
- 原予測・7項目の手動企業調査・本人のレビューを別の改変不可レコードとしてSQLiteに保存。JSONが正本、CSV/Markdownも同じsnapshot ID。
- APIによるimport preview→hash確認→idempotent confirm、保存検証・既存backup/restoreへの追加対応。
- 本人専用のスマホ閲覧サイトと、PCからの最小結果同期。サイト保存後の閲覧はPCへの接続を必要としない。
- 同じ本人専用サイトの「口座・保有」で、保有なし、口座区分、保有銘柄・株数・取得単価、任意の資金・リスク設定を手動登録できる。

サイト: https://stock-ai-private-daily.manato0618.chatgpt.site

実データの予測はまだ生成・同期していない。サイトの18/18は研究候補の学習完了数であり、推奨銘柄数やモデル採用済み表示ではない。現在は確認済みの準備状況だけを掲載する。

## アプリ内の口座・保有入力

`/portfolio`で「現在は保有なし」のまま、入力内容を確認→この内容を保存で開始できる。あとから口座の呼び名・特定口座/一般口座/NISA/未確認、源泉徴収、利用可能現金、銘柄コード、株数、平均取得単価を追加・修正できる。投資上限・最大下落率は任意。金額の空欄はnullで保持し、0円と区別する。単元未満の実保有も登録できる。口座番号や証券会社のログイン情報は収集しない。

今回ユーザーがアプリ内入力を明示したため、本人が入力した設定は本人専用クラウドDBへ保存する。PCが停止中でも保存・読込できる。認証された本人ID別のappend-only revisionを作り、同じ親revisionからの二重更新はDBのunique制約で防ぐ。古い画面からの保存は409で止まり、入力を残したまま保存済み内容を読み直せる。認証、same-origin、manual intent、厳密schemaを通った保存だけを受け付ける。原予測のテーブルは変更しない。

クラウド入力のPython側への取込・個別売買判断への接続は未実装。資金等が揃っても、評価・費用・税・価格データの確認を省略して推奨株数を出さない。本番へテスト口座・架空保有を登録しない。

## 原予測と手動調査

`PredictionSnapshot`はas_of、generated_at、data_as_of、selection/model/feature/data ID、対象銘柄、large-loss閾値、分位点alphaを保持する。対象は候補と全保有を完全に含める。調査対象は20日期待リターン順の候補上位20と全保有。元の予測値・モデル確率を調査結果で書き換えない。

固定7項目は利益の質、期待とバリュエーション、財務・希薄化、材料と時期、業界環境、流動性・保有リスク、反対材料。各項目に支持・注意・保留、根拠URL、公開時刻、確認時刻を記録する。支持・注意には根拠が必要。未調査を含む全体判断は支持にできない。有料調査APIや新契約は導入していない。

ローカルAPI（既存のloopback制限・manual intentヘッダーを使用）:

| 操作 | エンドポイント |
| --- | --- |
| 最新原予測と調査 | `GET /api/v1/daily/latest` |
| 正本・表・文章のexport | `GET /api/v1/daily/{snapshot_id}/export?format=json\|csv\|markdown` |
| import確認、レコード書込みなし | `POST /api/v1/daily/import/preview`、body: `jsonText` |
| 確定保存 | `POST /api/v1/daily/import/confirm`、body: `jsonText`, `confirmationHash`、header: `X-Stock-AI-Intent: manual-record` |

本人レビューの`continue_paper`と`reject`は記録できる。`adopt`は現在ブロックする。IDを手入力しただけで評価済みとせず、実際のevaluator/holdout証拠と個人設定を接続するまで昇格させない。60日経過による自動採用はない。

## 実行例

このcheckoutのソースを使うためPowerShellで`$env:PYTHONPATH='src'`を設定する。

```powershell
.venv/Scripts/python.exe -m stock_ai ops export-daily --snapshot-id <ID> --format json --output <保存先> --database <SQLite>
.venv/Scripts/python.exe -m stock_ai ops sync-private --snapshot-id <ID> --training-completed 18 --database <SQLite>
```

同期時の`STOCK_AI_PRIVATE_SITE_TOKEN`は環境変数またはOS側の秘密管理から供給する。ファイル、コマンド引数、公開サイトへ保存しない。送信先は本人専用originに固定、redirect拒否、SHA-256付きJSON、保存後の読戻し一致を必須にする。失敗してもローカル正本は残る。定期同期・Windows起動時実行は未接続。

再監査は`research audit-candidates --feature-selection <path> --candidate-campaign <path>`を3manifest分指定する。`scripts/audit_daily_evidence.py`は保存checkpointとラベル時点を読み取り専用で調べる。import lineageには当時のraw sourceが必要で、Git archiveのLF変換だけでは当時のbyte hashを復元できない。既存proofを書き換えない。

`--score-development`を追加すると、認証した開発OOFへ新しい順位・確率・分位点の診断を付ける。同点、NA、最小行数、log loss端点、交差分位点の規則は[指標契約](DAILY_EVALUATION_METRICS.md)に固定。元reportの指標とは別に保存し、選択・holdout・採用へ自動的に進めない。

## 残りの順序と終了条件

日次会計の固定注文評価器と[Decision Engineの連続実行](DAILY_STATEFUL_STRATEGY.md)を追加した。[入力・会計契約・検証範囲](DAILY_NAV_EVALUATOR.md)を参照。生価格、未収金、企業行動、約定不能、HOLDとの差を扱う。実市場adapter・個人税シナリオは引き続き未接続。

1. [26項目の評価試験票](evidence/daily-readiness-20261015/README.md)の不足を実装する。特に日次NAV、企業行動、約定不能を含む状態付き評価を実装し、固定注文の費用10/20/30/50bpsを手計算と照合する。元runの0/10/25/50bps設定は変更しない。
2. 5日・20日それぞれで開発OOFを比較する。全seed、cash/HOLD/等重み/momentum/Ridge/単一GBDT/ensembleを同一条件で比較し、欠損・停止銘柄を隠さない。単純な20日forward returnの加算をNAVにしない。
3. 特徴量・モデル・parameter・ensemble・uncertainty・判断規則・実用上必要な改善幅をholdout前に固定する。現時点で確定しているのは5日41列・20日51列の特徴量選択まで。
4. holdoutアクセス証跡を確認し、固定済みの選択を一度だけ最終評価する。結果を見て選択し直さない。現在のholdoutは本作業では評価していない。
5. 確定bundleからの日次refit・最新データ推論を実装し、原予測保存→保有との比較→クラウド同期を実データで通す。現在の`DailyAutomation(daily_only=True)`は順序の基盤で、live handlerは未接続。
6. 当時の訂正vintage、実行価格・費用の能力を確認する。現在のSINGLE_VINTAGE_AS_REVISEDと日足proxyでは実用適合を断定しない。資金・全保有・税・費用・リスク設定を本人から確定し、証拠付きの採用レビューを接続する。

実18候補の新指標診断は[保存証拠](evidence/daily-metrics-20261015/README.md)まで完了した。既存baseline report `47afb247…`は同じdataset IDだが、5日target・holdout境界2026-02-24で、今回の2026-03-04と異なる。旧summaryを直接比較表へ混ぜず、対象日・key・label・purge境界を合わせた開発比較を作る。これは既存holdoutへのアクセス履歴の安全性を断定するものではない。

[保存記録73ファイルのアクセス調査](evidence/holdout-access-inventory-20261015/README.md)では、holdout読込のtrue宣言や本番ledgerは見つからず、旧baselineの宣言sourceが評価期間を除外する経路であることを確認した。未記録アクセスや別保存先まで否定できる証拠ではないため、履歴の完全性はNOT_PROVENとする。

既存`build_decision_compatible_oof_predictions`は1/5/20日の完全bundleを要求する。別途[日次OOF adapter](DAILY_OOF_ADAPTER.md)を実装し、`research daily-oof`から5/20日・1日nullの研究用receiptを生成できる。horizon不足・較正履歴不足は理由付きで保存し、保有予測が欠ける比較は停止する。`research evaluate-daily-strategy`で前日の仮想約定を反映する研究会計に接続した。単一候補による接続確認であり最終モデル選択ではない。実価格・企業行動・費用契約を認証した実市場比較は残る。

v04のSB20/SB60区間は反例が再現された。統計的有意性や自動採用の条件には使わず、現段階では診断用とする。学習データは8月時点であり「今日の予測」と表示しない。実注文送信機能はない。

`research project-daily-market`で、[保存raw/normalizedの認証と日足projection](DAILY_MARKET_PROJECTION.md)を追加した。無約定行・元UL/LL・特殊コードを保持し、開発期間だけを読み出す。実データ確認は4日間まで。企業行動・約定能力・全期間の同一source接続を認証した実市場NAVは引き続き未完。

`research compare-daily-baselines`で、[同じ開発foldにそろえた回帰・リスクbaseline比較](DAILY_BASELINE_COMPARISON.md)を実行できる。ゼロ予測・20日momentum・V0 Ridge・過去の下落率/分位点・V0 Logisticと全18候補を照合し、固定の候補平均も記録する。モデルの予測指標とcash/HOLD等の状態付きNAVは区別する。 v3では固定Elastic Netとmomentum+revision/等重みルール順位も比較する。ルールは全同時点特徴量の母集団で正解結合前に順位化し、リターン単位のMSEを付けない。

## 検証と公開

本人専用アプリの入力は `ops pull-private-portfolio` でPCへ取り込める。
[取込手順](MANUAL_PORTFOLIO_IMPORT.md)と[公開・実入力検証](evidence/manual-portfolio-import-20261015/README.md)を参照。
保存版を照合してローカルへ確定した後に、同じ版だけをPC取込済みと表示する。
この記録を約定/現金/税台帳や個人向け推奨の完成とみなさない。

`research crossfit-daily-ensemble`は[3区間の時系列アンサンブル評価](DAILY_ENSEMBLE.md)を行う。重み学習・確率/分位点調整・後続評価を分け、各境界で未成熟labelを除外する。個別候補と単純平均を同じ後半期間で比較する。最終selectionやholdout入口とは別の研究診断である。

[実18候補の比較結果](evidence/daily-ensemble-20261015/README.md)では、順位の集計指標は改善したが、確率/分位点補正は誤差を悪化させた。個別期間の悪化も保持しており、較正成功・統計的有意差・採用可能とは判定しない。コードは全650試験PASS、coverage86.58%。

Python: `ruff check .`, `mypy src`, `pytest`, `pytest --cov`。Windowsのrunnerテストはcleanなsource commitを要求するため、checkpoint後に実行する。Git safe.directoryは必要なプロセス内にだけ設定する。テストJSONはUTF-8を明示。

`private/`: Nodeのschema/fault tests、TypeScript、eslint、Sites build、390px表示確認。`web/`は既存PWAのlint/typecheck/test/buildを維持。履歴sourceのコピーは科学的証拠としてlint書換え対象から除き、coverage分母は実際の`src/stock_ai`に限定する。

Sitesは既存`hosted/`と別のproject。publish用の隔離コピーは`.demo-artifacts/private-site-publish`。Windowsではhelperのプロセス内PATHへGit Bashを追加し、`TAR_OPTIONS=--force-local`を設定する。Nodeのnpm wrapperもcheckout内だけに置く。グローバル設定は変更しない。正規helperがpushしたcommitと対応archiveだけをprivate deployへ渡す。
