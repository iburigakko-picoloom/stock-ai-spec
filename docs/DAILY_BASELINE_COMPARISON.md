# 同一開発foldでの単純モデル比較

`research compare-daily-baselines`は、固定済み5日・20日の各9候補と単純モデルを同じ開発OOF上で比較する。v2では大幅下落確率・下側分位点、v3ではElastic Netと固定ルール順位を追加した。既存のbaseline reportとv1 receiptを保持したまま、新しい比較を別artifactへ保存する。予測値の診断であり、cash/HOLDの資産推移や採用判定ではない。

## 比較前の照合

固定feature selectionのcontent identity、datasetの全logical identity、18候補のcampaign/report/OOF byte・logical hash、元のfeature列・source・holdout境界を認証する。dataset全体のhash計算は行うが、holdoutの正解を採点しない。比較対象は全3 family × 固定全seed × 5/20日で、欠けた候補や重複を拒否する。

各horizonの全candidateで、銘柄、日付、予測時刻、正解値、label終了日、fold番号を完全一致させる。共通部分だけを残して不足行を隠さない。reportの分割設定と元datasetの開発日付列からfoldを再構成する。特に最初の評価foldがtuning期間の後半で切られている場合も、元のvalidation開始日と学習終端を維持する。

学習対象は元のexpanding train日付、horizon分のembargo、`label_end < original_validation_start`を満たす行。検証キー・値を元OOFと照合し、labelの受信時刻がfit cutoffより厳密に前であることと、featureの利用可能時刻も検査する。利用不能な行を黙って除外して学習条件を変更せず、理由付きで停止する。

## 固定した比較手法

- `zero_return`: 常に0のリターン予測。順位ICは定義できずnull、MSEは計算する。現金保有のNAVではない。
- `momentum_20d`: 因果的な過去20日returnをそのまま使う。5日用への倍率調整やtuningは行わない。欠損は、そのfoldの学習内で同featureが観測された行のtarget平均へ置換する。
- `ridge_v0`: V0の24列、train内の正確な中央値補完、欠損indicator、平均/標準偏差で標準化、切片ありRidge、alpha=5。既存baselineの設定を固定し、新たな探索はしない。
- `equal_weight_candidate_mean`: 同horizonの全9候補の回帰予測を等重み平均する固定比較。学習したstackingや最終採用ensembleとは区別する。
- `training_loss_rate`: 当該foldのtrain内で`target <= large_loss_threshold`だった行の割合。閾値は候補reportと一致必須。
- `logistic_v0`: Ridgeと同じV0列・train内補完/標準化、L2正則化C=1、切片の罰則なし、クラス重みなし。全行の平均logistic loss＋`||w||²/(2*C*n)`をL-BFGS-Bで最小化する。trainが単一クラスの場合のみ、その発生率を返し、constant fallbackとして記録する。未収束は停止する。
- `training_quantile`: 当該foldのtrain targetの経験分位点。候補と同じalpha、線形補間（DuckDB quantile_cont / NumPy linear相当）。条件付き分位点ではなく、銘柄共通の比較値。
- `equal_weight_large_loss` / `equal_weight_quantile`: 全9候補の同じリスク出力を等重み平均。較正済みensembleとはみなさない。

Ridgeは1列ずつ正確な中央値を求め、行block単位の中心化共分散・targetとの共分散を合成して同じ線形方程式を解く。確率的勾配法やデータ間引きは使わない。batch既定32,768行、DuckDB memory_limit512MB、threads1。元候補OOFのfull logical認証は引き続き1候補ずつmaterializeするため、処理全体が一定メモリという意味ではない。

Logisticの標準化済みtrainを一時バイナリファイルへ保存し、目的関数・勾配の各計算ではblockずつ読み込む。学習内で常に0になる欠損indicatorだけ計算から除き、予測時の係数は0へ戻す。全行を使う通常のLogisticRegressionと同じ目的関数であり、SGDや間引きではない。maxiter500、gtol1e-8、ftol1e-14、maxls50を固定し、成功statusに加え最大絶対勾配1e-6以下を要求する。係数・切片・反復数・目的値・勾配・クラス件数を保存する。失敗時も一時ファイルを閉じる。

