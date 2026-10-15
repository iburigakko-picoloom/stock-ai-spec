# 検証結果

Source checkpoint: `304d3e8dde32ea6d13aa185d465238584e06f209`。

- 新規23試験PASS、通常のRidgeとの数値一致と各種認証/因果性/欠損拒否を確認。新module coverage89%。
- 全Python回帰: **613 PASS**、655 warnings、590.55秒。coverage **86.35%**、基準85%維持。
- Ruff全体PASS、mypy src59 modules PASS。
- 実18候補と単純baselineの比較: exit0。5日6fold/1,327,530行、20日5fold/1,044,317行。source/OOF keys/fold/target全一致、非有限行の除外なし。
- 全18候補の新版順位auditは前回診断receiptとexact一致、MSEはrelative tolerance1e-14で一致。旧receiptのbyte SHAも確認。
- 正本receipt `e297ff4e0fff429379956ab00e738b5bedf1ea7b4fc9a6b3d477682a28f8571c` と両OOF Parquetのbyte hashを再確認。

実行: `.venv/Scripts/python.exe -m ruff check .`、`-m mypy src`、`-m pytest --cov=src/stock_ai --cov-report=json:.demo-artifacts/coverage-daily-baselines-full.json --cov-report=term --basetemp .demo-artifacts/pytest-daily-baselines-full-1`。Git safe.directoryはprocess内設定のみ。SQL/一時ファイルを使う試験は承認された実行、workspace内basetempで行った。

完全log: `.demo-artifacts/tests-daily-baselines-full-1.log`、実比較log: `.demo-artifacts/daily-baselines-actual-1.log`。先行失敗logも保持。新規警告は主にfixtureのpandas/NumPy日時処理とDuckDB fetch_record_batchの非推奨通知で、試験失敗ではない。CLIの実比較開始/成功はartifacts/daily-baselines/runs/へ追記保存。

実用成績・採用の証明ではない。確率/分位点baseline、learned ensemble、企業行動/約定能力/費用を通した全戦略NAV、個人税、最終selection/holdout、最新推論は未完。実注文なし、Goal active。
