# 開発期間の日次市場データの認証

2026-10-15。`research project-daily-market`は保存済みJ-Quants V2の日足を日次評価用に読み出す。元のraw/normalizedファイルや固定学習datasetは書き換えない。実市場NAVの前段として証拠と不足能力を保存する。

## 入力と認証範囲

入力JSONの`catalog_path`、`store_root`、`feature_selection_path`、`start`、`end`、`source_snapshot_as_of`を明示する。`revision_policy`は`SINGLE_VINTAGE_AS_REVISED`のみ。feature selectionのcontent identityとmetadata hashを確認し、終了日がその`locked_holdout_start`以降ならcatalogを開く前に拒否する。

DuckDBをread-only transactionで開き、指定期間・vintage内で品質合格、ingestion成功、Bulk完了のobjectを対象にする。normalized行が指すraw objectと、catalog/manifest全15項目、path、byte hash、行数、行metadata、レコードhash、キー集合、生OHLC/出来高/売買代金/調整係数を照合する。空partitionは同じpayload/dateのrawとの一意な組を確認する。読み込み後にもverifyする。

複数vintageではavailable_at、received_at、payload_hashの順で版を選ぶ。後日の追加が以前の指定vintageの結果を変えないことを試験する。これはローカル証拠の整合性検証であり、providerの訂正前の値を復元するものではない。projectionコマンドはfeature selectionが宣言したdataset IDを記録するが、dataset構築時の全source frameとの一致はコマンド内では検証しない。

別の[元データ識別値照合](evidence/daily-source-identity-20261015/README.md)で、固定feature selection→build→dataset metadataと全5種類のsource frameを認証した。normalized 13,015 objectの処理前後hashを検証し、株価・銘柄一覧は各9,801,708行を含む全5種類で学習時の識別値と完全一致。これは同一入力の確認であり、全期間raw/normalized行ペア、ユニバース/営業日完全性、企業行動/執行能力の認証や`evaluation_ready`への昇格ではない。

## 欠損・コード・執行能力

四本値・出来高・売買代金がすべてnullの行は`reported_no_trade`として残す。正で揃った行は`reported_trade`、一部欠損やゼロは`incomplete_bar`。欠けた行から無約定・上場廃止を推測しない。負値・非有限値・不正なUL/LLは拒否する。UL/LL未収録はnullを保つ。

5桁provider codeを正本キーとして保持する。末尾0以外は`nonstandard_provider_code`、4文字`symbol`はnullにして普通株への誤結合を防ぐ。末尾0でも株式/ETF/REIT等の区別や投資対象適格性はこのprojectionでは確定しない。

UL/LLをrawから回収するが終値の約定可否へ変換しない。非単位または欠けたadjustment factorには企業行動証拠が必要というflagを付け、分割イベントを自動作成しない。買い/売りstatusはunknown、capacity・呼値・決済時刻はnull、企業行動は未認証、`evaluation_ready=false`。

根拠は[J-Quants V2日足仕様](https://jpx-jquants.com/ja/spec/eq-bars-daily)（2026-10-15確認）。特にULは高値の到達判定であり、引けの買付不能の証拠ではない。

## 実行と限界

```powershell
.venv/Scripts/python.exe -m stock_ai research project-daily-market --input <入力JSON> --output-root artifacts/daily-market
```

正本JSONはsource metadata、抽出行、集計、不足能力、実装hash、pandas/DuckDB版を持つ。既存receiptは上書きしない。明細はローカル保存でクラウドへ送らない。指定窓をメモリ上に構成するため、全期間の処理前に分割/ストリーミングが必要。

初回の実データ確認は2025-11-04〜11-07の4日、8object、17,669行。[初回証拠](evidence/daily-market-20261015/README.md)を保持している。

続いて[開発評価期間全体の照合](evidence/daily-market-development-20261015/README.md)を完了した。2024-07-31〜2026-03-03の42区間、386営業日、raw/normalized 772 object、1,702,477行を認証。営業日全体の欠落・予定外の日付・OHLCの大小関係違反は0。無約定73,469行、特殊code1,675行、企業行動要確認394行を保持した。全receiptのcontent identityとbyte hash、区間集計も独立に再確認している。

続く[当日銘柄一覧との照合](evidence/daily-universe-development-20261015/README.md)で、同じ386営業日のmaster raw/normalized 772 objectを認証した。master/価格の全1,702,477キーが一致し、既存対象ルールに一致する1,471,945行にも価格の欠落は0。対象銘柄の無約定10,038行、調整要確認359行、対象外市場・特殊codeを削除せず、日別の外部結合をローカルParquetへ保存した。単元株数はmasterが提供しないためnullを維持する。

ここで確認したのは固定vintageにおける当日銘柄一覧と価格の網羅であり、訂正前の情報を復元したことではない。訂正前vintage、上場廃止・企業行動、約定能力、実用費用、個人設定の接続は残る。実市場戦略成績、全候補のNAV比較、最終selection/holdout、最新推論、実用採用は未完。実注文なし。

2026-10-15の[接続確認](evidence/live-data-access-20261015/README.md)では、株価Bulk一覧と銘柄一覧の2要求がHTTP403。これは当時の履歴として残す。2026-10-18に本人がLight契約済みと連絡し、TOPIX HTTP200、基本5種類の開発期間取得に成功した（D167）。旧保存先とは別版で固定し、2024-10月の22営業日・96,671行・raw/normalized44objectを本projectionで再認証。4,276行の無約定、85行の特殊code、7行の企業行動要確認を保持し、`evaluation_ready=false`と不足能力を維持した。現在取得した訂正後vintageは当時の既知情報ではなく、取得対象は最終期間前の開発用であって今日の相場更新ではない。私有明細とhashは`.demo-artifacts/light-resume-20261018/`に保持し公開しない。
