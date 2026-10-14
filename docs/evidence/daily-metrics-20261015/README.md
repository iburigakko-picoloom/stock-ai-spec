# 開発評価指標の検証

2026-10-15。計算規則は[指標契約](../../DAILY_EVALUATION_METRICS.md)。この検証は市場で利益が出ることやモデル採用を示さない。

- 新規の手計算・境界・CLI試験41 PASS。既存の認証/日次API試験と合わせ53 PASS。
- `evaluation_metrics.py`は138 statements、44 branchesを含め100% coverage。Ruff全体とmypy55 modules PASS。
- historical reportのIC最小行数・端点Brierを保持し、新しい診断だけ別versionに固定。変更はcheckpoint `b9e9f8b`。
- 27候補のtest fixtureを使い、source・feature・OOF認証→4task診断→receipt保存を確認。実holdoutは開かない。
- production calendarと未来価格変更の3試験PASS。公式[JPX休業日一覧](https://www.jpx.co.jp/corporate/about-jpx/calendar/)を2026-10-15に参照し、2026-01-12を除いた境界をfixtureに固定。01-09のfeatureに対し入口01-13、出口は1日01-14・5日01-20・20日02-10。価格が欠けても日付を進めない。
- productionの未来価格変更試験をV1からV0/V1/V2の全列へ拡張。過去の特徴量はbit相当のexact比較で一致。

## 実18候補への適用

全18候補PASS、全taskでkey・targetが整列し、非有限行の除外は0。学習をやり直さず、保存OOFだけを認証して採点した。5日は各task1,327,530行、20日は1,044,317行。同じ観測を複数モデルで使用しており、独立な標本数として合算しない。

完全receiptは`06aa2b94c2dcd90ef0faa850c1924c93ea7080f4a0a37f998750927e273cf65c.json`。内容IDは末尾LFを除くSHA-256、ファイル全byteのSHA-256は`summary.json`に別記。元report metrics、新指標、日別IC、reliability bin、実装hash・library版を保存する。`candidates.csv`は同じreceiptから全18候補をhorizon/family/seed順に書き出した表であり、採用順位ではない。

下落イベントの実測率は5日3.650%、20日11.258%。全候補で平均予測確率はこれより高い。10%分位点を下回った割合は5日8.50〜9.14%、20日9.07〜11.08%。これらは重複期間を含む開発OOFの記述値であり、後続期間での較正確認や有意差の証拠ではない。全候補が単一alphaのため、非交差を確認できたとは数えない。最終selection/holdout/採用へ進めていない。

全体回帰はcheckpoint `ac0fa41`で497 PASS、branch込みcoverage85.68%（基準85%）。元の5つの監査receiptはSHA-256が不変。先行するNAV checkpoint `55e2878`の全体回帰は453 PASS、coverage85.48%。全baseline/NAV比較・regime別較正・実市場adapter・固定selection/holdout・日次推論・個人保有接続は未完。
