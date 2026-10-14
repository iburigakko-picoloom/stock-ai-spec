# 日次市場projectionの検証証拠

実市場4日間（2025-11-04〜11-07）をsource vintage 2026-08-29 23:30 JSTでread-only抽出。固定feature selectionは13c8676f…、holdout境界は2026-03-04。holdout partitionは対象外。

raw/normalized計8objectのcatalog・manifest・byte hash・行metadata・キー・値の一致を認証。17,669行のうちreported_trade16,899、reported_no_trade770。nonstandard provider code20行を普通株へ統合せず保持した。非単位/欠損調整係数1行、UL=1が36行、LL=1が15行。provider全収録銘柄の小窓であり、投資対象ユニバースや約定可能数量の集計ではない。

元receiptはローカルartifacts/daily-market/に保存。summary.jsonへreceipt identityとbyte SHA、source metadata、集計だけを記録し、明細を再配布しない。実装は[日次市場projection契約](../../DAILY_MARKET_PROJECTION.md)。

初回の実データ実行は末尾0以外のprovider codeで拒否した（daily-market-actual-1.log）。provider code保持・symbol null・明示flagへ修正後、再実行成功（daily-market-actual-2.log）。元raw、normalized、学習datasetの変更なし。

追加30試験と既存保存層/NAV/戦略を合わせて115試験合格（32.27秒）。新moduleのbranch込みcoverage94%。最初の28試験も合格。その後、pandas.where(None)の型検査不一致とlintのregex指定を修正し、特殊コード/空partitionの試験を追加。Ruff全体/mypy58modules合格。全体回帰はverification.mdに記録する。

意味の根拠は[J-Quants V2公式仕様](https://jpx-jquants.com/ja/spec/eq-bars-daily)（2026-10-15確認）。約定能力・企業行動・実用費用は未認証。historical_as_known=false、evaluation_ready=false、adoption_eligible=false。全期間比較、モデル選定、holdout採点は実施していない。
