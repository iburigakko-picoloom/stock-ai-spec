# 検証結果

Source checkpoint `a0be50799821ac762f8926dfaa79ec0f380be932`。

- 全Python回帰 **626 PASS**、776 warnings、793.95秒、coverage **86.42%**（基準85%）。
- 関連36試験PASS（追加13）、変更module coverage91.08%。Ruff全体PASS、mypy src59 modules PASS。
- 実18候補と確率/分位点baseline比較exit0。5日1,327,530行/6fold、20日1,044,317行/5fold。全trainを維持しLogisticの収束確認。
- 18候補の大幅下落確率/分位点指標が過去の認証済み診断と完全一致。元の回帰評価指標も完全一致。v1 OOFとkey/targetを完全照合しbaseline予測の差はrtol1e-10/atol1e-12以内。
- 元receiptのbyte SHA、今回receiptとOOFのbyte SHA、実装source hashを確認。

実行: `.venv/Scripts/python.exe -m ruff check .`、`-m mypy src`、`-m pytest --cov=src/stock_ai --cov-report=json:.demo-artifacts/coverage-daily-risk-full.json --cov-report=term --basetemp .demo-artifacts/pytest-daily-risk-full-1`。Git safe.directoryはprocess限定。OMP/OPENBLASは1thread。試験DBはworkspace内で分離。

独立したsklearnのmedian-imputer/StandardScaler/LogisticRegression(C固定)との一致、batchサイズ・C変更、欠損/定数/大きな値、inclusive閾値、単一class fallback、未収束停止、未来の正解変更による過去fit/予測不変、task間as_of不一致拒否を検証。初回の2失敗はテスト側の固定閾値と分位点の完全float比較であり、修正前logも保持。警告は主に既存の日時処理とDuckDBの非推奨API。

完全logは`.demo-artifacts/tests-daily-risk-full-1.log`、`.demo-artifacts/tests-daily-risk-targeted-1/2.log`、`.demo-artifacts/daily-risk-actual-1.log`。CLI実行履歴はartifacts/daily-risk-baselines/runs/。hashはsummary.json。

予測診断は採用の証明ではない。費用/税/企業行動/約定能力を含む全戦略NAV、残りのrule/Elastic Net、cross-fitted ensemble、最終selection/holdout、最新推論、本人入力との接続は未完。実注文なし。Goal active。
