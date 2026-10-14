# Verification at source checkpoint 2cd7167

- `ruff check .`: PASS.
- `mypy src`: PASS, 56 source modules.
- Focused: `pytest tests/test_daily_oof.py tests/test_research_memory.py tests/test_daily_nav.py -q --basetemp=.demo-artifacts/pytest-daily-oof-6 --cov=src/stock_ai --cov-report=term-missing --cov-fail-under=0`: 97 PASS; daily_oof branch-inclusive coverage94%.
- Full: `pytest -q --basetemp=.demo-artifacts/pytest-daily-oof-full-1 --cov=src/stock_ai --cov-report=term-missing`: 531 passed, 83 warnings in 467.02s (0:07:47); coverage85.86% (required85%).
- Full log: `.demo-artifacts/tests-daily-oof-full-1.log`, SHA-256 `b083f5d79ee4f9691d5362401abccac63f45c41bfe59f21f8704169836b5cc4b`.
- Python used `.venv/Scripts/python.exe`, `PYTHONPATH=src`. Tests used the authorized execution environment and workspace-local basetemp. Git safe.directory was set only in this process through GIT_CONFIG_COUNT/KEY_0/VALUE_0. No global configuration was changed.
- Real-data CLI ran before the full suite using the same fixed source. Receipt99bb4873… was checked for exact content hash, source hash, 3,717 forecasts, 30 explicit horizon blocks, 1dnull, risk20d, 962,235 calibration rows and257 dates.
- Initial per-module coverage invocations failed in NumPy initialization. Logs retained; using the source directory for coverage resolved invocation failure. Tests and scientific requirements were not weakened.
- No holdout performance evaluation, final model selection, personal portfolio mutation, model adoption or real order.
