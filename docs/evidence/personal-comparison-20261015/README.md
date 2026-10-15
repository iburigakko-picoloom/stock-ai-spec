# 個人入力・台帳照合と研究HOLD比較

関連129試験と最終の個人比較34試験PASS。Ruff全体/mypy63 modules PASS。個人比較moduleのcoverageはverification.jsonへ保存し、全体coverageと区別する。source checkpoint後の全747試験も成功し、詳細を末尾とfull-regression.jsonへ保存した。

合成試験で、100株売却/100株購入の各費用1,000円・推定税2,000円・残現金196,000円・HOLD比26,000円を独立手値と照合。複数口座の共通予算、NISA売却後の同日枠非回復、予約現金、単元未満保有、入力不一致、未反映/未解決約定、現在日付/11:30固定、途中変更拒否、原記録不変、APIの時計と手動意図も確認した。

本人の保存入力は保有なし/口座0/資金・リスクnullのまま読み出した。台帳・予測・設定・市場等の不足を返し、提案は生成しない。SQLite全schema/recordの読み取りdump hashは処理前後で一致。個人のraw入力・owner IDはこの証拠に含めず、集計とhashだけを保存した。

最初の試験は日次v2 fixtureのhorizon指定漏れで23失敗、その修正後は試験側の売買区分/既存HTTP428想定で2失敗。いずれも既存契約へ試験を合わせ、検証条件を弱めていない。module名を指定したcoverage起動はNumPy初期化で失敗し、既存標準のsource-directory指定へ戻した。全失敗logを保持。

PC/ローカルAPIの研究比較を実装した段階。初回台帳の本人照合・確定、クラウドの補足設定/比較表示、現実の価格/約定/税/リスク前提、実市場NAV、最終selection/holdoutと採用、最新推論/同期は未完。実注文なし。詳細は../../PERSONAL_COMPARISON.md。

全体回帰はsource `7eea42a44642ad6ddf520c5359edfb7295c000f8`で747 PASS、coverage86.95%（基準85%）。開始/終了時刻とlog/coverage SHAはfull-regression.jsonを参照。コード全体の回帰成功であり、未接続の実市場検証やモデル採用の完了ではない。
