# 開発評価指標の検証

2026-10-15。計算規則は[指標契約](../../DAILY_EVALUATION_METRICS.md)。この検証は市場で利益が出ることやモデル採用を示さない。

- 新規の手計算・境界・CLI試験41 PASS。既存の認証/日次API試験と合わせ53 PASS。
- `evaluation_metrics.py`は138 statements、44 branchesを含め100% coverage。Ruff全体とmypy55 modules PASS。
- historical reportのIC最小行数・端点Brierを保持し、新しい診断だけ別versionに固定。変更はcheckpoint `b9e9f8b`。
- 27候補のtest fixtureを使い、source・feature・OOF認証→4task診断→receipt保存を確認。実holdoutは開かない。
- production calendarと未来価格変更の3試験PASS。公式[JPX休業日一覧](https://www.jpx.co.jp/corporate/about-jpx/calendar/)を2026-10-15に参照し、2026-01-12を除いた境界をfixtureに固定。01-09のfeatureに対し入口01-13、出口は1日01-14・5日01-20・20日02-10。価格が欠けても日付を進めない。
- productionの未来価格変更試験をV1からV0/V1/V2の全列へ拡張。過去の特徴量はbit相当のexact比較で一致。

この時点の実18候補の新版診断と全体回帰は実行後に別結果を追記する。先行するNAV checkpoint `55e2878`の全体回帰は453 PASS、coverage85.48%。全baseline/NAV比較・regime別較正・実市場adapter・固定selection/holdout・日次推論・個人保有接続は未完。
