# 検証記録

2026-10-15。checkpoint後の最終全体試験まで実行済み。

- ruff check .: PASS。mypy src: PASS、53 modules。
- 日次契約・API・同期の故障注入と既存UTF-8の修正: 42 PASS。
- private/: 日次schemaと口座・保有schema/DB migrationの12 tests PASS、TypeScript PASS、eslint PASS、Sites build PASS。
- web/: lint PASS、typecheck PASS、18 tests PASS、build PASS。
- 390px幅: 横はみ出しなし、主要区画を確認。
- 本人専用deployment成功: source 87bb4a24ee55a11fc16458a91a556011c654d0ac。
- production private boundary: 匿名401、POST→GET完全一致、同一payloadの再送も同じID/received_at。
- 実際のモデル予測をクラウドへ送信していない。準備状況のみ。

初回全体テスト: 376 PASS / 2 FAIL。1件はWindows既定encodingでテストJSONの日本語pathが変化したため、UTF-8を明示して修正・再試験PASS。もう1件はrunnerが未commitのsourceを正しく拒否したため、checkpoint後に再試験する。初回coverageにはstock_ai名でロードされた旧fixtureも入り82.68%。分母をsrc/stock_aiへ明示し直し、最終値は下記へ追記する。基準85%は変更していない。

最終全体試験: `pytest --cov --tb=short -q`、408 PASS / 0 FAIL、998.20秒、coverage85.26%。ログはローカル`.demo-artifacts/tests-daily-final-1.log`。検証対象Python sourceは722b9a2でcheckpoint済み、receiptのGit byte保持修正は2e268dd。以後はprivate UI・文書だけを変更。

口座入力のローカル実ブラウザ検証: 保有なし・金額未入力の確認→保存→ページ再読込、NISAの対象外源泉徴収、1株・取得単価1234.5678の保存、別タブの古いrevisionからの保存409拒否と再読込を確認。幅390px（scrollbar込み、content/client各375px）で横overflowなし。テスト用口座はローカルDBにのみ保存。

入力画面の本番deployment成功: source847864637a69cfb9e970550a45cca71dc8495bc5。`portfolio-deployment.json`を参照。通常のChatGPTサインイン後に本番`/portfolio`を表示。ユーザーが申告した「現在は保有なし」を保存し、口座・資金・リスクは未入力のまま維持した（2026-10-15 02:36:51 JST）。ローカルpreview停止後にページを再読込し、同じ保存時刻・保有なし・金額空欄を確認。本番にテスト口座・架空保有は登録していない。`/api/portfolio`と`/api/sync`は匿名GETに401。audienceはownerのみ、group0を再確認。

PC側preview停止後も、private cloudから同じ準備状況IDを読戻せることを確認。`cloud-after-local-stop.json`を参照。

Gitの信頼設定・PATH・tarのWindows設定は検証プロセス内だけ。科学pin、元のcheckpoint、失敗履歴は変更していない。実注文なし。
