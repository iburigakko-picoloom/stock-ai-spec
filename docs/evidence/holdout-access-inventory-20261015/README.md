# 最終評価へのアクセスに関する保存記録の調査

2026-10-15。最終評価の正解や新たな成績を読み出さず、保存済みのmetadataとGitに残るコードを調査した。これはローカル記録の確認であり、過去のすべてのアクセスが記録されたという証明ではない。`history_completeness=NOT_PROVEN`を維持する。

## 調査範囲と結果

- `artifacts/reports`、`artifacts/selections`、`artifacts/campaigns`、`artifacts/experiments`のJSON/JSONL全73ファイル、161レコードを調査し、各ファイルのbyte SHAと宣言の位置をinventory.jsonへ保存した。
- アクセス宣言148件は、boolean falseが147件、文字列`"false"`が1件。trueの宣言は見つからなかった。文字列はbooleanへ勝手に変換せず、型をそのまま記録した。
- `artifacts/`全体のファイル名を調べ、holdoutまたはledgerを名前に持つJSONはなかった。現CLIの既定保存先は`artifacts/holdout/goal3`。テスト用の`.demo-artifacts/pytest-*`はこの本番成果物調査に含めていない。
- 旧baseline report `47afb247…`のcontent identityを再計算して一致を確認した。宣言source `86c958d`は`86c958d0fd60c91c2941420a58a0dcfe7bcea764`へ解決できる。
- その固定版の`reserve_locked_final_holdout`は日付が境界より前の行だけを返す。baseline処理はさらにlabel終了日が境界より前の行へ絞り、そのdevelopmentだけを評価器へ渡す。境界は2026-02-24で、現候補の2026-03-04より前。固定関数の本文・位置・SHAも保存した。

このコード経路に従った旧baseline評価は、現在の最終評価期間を採点していない。境界が異なる旧baseline成績をそのまま現候補と比較できない点は変わらない。

## 証明できていないこと

falseという宣言やledgerの不在から、未記録の手動読込・外部コピー・別保存先での処理までなかったとは断定できない。旧baseline reportはsummaryと宣言commitを結び付けるが、実際にそのコードだけが実行されたことを示す署名済み実行証跡ではなく、評価行ごとのkey receiptも持たない。

したがって、この調査だけで「完全に未開封」「最終評価や採用の条件を通過」とはしない。最終選択の固定、正式evaluatorの単回ledger、過去の追加アクセス証跡の確認は別途必要。SINGLE_VINTAGE_AS_REVISEDの制約も未解決である。実注文なし。

再現用スクリプトは`.demo-artifacts/inventory_holdout_metadata.py`。調査中にファイルが変わっていないことも再hashして確認した。保存記録・元データ・学習成果は変更していない。
