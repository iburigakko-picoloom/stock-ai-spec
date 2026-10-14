# 確率・分位点比較のコード検証

Source `a0be50799821ac762f8926dfaa79ec0f380be932`。コード検証のcheckpointであり、実市場の成績や全計画の完了を示すものではない。

- 全回帰 **626 PASS**、776 warnings、793.95秒、coverage **86.42%**。基準85%維持。
- 関連36試験PASS、追加13。変更module coverage91.08%。Ruff全体PASS、mypy src59 modules PASS。
- 独立したsklearnのmedian/indicator/StandardScaler/LogisticRegressionとの数値一致を、batchサイズ/C変更・欠損/定数/大きな値で確認。
- 閾値の等号、単一class fallback、未収束停止、未来の正解変更による過去fit/予測不変、task間予測時刻の不一致拒否を確認。
- 初回のテスト側固定閾値と分位点の完全float比較による2失敗は修正。失敗logも保持。

実行: `.venv/Scripts/python.exe -m ruff check .`、`-m mypy src`、`-m pytest --cov=src/stock_ai --cov-report=json:.demo-artifacts/coverage-daily-risk-full.json --cov-report=term --basetemp .demo-artifacts/pytest-daily-risk-full-1`。OMP/OPENBLASは1thread、Git safe.directoryはprocess限定。一時DBをworkspace内へ分離。

完全logは`.demo-artifacts/tests-daily-risk-full-1.log`と`tests-daily-risk-targeted-1/2.log`。hashはtest-verification.jsonに保存。警告は主に日時処理とDuckDB非推奨API。

この保存時点では実18候補の比較が稼働中（5日fold6、train3,200,734行のLogisticまで到達）。最終receiptと既存評価の再照合は未完。実データ結果の確定後に別途README/summary/verificationを保存する。実注文なし、Goal active。
