# 日次NAV評価器の検証証拠

2026-10-15。市場成績ではなく、テスト専用の会計入力を使う。本人の資金・保有は使用しない。`summary.json`と`fixtures/`の入力/strategy/HOLD receiptを照合できる。

- 新規日次NAV試験45 PASS。既存cost/tax・simulator・domain・CLI・daily API/contractsを含む105 PASS。新規NAV moduleのbranch込みcoverage92%。
- Ruff全体PASS。mypyは54 modules PASS。
- 固定株数の片道費用0/10/20/30/50bpsを往復控除し、手値と完全一致。2回の100株×100円取引で、それぞれ総費用0/20/40/60/100円。
- 20session保有を21日連続開始し、41sessionの各日NAVが独立cohort計算と一致。期末の合成利益42,000円は市場予測・収益実績ではない。
- 無変更HOLDとの比較、予約現金、決済待ち、部分約定、停止、欠損mark、分割・端数・配当・現金交付などの対応は[会計契約](../../DAILY_NAV_EVALUATOR.md)と`tests/test_daily_nav.py`を参照。
- 最初の制限環境で既存fixture CLIがPermissionError。TestClient経路の継続も中断し、作業フォルダー内のbasetempと許可されたプロセスで再実行して105 PASS。テストや仕様は緩めていない。
- dotted module名をcoverage sourceに渡すとNumPy再importでcollectionが失敗したため、既存のfilesystem source設定でcoverage runを使用。新規評価器の通常pytestも45 PASS。

全体pytest/coverageはsource checkpoint後に実行して追記する。実データadapter・戦略連続実行・税シナリオ・全候補比較・最終holdoutは未完。Goal全体の完了とはしない。原学習artifact・source pin・失敗履歴は保持、実注文なし。
