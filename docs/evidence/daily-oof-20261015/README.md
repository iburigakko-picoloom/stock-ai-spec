# 日次OOF接続の実データ検証（2026-10-15）

source checkpoint `2cd71677be20e656795e029875e23014682d7bee`。過去の5日・20日OOFを日次Prediction v2へ変換した接続確認であり、最新予測・モデル選択・採用・実注文ではない。

## 実測

明示的なLightGBM seed17の5日/20日ペアを使用。最良候補という意味はない。判断時点は2025-11-06 11:30 JST。

- 使用可能3,717銘柄。5日/20日がそろわない30銘柄は理由付きblockとして保持した。
- 1日予測は全件null、リスクhorizonは20日。
- リスク尺度は当時までに結果の受信条件を満たす962,235行・257特徴量日から求めた20日残差RMSE 0.126239260754756。これは信頼区間や個人向け最大損失の推定ではない。
- 原report・OOF・campaign・固定特徴量・datasetのidentityを認証。全列/全行の内容hash計算には保護期間も含むが、分析用に取り出すのは開発OOFに一致する時点列だけ。holdoutの成果を評価していない。
- 最終receiptと現在のadapter source SHA、1日null、件数、理由、較正件数を再照合した。元dataset byte SHAは `f344680f9d191885f856153175cb61cc2581c619770ed1c94fe442ef7366d8f8`。

正本は `99bb487396e9ddecb4ff14ee907f8cfae94235d954aa290876bb0bc558d081d6.json`。`summary.json`に正本file SHA、末尾LFを除いたreceipt ID、実装source SHA、元report IDsと集計を記録した。JSONはGitの改行変換対象外。最初の接続確認receiptは`.demo-artifacts/daily-oof-real-20261015`、途中の認証追加確認は`.demo-artifacts/daily-oof-authenticated-20261015`に保持した。最終証拠は固定sourceで別途再実行したもの。

## 検証

日次adapter、新規source認証、既存memory/NAV回帰の計97試験がPASS。新規moduleはbranch込み94%。時刻等号、受信遅延、Arrow microsecond単位、未来target変更による過去不変、冷始動、horizon不足、保有欠落、provenance不整合、5日と20日の予測が逆方向の場合の20日主体の入替比較を検査した。

実際の認証fixture bundleで、保護期間の未使用列を書き換え、Parquet/file/metadata hashを更新しても、固定content identityの不一致として拒否した。保護期間を改変する試験は合成fixtureに限り、実データは変更していない。

個別module名を`--cov`に指定した2回はNumPy初期化で失敗した。`--cov=src/stock_ai`の通常のソースディレクトリ指定で再実行し、同じ試験がPASS。失敗logも`.demo-artifacts/tests-daily-oof-3.log`と`-4.log`に保存。対象検証は`-6.log`。Ruff全体・mypy56modulesはPASS。

全体回帰の結果は`verification.md`へ別途記録する。

## 残る範囲

研究用の単日の予測→保有比較まで。毎日の状態を引き継ぐDecision Engine→NAV、実市場価格/企業行動/約定能力、全baselineと候補の同条件比較、固定selection、holdout、最新推論、本人の口座設定との接続は未完。実用的な費用・当時の訂正vintageも未証明。実注文なし。

方法とコマンド: [日次OOF契約](../../DAILY_OOF_ADAPTER.md)。元計画: [Drive評価計画v01](https://drive.google.com/file/d/1QsR-djCVznWj-AeeyVEo8xii2-lzWBFp/view)。
