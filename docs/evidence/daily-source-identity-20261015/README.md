# 学習時の元データ5種類との識別値照合

固定feature selection → production buildのcontent identity → dataset metadata → 全5種類のsource frameという対応を読み取り専用で照合した。catalogや元ファイルは書き換えていない。

| 元データ | 最新版選択後の行数 | 検証したnormalized object数 | 学習時の識別値 |
| --- | ---: | ---: | --- |
| trading_calendar | 3,527 | 3,528 | 完全一致 |
| topix | 2,359 | 2,360 | 完全一致 |
| financial_summary | 185,307 | 2,388 | 完全一致 |
| security_master | 9,801,708 | 2,379 | 完全一致 |
| daily_prices | 9,801,708 | 2,360 | 完全一致 |

catalogの成功・品質合格・固定vintage内のnormalizedファイルを選び、元のpoint_in_timeと同じキー・available_at/received_at/payload_hash優先順位で最新版を選択。各ファイルのbyte SHAを処理前後に検証した。build IDは固定feature decisionのbuild_idと一致し、全source IDを含むcontent hashを再計算した。

hashのschemaにはPandasの型も含む。全体の欠損有無でnullable型を先に決め、各chunkを同じ型へ戻してから、元の_source_frame_idと同じ行hashを連結する。小規模試験は5,005行、最後のchunkだけに欠損がある整数/実数/文字列/真偽/時刻と全欠損列を含め、1/2/8 vector単位で元の全件計算と一致し、値改変を検出した。営業日/TOPIXは実データでも元の全件計算と一致。大型データは512MBのDuckDB予算と一時diskを使い、元の学習時source IDとの完全一致を確認した。

これは学習入力との同一性の確認。全期間のraw/normalized行ペア認証、PITユニバース/営業日完全性、配当/分割/現金交付、呼値/約定数量/決済、実用費用は別の未完項目。過去の訂正前vintageを復元したものではなく、SINGLE_VINTAGE_AS_REVISED制約は残る。

固定vintage全体の識別値を再計算するため、元データにはholdoutに当たる暦日も含む。予測・target・成績は計算しておらず、holdout評価や採用判定には使っていない。元のdataset/feature/report/OOFは変更していない。実注文なし。

summary.jsonに対応関係、source ID、schema、入力・log・実行scriptのSHAを保存。*.py.txtは実行したscriptのbyte一致コピーで、元の.demo-artifacts位置を前提とする。既存結果の上書きを拒否するため、再実行時は元の証拠を保持した別試行にする。
