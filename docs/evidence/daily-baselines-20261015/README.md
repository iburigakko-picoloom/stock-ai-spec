# 同一開発foldの実18候補と回帰baseline比較

固定datasetと候補campaign/report/OOFを認証し、元の評価キー・値・foldと完全一致する比較を実行した。5日1,327,530行・6fold、20日1,044,317行・5fold。全18候補の回帰予測、ゼロ予測、20日momentum、V0 Ridge(alpha5)、固定候補平均を同じ観測で採点した。

Source checkpoint: `304d3e8dde32ea6d13aa185d465238584e06f209`。canonical receipt: `e297ff4e0fff429379956ab00e738b5bedf1ea7b4fc9a6b3d477682a28f8571c`。元receipt・OOFはartifacts/daily-baselines/に保持し、summary.jsonにSHAと集計を保存。原dataset・学習成果は変更していない。

| 期間 | 比較手法 | seed | MSE | 日次平均Rank IC |
|---|---|---:|---:|---:|
| 5日 | catboost | 17 | 0.00365033 | 0.045001 |
| 5日 | catboost | 29 | 0.00364909 | 0.041460 |
| 5日 | catboost | 43 | 0.00364557 | 0.041300 |
| 5日 | lightgbm | 17 | 0.00365120 | 0.041239 |
| 5日 | lightgbm | 29 | 0.00365052 | 0.040573 |
| 5日 | lightgbm | 43 | 0.00368159 | 0.040232 |
| 5日 | xgboost | 17 | 0.00365358 | 0.041415 |
| 5日 | xgboost | 29 | 0.00365759 | 0.040457 |
| 5日 | xgboost | 43 | 0.00367158 | 0.040773 |
| 5日 | equal_weight_candidate_mean | — | 0.00364809 | 0.043494 |
| 5日 | momentum_20d | — | 0.02018274 | -0.012909 |
| 5日 | ridge_v0 | — | 0.00366021 | 0.010663 |
| 5日 | zero_return | — | 0.00370793 | null |
| 20日 | catboost | 17 | 0.01586041 | 0.072274 |
| 20日 | catboost | 29 | 0.01590399 | 0.071277 |
| 20日 | catboost | 43 | 0.01583747 | 0.073409 |
| 20日 | lightgbm | 17 | 0.01585263 | 0.071394 |
| 20日 | lightgbm | 29 | 0.01607543 | 0.075494 |
| 20日 | lightgbm | 43 | 0.01621282 | 0.073761 |
| 20日 | xgboost | 17 | 0.01612373 | 0.076632 |
| 20日 | xgboost | 29 | 0.01593360 | 0.072222 |
| 20日 | xgboost | 43 | 0.01645530 | 0.070329 |
| 20日 | equal_weight_candidate_mean | — | 0.01588630 | 0.077237 |
| 20日 | momentum_20d | — | 0.03165786 | -0.005679 |
| 20日 | ridge_v0 | — | 0.01600800 | 0.029052 |
| 20日 | zero_return | — | 0.01608674 | null |

MSEは小さい方、Rank ICは大きい方が良いという別々の診断。異なるhorizonのMSEを直接優劣比較しない。zero_returnは現金保有の成績ではなくゼロ予測の誤差で、順位ICは定義できない。将来20日returnを日次NAVへ足し上げない。固定候補平均は学習したstackingではない。

全foldでlabel受信時刻<fit cutoffとfeature利用時刻を確認。Ridgeは最大数百万行のtrainを32,768行ずつ処理し、全行の中央値と中心化共分散を使った。モデル係数・各fold条件・予測は正本receipt/Parquetで再確認できる。

新規23試験PASS、新module coverage89%、Ruff全体/mypy59modules PASS。通常Ridgeとの数値一致、未来値変更による過去不変、候補/行/正解/fold/受信時刻の不一致拒否、改変source拒否を検証。初期のfixture Path型、source認証のsymbol列不足、DuckDB/Pandas時刻単位差による失敗を修正し、tests-daily-baselines-1/2/3.logを保持。全体回帰はverification.mdへ記録。

残り: probability/quantile baseline、cross-fitted learned ensemble、全戦略の状態付きNAV、企業行動・約定能力・実用費用・個人税、最終selection/holdout、最新推論。単純な開発指標だけでモデルを採用・除外していない。実注文なし。
