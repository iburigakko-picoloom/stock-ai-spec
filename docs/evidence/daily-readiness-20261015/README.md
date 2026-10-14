# 日次版の監査証拠（2026-10-15）

## 実測した結果

- 5日9/9、20日9/9、計18候補のreport・OOFのbyte/logical hash、宣言task、key/target整列、正式特徴量・seed・source pinを認証。`candidate-audit.json`。
- 503個の成功checkpoint unitを認証。再開importは保存されていた8d82fa6のraw source byteを使用し、履歴・proofを変更していない。`checkpoint-source-audit.json`。
- 保存datasetから5日・20日の計13個の分割境界を再構成。label_available_at < 学習締切、閉区間の非重複を確認。全18候補のsplit設定・stage境界が一致し、実reportの外部OOFのfold/開始日/終了日とも一致。`label-fold-audit.json`。
- 時点検査は保存されたsingle-vintage由来のavailability宣言に対する検査。訂正前vintageの実在・過去の全アクセス履歴を証明するものではない。
- Drive v04の21単体試験と全calibrationを別実行。null/power/selection/fixture_checksが配布結果と完全一致し、4種類のfixture判定も一致。`v04-calibration.json`, `v04-summary.csv`。Python3.12.3 / NumPy2.5.2 / SciPy1.18.1。
- 本作業で実holdoutの成果を計算・評価していない。development最終selectionも作っていない。

各ファイルのSHA-256は`sha256.json`。配布ZIPは`.demo-artifacts/evaluator-v04/source.zip`、元コードは同ディレクトリの`extracted/stock_evaluation_v04`。未公開市場raw dataや学習済みmodelはこの証拠フォルダに含めない。

Drive: [評価計画v01](https://drive.google.com/file/d/1QsR-djCVznWj-AeeyVEo8xii2-lzWBFp/view)、[評価器v04](https://drive.google.com/file/d/1H2soeEQO3OmvqCINOSVAKtZWuCxE2eVp/view)。

固定horizon20・自己相関の強いfixtureではSB20の偽陽性率20.8%、coverage58.8%、SB60でも18.0% / 65.7%。再現成功はその区間推定の妥当性確認ではなく、誤較正の再現である。CIは診断用途に限定する。

## v01試験票との対応

「部分」は既存fixtureまたは今回の一部試験がある状態。「未完」は必要な統合試験を満たしていない状態。これらを26/26合格と数えない。

| ID | 対象 | 確認と残作業 |
| --- | --- | --- |
| V01 | ラベル境界交差 | 新規closed interval監査と1件違反試験、実13分割の照合済み |
| V02 | 営業日calendar | JPXの2026-01-12休業を含む専用fixtureで1/5/20日を手日付と照合。入口価格欠損でも営業日をずらさず欠損を保持。将来のカレンダー変更対応はデータ取得工程で継続 |
| V03 | 等号・引け・受信遅延 | 新規strict availability・timezone故障注入、実13分割の照合済み |
| V04 | 日付group | 新規group違反検出、既存dategroup分割試験あり |
| V05 | 未来列・未来開示 | 部分。PIT/未来availability拒否あり。全feature由来の統合故障注入が残る |
| V06 | 未来変更・訂正版 | productionのV0/V1/V2全列で未来価格変更に対する過去値の完全一致を確認。訂正fixtureも既存試験あり。strict vintageは実データ能力不足 |
| V07 | 訓練外fit | 部分。fold preprocessor train-only試験あり。全選択工程の監査まで要確認 |
| V08 | holdout混入 | 新規OOF境界拒否、既存selection/holdout purity試験あり |
| V09 | IC±1 | 独立計算の手値照合済み |
| V10 | ties/定数/NA | 新しい診断で3銘柄未満・定数・全欠損をnull、同点は銘柄昇順、有効行数と除外数を記録。行順不変と手値を確認。既存2銘柄許可reportは保持 |
| V11 | NDCG/Precision | 非負grade、全負return・逆順・K超過の独立手値を確認。Precisionはtop-K集合重複率、勝率とは別。認証OOFへの採点経路を追加 |
| V12 | key/horizon整列 | 新規重複・欠損・horizon・task整列検査、実18候補の一致を確認 |
| V13 | null反復校正 | v04を全再現。実株評価器への移植・適用判定は未完 |
| V14 | signal/共通shock/重複 | v04を全再現。SB20/SB60の誤較正を記録 |
| V15 | paired日付block | v04 fixtureを再現。実比較系列への接続は未完 |
| V16 | noiseから最良選択 | v04 selection反例を再現。実選択履歴との統合は未完 |
| V17 | 確率/分位点 | 0/1・base rate・過信のBrier/log loss/ECE、pinball/coverageを手値照合。epsilon=1e-8 float64、交差を検出して修復しない。単一alphaは交差確認不可。[実18候補の3時点較正](../daily-ensemble-20261015/README.md)を後続期間で評価済み。確率較正はECE改善とBrier/log loss悪化が併存、分位点補正はpinball悪化。較正成功とは判定せず、regime別検証は未完 |
| V18 | 固定注文の費用 | 固定株数0/10/20/30/50bpsの片道/往復手値、費用内訳の二重控除なしを日次NAV試験で確認。realistic costの実証は別途必要 |
| V19 | 重複保有の日次NAV | 21個の20日cohortを41sessionで追跡し、独立cohort手値と各日NAVが一致。forward20を加算しない。実戦略接続は残る |
| V20 | 単元/資金/部分約定 | 日次NAVで単元・呼値・口座別現金・予約現金・決済待ち・共有capacity・partial/no-fillを確認。Decision Engineの連続実行は未接続 |
| V21 | 停止/特別気配/欠損exit | 日次NAVで停止/特別気配/値幅/不明状態のno-fillと保有持越しを確認。欠損NAVはnull、仮定の評価減と分離。実データ状態の認証は未完 |
| V22 | 分割/配当/現金交付 | 分割・端数・配当権利/未収/売却後受取・確認済み現金交付の手値を確認。複雑な権利処理、実企業行動adapterは未完 |
| V23 | HOLDとの同条件比較 | 同じ初期保有・現金・日付でNAVの入替差を手計算照合。実候補/全baselineの比較は未完 |
| V24 | byte/logical/metadata改変 | 既存tamper試験＋新規原予測改変拒否、実503unit/18report認証 |
| V25 | 同ledger再開・別root/commit | 既存locked-holdoutのfixture試験あり。実holdoutは未実行 |
| V26 | 固定選択違反/自動採用禁止 | 既存selection不整合拒否＋日次採用受付ブロック。証拠付き本人採用経路は未接続 |

## 次の判定

日次NAV・実用費用・vintage能力・個人設定が欠けるため、実用採用は保留。学習結果を再計算せず、まず上の未完項目を実装・検証し、開発OOF比較から固定selectionへ進む。詳細は[日次runbook](../../DAILY_RUNBOOK.md)。
