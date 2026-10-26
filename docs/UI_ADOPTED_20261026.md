# 採用版UIと既存機能の対応（2026-10-26）

参照：添付 `1-stock-ui-mock-offline.html` の `selectedVariants`（28指定＋設定トップ＝29画面）。公開URLは取得不可。HTMLはソースとして確認し、架空値・デモ状態遷移・比較/案切替を移植しない。設定トップは現行を保持する。

| 採用画面 | 既存の接続先・保存処理 | 採用する構成 |
| --- | --- | --- |
| ホーム B | HomePage / home API | 白い資産合計、現金/株式、保有一覧、資産管理 |
| 今日 A | TodayPage / today API | 市場・提案・本人判断への導線 |
| ランキング A | Rankings / mobile/ranking/5d・20d | 3モデル、検索、表、共通銘柄詳細 |
| 検証 A | ValidationPage / validation API | 主指標・推移・詳細分析。未観測は未観測 |
| 設定 | MobileDevicePanel | 現行トップを維持 |
| 銘柄詳細 A | StockDetailPage / stocks API | 数値予測・保有・提案・調査を区別 |
| 資産管理 A | HoldingsPage / CurrentAccountPanel | 初回登録・残高修正・履歴への入口 |
| 資産登録 B | InitialHoldings / MobilePersonalPanel | 一覧フォーム、初回台帳確認 |
| 入出金 B | CurrentAccountPanel cash | 現在残高の確認・差分保存。入出金額からの自動推定はしない |
| 保有修正 B | CurrentAccountPanel holdings | 現在保有・取得単価の確認と修正 |
| 修正履歴 A | current ledger / operations store | 保存済み台帳履歴。読み取り専用 /api/v1/portfolio/history を追加 |
| 取引記録 B | ExecutionPage / executions・apply-executions | 実約定入力・差分反映・同画面結果 |
| 取引履歴 B | decisions/{id}/executions | 保存済み約定。読み取り専用 /api/v1/executions を追加 |
| 判断確認 A | DecisionReviewPage / review・decisions | 株数変更・再計算・同画面保存結果 |
| ChatGPT相談 A | ManualChatGPTPage | 相談文・回答JSON・独立保存 |
| 相談履歴 B | ManualChatGPTPage / manual consultation | 保存済み相談の選択・詳細 |
| 運用条件 B | capital/risk / MobilePersonalPanel | 既存入力だけの簡潔なフォーム |
| 口座税手数料 B | MobilePersonalPanel | 口座別税・NISA・費用の既存設定 |
| データ更新 B | MobileMarketPanel / DailyControls | 実進捗・停止/再開・通知 |
| ChatGPT設定 B | ChatGPTPanel | 接続・許可・手動相談 |
| バックアップ B | MobileBackupPanel | 暗号化書出し・検証後復元 |
| アプリ情報 B | about / native update | 実際の更新状態・ライセンス |
| モデル管理 C | MobileModelPanel | モデル/計算の操作と確認、狭幅では1列 |
| データ修復 B | MobileMarketPanel | 履歴・指定日・訂正取得・特徴量 |
| 計算方式 B | MobilePersonalPanel / model settings | 既存方針の明示選択、無断変更なし |
| CSV取込 B | DataOperationsPage | preview・競合照合・確定保存 |
| 処理状況 B | DataOperationsPage / DailyPanel | 実ジョブ状態・停止理由 |
| 詳細分析 B | ValidationPage details | 実指標・モデル診断・週/月次 |
| 調査履歴 B | CompanyResearchPanel | 保存済み調査・中断/再開の実状態 |

## 接続上の確認点

- 20日順位は実予測のrank_score_20d（欠損を値予測で代用しない）、5日/20日値はexpectedReturn（比率→%）を使用。ChatGPT順は別タブで明示する。
- 原予測、ChatGPT回答、本人判断、約定は既存の別レコードを維持する。
- 判断保存は台帳を変更しない。約定記録と未反映約定の反映を区別し、失敗時に記録を重複送信しない。
- 残高のavailable_cashは既存契約を維持し、reserved_cashを資産へ加算しない。
- 設定トップ以外の装飾と説明用の折りたたみを簡素化。必要な情報や操作自体は削除しない。
- 画面復帰は保持されたstateとルート別スクロールを使用。画面テストのfixtureは製品APKに入れない。

## 実施結果

- 資産管理・現金変更・残高履歴・取引履歴・相談履歴・調査履歴・CSV・処理状況・詳細分析の経路を既存の保存処理へ接続。
- 判断は同画面に保存結果を表示。約定は記録後、現在時点までの未反映分を反映。記録成功/反映失敗の再試行では約定POSTを再送しない。
- ランキング・保有・設定画面の状態を保持。ルート別スクロールと銘柄詳細の口座選択・戻り先を保持。
- Vitest 26ファイル191件、Pythonのランキング/API/照合/保有80件、ESLint・TypeScript・変更PythonのRuff成功。
- Playwright: 29対応画面を320/390px・100/150%文字で検査。Android 35 SystemWebViewでも320dp・100/150%で全経路を実表示、各画面上/中/下を端末キャプチャ。検索・モデル選択・スクロール復帰も成功。
- Android証拠: .demo-artifacts/ui-adopted-native-capture/（テスト専用データ・専用エミュレーター、本人の保存データは使用しない）。

## 既存機能に合わせた対応と確認範囲

- 初回資産登録と保有修正は同じ /holdings で、台帳の有無に応じて実フォームを切り替える。初回確定は既存の口座設定から行う。
- モックの入出金は現金残高の変更として既存の確認・保存を使用。履歴は初回登録・修正・約定反映を含む直近100台帳であり、分類を推測しない。
- 処理状況は既存APIにある進捗・実行情報のみ。モデル未採用、未算出、履歴なしの状態をダミーで埋めない。
- モックの見本と実データで必要なフォーム項目数は異なる。既存の口座・税・計算の確認項目を削除して見た目だけを一致させない。
- 本人のAndroid端末での更新・既存データ移行確認、実プロバイダー通信は未実施。エミュレーターの境界fixtureはAPKへ含めない。
- 確認用APKは .demo-artifacts/ui-adopted-20261026/ に既存署名で作成。署名/同梱物/ソース照合の結果は同ディレクトリのverified.jsonを参照。
