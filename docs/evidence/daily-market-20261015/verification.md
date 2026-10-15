# 検証結果

Source checkpoint: `da999e11e48bb29d0497bf13e1ed3d1eaf2e217f`。

- Ruff全体: PASS。mypy src: 58 modules PASS。
- 新規30試験。保存層・NAV・戦略との関連115試験PASS、32.27秒。新moduleのbranch込みcoverage94%。
- 全Python回帰: **590 PASS**、109 warnings、475.50秒。coverage **86.28%**、既定85%基準を維持。
- 実データ: 4日・8object・17,669行。receipt `23db5bc7074b4b3946ee56ac886f38dba88992602337d86864840fc00826f0de`。明細はローカル保存、summaryのSHAで照合。
- source commit後、元receiptと現行実装のbyte hash一致を再確認。

実行コマンドは`.venv/Scripts/python.exe -m ruff check .`、`-m mypy src`、`-m pytest --cov=src/stock_ai --cov-report=json:.demo-artifacts/coverage-daily-market-full.json --cov-report=term --basetemp .demo-artifacts/pytest-daily-market-full-1`。Git safe.directoryはprocess内設定のみ。一時DBを使う試験は承認された実行でworkspace内basetempへ保存した。private UIには今回変更なし。

完全logは`.demo-artifacts/tests-daily-market-full-1.log`、関連試験は`tests-daily-market-2.log`。これらとcoverage JSONのhashをsummaryへ保存。最初の実データ拒否・lint/型修正もREADMEに保持している。

全期間PIT/企業行動/約定能力の認証、実市場NAV、全baseline比較、個人税、最終selection/holdout、最新予測への接続は未完。これは市場利益の実証ではない。Goal active、実注文なし。
