# 日次版の実装と残作業

2026-10-15。日次版を先に進め、前場版は別工程とする。現在は研究用の基盤段階であり、全計画の完了・実用採用を意味しない。

## 現在使えるもの

- 学習済み18候補（5日・20日×3方式×3seed）のreport/OOF認証。成功・失敗履歴、元のsource pinを保持。
- 日次Prediction v2。5日・20日の原予測を保持し、1日は未提供（null）。Decision Engineの日次設定は重み0/0/1、リスクは20日。
- 原予測・7項目の手動企業調査・本人のレビューを別の改変不可レコードとしてSQLiteに保存。JSONが正本、CSV/Markdownも同じsnapshot ID。
- APIによるimport preview→hash確認→idempotent confirm、保存検証・既存backup/restoreへの追加対応。
- 本人専用のスマホ閲覧サイトと、PCからの最小結果同期。サイト保存後の閲覧はPCへの接続を必要としない。

サイト: https://stock-ai-private-daily.manato0618.chatgpt.site

実データの予測はまだ生成・同期していない。サイトの18/18は研究候補の学習完了数であり、推奨銘柄数やモデル採用済み表示ではない。現在は確認済みの準備状況だけを掲載する。

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

## 残りの順序と終了条件

1. [26項目の評価試験票](evidence/daily-readiness-20261015/README.md)の不足を実装する。特に日次NAV、企業行動、約定不能を含む状態付き評価を実装し、固定注文の費用10/20/30/50bpsを手計算と照合する。元runの0/10/25/50bps設定は変更しない。
2. 5日・20日それぞれで開発OOFを比較する。全seed、cash/HOLD/等重み/momentum/Ridge/単一GBDT/ensembleを同一条件で比較し、欠損・停止銘柄を隠さない。単純な20日forward returnの加算をNAVにしない。
3. 特徴量・モデル・parameter・ensemble・uncertainty・判断規則・実用上必要な改善幅をholdout前に固定する。現時点で確定しているのは5日41列・20日51列の特徴量選択まで。
4. holdoutアクセス証跡を確認し、固定済みの選択を一度だけ最終評価する。結果を見て選択し直さない。現在のholdoutは本作業では評価していない。
5. 確定bundleからの日次refit・最新データ推論を実装し、原予測保存→保有との比較→クラウド同期を実データで通す。現在の`DailyAutomation(daily_only=True)`は順序の基盤で、live handlerは未接続。
6. 当時の訂正vintage、実行価格・費用の能力を確認する。現在のSINGLE_VINTAGE_AS_REVISEDと日足proxyでは実用適合を断定しない。資金・全保有・税・費用・リスク設定を本人から確定し、証拠付きの採用レビューを接続する。

v04のSB20/SB60区間は反例が再現された。統計的有意性や自動採用の条件には使わず、現段階では診断用とする。学習データは8月時点であり「今日の予測」と表示しない。実注文送信機能はない。

## 検証と公開

Python: `ruff check .`, `mypy src`, `pytest`, `pytest --cov`。Windowsのrunnerテストはcleanなsource commitを要求するため、checkpoint後に実行する。Git safe.directoryは必要なプロセス内にだけ設定する。テストJSONはUTF-8を明示。

`private/`: Nodeのschema/fault tests、TypeScript、eslint、Sites build、390px表示確認。`web/`は既存PWAのlint/typecheck/test/buildを維持。履歴sourceのコピーは科学的証拠としてlint書換え対象から除き、coverage分母は実際の`src/stock_ai`に限定する。

Sitesは既存`hosted/`と別のproject。publish用の隔離コピーは`.demo-artifacts/private-site-publish`。Windowsではhelperのプロセス内PATHへGit Bashを追加し、`TAR_OPTIONS=--force-local`を設定する。Nodeのnpm wrapperもcheckout内だけに置く。グローバル設定は変更しない。正規helperがpushしたcommitと対応archiveだけをprivate deployへ渡す。