大幅下落はBrier、log loss、10bin ECEと各bin件数、分位点はpinball lossとstrict/inclusive coverageで比較する。全指標の定義はdaily-development-metrics-v1と一致し、各foldと全OOFの値を保存する。候補間の閾値・alpha、task間のas_ofを含む全keyを照合する。単一の下側分位点だけでは上下の予測区間のcoverageや分位点交差は検証できない。

## v3: Elastic Netと固定ルールの追加比較

v3はv1/v2と同じ認証・fold・評価keyを維持し、次を追加する。既存候補の成績を見た後の探索的な追加診断であり、独立した事前登録の採否検定とは扱わない。以下の係数・特徴・欠損処理は新しい実データ成績を計算する前に固定し、結果による調整や勝者だけの報告をしない。

- `elastic_net_v0`: Ridgeと同じV0列、train中央値、欠損indicator、train平均/標準偏差。目的関数は全行平均二乗誤差/2＋alpha×l1_ratio×L1＋alpha×(1−l1_ratio)×L2二乗/2、alpha=0.001、l1_ratio=0.5、targetの再標準化なし、切片に罰則なし。Gram統計を全trainからblockで蓄積し、循環座標降下を最大50,000反復。最小ノルム劣勾配の最大絶対値1e-9以下を必須とし、未収束は失敗として残す。係数・目的値・反復数・KKT残差・L2による目的値gap上界を保存する。
- `momentum_revision_rank`: 過去20日returnと会社予想修正の各同日内順位を等重み平均。
- `equal_weight_rule_rank`: 過去20日return、業種相対20日return、ROE、会社予想修正の各同日内順位を等重み平均。全特徴は正方向。

ルールは観測値の同順位にmidrankを使い、`(2*rank-n-1)/(n-1)`で−1〜1へ変換する。定数列、単一観測、欠損は中立0とし、欠損した特徴の重みを他の特徴へ再配分しない。順位母集団はその評価日のsource特徴量全行を使い、将来labelとの結合より前に構成する。正解未受領の銘柄も同時点の特徴があるなら順位計算へ入る。全peerの利用可能時刻を検査し、日付内でas_ofが異なる場合や遅い入力がある場合は停止する。指標計算だけを元OOFと同じ評価行へ結合する。

ルール出力は無次元の順位スコアであり、リターン・確率・売買命令ではない。順位指標だけを保存し、生returnを正解とするMSEを計算しない。Elastic Netはリターン単位としてMSEも比較する。これはcash/HOLD等の状態付きNAV、費用・税、モデル採用を完成させるものではない。

Elastic Netの目的関数は[scikit-learnの公式仕様](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.ElasticNet.html)と同じである。独立したSimpleImputer/StandardScaler/ElasticNetとの予測値・目的値一致、batchサイズ変更、定数/欠損、未収束、将来値変更、正解未受領peerの参加を試験する。

## 保存と検証

各foldの学習/評価境界、利用可能時刻の最大値、行数、中央値・平均・scale・係数、各baseline予測を保存する。各候補とbaselineの新版順位指標・MSE、固定平均の指標を同一receiptに集約する。OOF Parquetはbyte SHAを名前とし、既存ファイルの不一致や上書きを拒否する。実装source hashと依存ライブラリ版を記録する。CLIはSTARTED/SUCCEEDED/FAILEDを追記保存し、失敗を消さない。

```powershell
.venv/Scripts/python.exe -m stock_ai research compare-daily-baselines --feature-selection <固定feature.json> --candidate-campaign <h5-legacy.json> --candidate-campaign <h5-continuation.json> --candidate-campaign <h20.json> --dataset <固定dataset.parquet> --output-root artifacts/daily-baselines
```

検証は通常のmedian-imputer/StandardScaler/Ridgeとの数値一致、batchサイズ不変性、欠損・定数列・大きい値、未来のvalidation変更による過去予測不変性、全候補の欠損/重複/改変拒否、protected rowの採点排除を含む。

v3の実データ比較はsource checkpoint後に別receiptへ保存する。cross-fitted learned ensembleは別の時系列診断として検証済み。cash/HOLD/等重みの実市場状態付きNAV、企業行動・実用費用・個人税、最終selection/holdoutと最新推論は残る。ここでの正解は重なる将来returnであり、日次リターンとして足し上げない。SB20/SB60を有意性や採用の根拠にしない。実注文なし。
