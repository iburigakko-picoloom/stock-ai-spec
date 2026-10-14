# 開発OOFの評価指標

2026-10-15。`daily-development-metrics-v1`は、認証した開発OOFの診断用。過去の学習reportを変更せず、`audit-candidates --score-development`で別receiptに追加する。モデル選択、統計的有意性、採用の判定ではない。実holdoutを読み込まない。

## 順位

- keyは日付・銘柄。重複、空key、日中timestampを拒否する。日付内を銘柄の文字列昇順に並べ、予測・targetが同点の場合の優先順を固定する。入力行を逆順にしても結果は変わらない。
- targetまたはpredictionが非有限の行は除外数を明示する。各日の有効行数とICを残し、有効行ゼロの日も消さない。
- ICは平均順位のSpearman。有効3行以上、両方が非定数の場合だけ計算する。定数・欠損・小標本はnull。平均は有効日を等重み、標準偏差はddof=1。ICIRは平均/標準偏差で、標準偏差0や1日だけの場合はnull。別に有効行数で加重したICも出す。有意性への年率換算はしない。
- 既存の学習reportは2行でもICを計算していた。新しい最小行数を過去のreportへ遡及しない。
- relevanceは各日のtarget平均percentile順位から`min(ceil(percentile*5)-1,4)`で0〜4へ変換する。gainは`2**grade-1`。rawの負returnをgainに使わない。
- NDCG@5/10/20は`1/log2(position+2)`で割引し、正解順のDCGで正規化する。Kは有効銘柄数まで縮め、有効1銘柄以下はnull。
- Precision@Kは予測top-Kと正解top-Kの集合重複率。正returnの勝率ではない。K超過では全銘柄が選ばれ、Precisionは1となるため、NDCG・top-K実現平均と併記する。
- 順位指標とtop-K実現平均は有効日等重み。MSEは有効行等重み。全欠損なら総合metricsもnull。

## 下落確率

イベントはreportで固定された`target <= large_loss_threshold`。等号を含む。確率は0〜1の実値、イベントは0/1、全値有限・同じ長さを必須とし、範囲外をclipして受け入れない。

Brierは元の確率で平均二乗誤差を計算する。log lossだけfloat64でepsilon=1e-8、上限1-epsilonへclipする。完全正解のBrierは0、完全逆は1。log lossは正解端点でも約1e-8、逆端点では約18.42068となる。過去のreportはBrierにもclipを適用していたため、端点付近の微小差を履歴変更で消さない。

reliabilityはfloat64の`linspace(0,1,11)`による10bin。左端を含み、右端は最後のbinだけ含む。非空binの件数、予測平均、実際の発生率を保存する。ECEは件数加重の絶対差。base rateも出す。確率・分位点の総合値は行等重みで、日付等重みICとは集計単位が異なる。regime別の比較や後続期間の較正は別工程。

## 分位点

alphaは0〜1の内側で厳密な昇順。予測は行×alphaの有限行列。pinballは`max(alpha*(y-q),(alpha-1)*(y-q))`の行平均。coverageは`y<q`と`y<=q`を別々に出し、同値がある場合の差を保持する。

隣り合うalphaで予測が減少した行をcrossed_rowsとして数える。交差を並べ替えて修復せず、元の予測で採点する。1つのalphaしかない場合はcrossing_check_available=false。現在の候補の単一alphaを「非交差確認済み」とは扱わない。

## 実行と証拠

既存の3campaign、正式feature selectionを指定して、通常の認証に`--score-development`を追加する。report/OOFのbyte・logical hash、source pin、正式feature、task整列、holdout境界の認証が先。新しい結果にも原report ID、指標source hash、NumPy/pandas/SciPy版を残す。元reportのmetricsは別フィールドに保持する。

`tests/test_evaluation_metrics.py`には負return、K超過、同点・欠損、日付等重み、確率端点・base rate・過信、pinball・交差の独立手計算ケースがある。`tests/test_daily_readiness.py`で27候補fixtureの認証→全task採点→receipt保存を確認する。26試験票全体、日次NAVへの実戦略接続、実用費用、最終holdoutは完了していない。
