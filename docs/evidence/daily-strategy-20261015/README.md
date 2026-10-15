# 連続日次判断の検証（2026-10-15）

source checkpoint `9d39864c010a4d1fbacdacbf2e2e1182b4710f2a`。このフォルダの戦略成績はすべて合成テスト専用入力であり、実際の市場成績・本人の資金・モデル採用ではない。

## 実装と試験

29個の追加試験を含む関連112試験PASS。新規daily_strategy moduleのbranch込みcoverage99%。Ruff全体、mypy57modules PASS。全体回帰は`verification.md`へ記録する。

独立した会計例:

- 30万円の仮想現金から1000円の株を300株提案しても、日々100株しか約定しない場合、翌日提案は200株、次は100株。実保有100→200→300株、現金20万→10万→0円を引き継ぐ。
- 最終日だけ終値1100円とする上記例では、NAV33万円、現金HOLD30万円、差3万円。これはテストの手計算値。
- 片道10bpsでは実際の100株約定2回に各100円を課し、保有200株・現金99,800円・取得単価1001円・費用計200円。売買費用を提案時と約定時で二重控除しない。
- 売却不能の保有は翌日も残り、全保有として再評価する。受領前の売却代金はNAVに含むが、判断時の買付余力に含まない。売却後も配当権利を保持し、支払後の現金へ反映する。
- 判断前の分割を株数/原価へ反映し、古い単位の参考価格では比較を停止。判断後の分割は元単位の注文を失効する。
- 将来の約定価格/終値を変更しても、その時点の判断・それ以前の状態は完全一致する。実際の約定結果のみ変わる。

不足予測・価格・銘柄・流動性・古い価格、探索上限超過を停止理由として保存し、保有を消さない。停止のある評価は`decisions_complete=false`。生成注文を固定注文評価器へ再投入した結果が、連続評価と完全一致する。

日次研究用提案のflagが汎用engineの既定値falseになっていた点も是正し、DailyDecisionAuditとresearch-onlyを必須にした。原予測、価格、現在portfolio、candidate evidenceのhashがproposal IDに結び付く。実注文の指示ではない。

`0d5beb6efa0a99ac02b0da419fefd7baf49dab6a14e9053dedcb3da9b755b43e.json`はpytestが生成した実receiptのbyte一致コピー。`summary.json`にsource hash・数量・資金・NAV差とfixture表示を保持。JSONのGit改行変換は無効。最初の証拠抽出はDecimalの文字列末尾の0の違いを厳密比較して停止したため、数値として照合する抽出へ修正した。テスト結果・正本receiptは変更していない。

## 次の実市場接続の確認

`source-schema-inspection.json`はlocal catalogをread-onlyで開き、5dataset × raw/normalizedの最新1objectずつ、計10objectのschemaとbyte hashを検査した記録。価格・リターンなどの値は解析していない。全履歴のschema一致、null率、当時vintage、完全なPIT認証を証明するものではない。

保存raw株価にはUL/LLがあるが、選んだnormalized株価schemaにはない。raw財務にはDiv/FDiv列があるが、権利・支払時刻を持つイベント列は確認できない。銘柄単元には列と欠損理由列があるが、値の充足は未検査。catalogには特別気配/証券口座決済/独立企業行動のdatasetがない。

公式V2仕様でも、ULは終値でなく当日の高値の到達を表し、特別気配や値幅上限下限そのものは提供されない。よってULだけを「終値で買えない」という実証に使わない。同仕様は当時の利用可能日時と訂正前データを提供しないこと、現金配当を価格調整に含めないことも明記している。[公式株価四本値仕様](https://jpx-jquants.com/ja/spec/eq-bars-daily)（2026-10-15確認）。

次は既存rawの認証と執行関連項目の別projection、企業行動・約定能力の欠落判定へ進む。既存normalized/学習成果を上書きせず、不明をtradableや配当0に補完しない。追加有料providerの導入・契約変更は行っていない。

全baseline比較・固定selection・holdout・最新予測・個人口座/税との接続は未完。実注文なし。[実行契約](../../DAILY_STATEFUL_STRATEGY.md)。
