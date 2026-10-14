# 開発期間の日次市場データの認証

2026-10-15。`research project-daily-market`は保存済みJ-Quants V2の日足を日次評価用に読み出す。元のraw/normalizedファイルや固定学習datasetは書き換えない。実市場NAVの前段として証拠と不足能力を保存する。

## 入力と認証範囲

入力JSONの`catalog_path`、`store_root`、`feature_selection_path`、`start`、`end`、`source_snapshot_as_of`を明示する。`revision_policy`は`SINGLE_VINTAGE_AS_REVISED`のみ。feature selectionのcontent identityとmetadata hashを確認し、終了日がその`locked_holdout_start`以降ならcatalogを開く前に拒否する。

DuckDBをread-only transactionで開き、指定期間・vintage内で品質合格、ingestion成功、Bulk完了のobjectを対象にする。normalized行が指すraw objectと、catalog/manifest全15項目、path、byte hash、行数、行metadata、レコードhash、キー集合、生OHLC/出来高/売買代金/調整係数を照合する。空partitionは同じpayload/dateのrawとの一意な組を確認する。読み込み後にもverifyする。

複数vintageではavailable_at、received_at、payload_hashの順で版を選ぶ。後日の追加が以前の指定vintageの結果を変えないことを試験する。これはローカル証拠の整合性検証であり、providerの訂正前の値を復元するものではない。feature selectionが宣言したdataset IDを記録するが、そのdataset構築時の全source frameとの一致はまだ検証しない。

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

実データ確認は2025-11-04〜11-07の4日、8object、17,669行。[検証証拠](evidence/daily-market-20261015/README.md)を参照。全期間、PIT銘柄/営業日の完全性、企業行動、約定能力、実用費用、個人設定の接続は残る。実市場戦略成績、全候補比較、最終selection/holdout、最新推論、実用採用は未完。実注文なし。
