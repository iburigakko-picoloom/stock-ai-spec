# 検証記録

2026-10-15。最終全体テストはcheckpoint後に追記する。

- ruff check .: PASS。mypy src: PASS、53 modules。
- 日次契約・API・同期の故障注入と既存UTF-8の修正: 42 PASS。
- private/: Node schema tests 4 PASS、TypeScript PASS、eslint PASS、Sites build PASS。
- web/: lint PASS、typecheck PASS、18 tests PASS、build PASS。
- 390px幅: 横はみ出しなし、主要区画を確認。
- 本人専用deployment成功: source 87bb4a24ee55a11fc16458a91a556011c654d0ac。
- production private boundary: 匿名401、POST→GET完全一致、同一payloadの再送も同じID/received_at。
- 実際のモデル予測をクラウドへ送信していない。準備状況のみ。

初回全体テスト: 376 PASS / 2 FAIL。1件はWindows既定encodingでテストJSONの日本語pathが変化したため、UTF-8を明示して修正・再試験PASS。もう1件はrunnerが未commitのsourceを正しく拒否したため、checkpoint後に再試験する。初回coverageにはstock_ai名でロードされた旧fixtureも入り82.68%。分母をsrc/stock_aiへ明示し直し、最終値は下記へ追記する。基準85%は変更していない。

Gitの信頼設定・PATH・tarのWindows設定は検証プロセス内だけ。科学pin、元のcheckpoint、失敗履歴は変更していない。実注文なし。
