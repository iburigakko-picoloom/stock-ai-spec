> 添付パッチ側の過去の検証記録です。最新コードへ統合後の検証結果は docs/STATUS.md の D266 を参照してください。旧 D238 の番号はパッチ側の番号であり、現行の D238 と異なります。

# 設定・取引入力の待ち時間を減らす調査と修正

対象基点: `34d700f829687bc510f34b4476bfcbe58dbd74d7` / `feature/topix500-preselection`。
合成データだけを使用。本人端末や口座データの計測結果ではない。

## 原因と今回の修正

| 箇所 | 変更前の無駄・待ち | 修正後 |
| --- | --- | --- |
| 補足設定 | 設定読込とreadinessをPromise.allで待つ。readinessは個人比較と価格付き初回台帳previewを計算。保存直後にも自動実行 | 設定だけで表示・編集・保存。準備状況は本人が確認ボタンを押したときに計算 |
| 共通API | 各GETを含む全要求でSQLite整合性、外部キー、全台帳payload/hash/modelを再検査。healthは二重検査 | 同一接続のdata_versionとDB/WALの識別・更新情報が変わらない間だけ検証結果を再使用。変更・交換・失敗後は全検査。healthはmiddlewareの結果を利用 |
| 取引保存・CSV取込 | operationsだけの変更でも市場DBを含むZIPを生成・転送・暗号化 | 既存のoperations差分保存を、監査済みの判断/約定/台帳適用/CSV preview・confirmへ拡張。未確認のPOSTは全保存を維持 |
| 判断の確認 | 読取専用のreview POSTでも全状態を保存 | 計算・検証のみのreviewは保存なし。native/worker双方で限定経路を照合 |
| 実行結果・保存済み判断 | todayの予測archive取得後にdecision取得。保存済み判断では準備中に不要なhealthも要求 | execution-contextの1要求で提案と判断を返す。予測archiveは取得しない。判断確認も軽量todayを利用 |
| 画面の更新 | 60秒以上の読込を60秒pollが無効化し、結果を表示できない。重複GETが計算待ち列に積まれる | 実行中の周期pollを抑止。同一GETの実行中promiseだけを共有。POST前後で共有対象を解除。入力中の周期/focus再読込を停止 |
| 設定一覧 | 保存済み口座設定もPython初期化・計算待ち列を待つ | 既存の独立した暗号化表示コピーへportfolioを追加。保存時刻を検証した過去表示から開始し、正本確認まで編集禁止。遅着コピーによる上書きを拒否 |
| 復元 | 新たなSQLite監視接続が復元時に古いWALを保持する危険 | staged archive全件検証後、置換前に監視接続を閉じる。API終了時にも解放。旧DBのWAL等も置換時に除去 |

保存は既存の世代照合・暗号化commit完了後に成功応答する。取引IDによる再試行、CSV基点競合、古い提案拒否、本人の初回台帳確認を維持。モデル、特徴量、金融計算、holdout、正式採用条件は変更しない。実注文なし。

## 既存アプリ・公式設計との比較

2026-10-26に以下の一次資料を確認した。ソース構成の比較であり、他アプリとの実機速度比較ではない。

- [Google Now in Androidの実装説明](https://github.com/android/nowinandroid/blob/main/docs/ArchitectureLearningJourney.md): 構造化データをRoom、利用者設定をProto DataStoreに分け、同期をWorkManagerで実行。設定読込に同期や記事処理全体を従属させない構造を参考にした。本修正では既存暗号化保存を利用し、DB全面移行は行わない。
- [Android offline-first data layer](https://developer.android.com/topic/architecture/data-layer/offline-first): ローカル読取と同期の責務を分離。このアプリでも保存済み閲覧と正本更新を分離する。ただし取引の確定は正本検証を必須とする。
- [Android startup analysis](https://developer.android.com/topic/performance/appstartup/analysis-optimization): 不要な起動処理を遅延し、実測で原因を区別する。重い処理を別threadに移しただけでは初回表示やCPU競合の解消を証明できない。
- [SQLite PRAGMA data_version](https://www.sqlite.org/pragma.html#pragma_data_version): 値の比較は同じ接続で行う。別接続のcommitを検知する読み取り専用observerとファイル識別を併用し、TTLだけで検証済みとみなさない。

## 部品単位の計測

Linux/CPython 3.12.14、合成portfolio 501件、固定seedの非圧縮性市場payload 16MiB。中央値。生値は[components.json](components.json)。

| 処理 | 従来経路 | 修正経路 |
| --- | ---: | ---: |
| 台帳の整合性確認 | 全検査14.024ms | 変更なしの確認0.0109ms |
| SQLite snapshot→ZIP→base64分割の保存準備 | 全状態450.949ms | operationsのみ12.940ms |
| 保存転送対象のbase64文字数 | 22,486,196 | 78,312 |

**アプリ全体が35倍速くなるという結果ではない。** 初期復元、実行中計算の待ち、native転送・暗号化・端末storage、実市場の圧縮率、描画は含めない。実市場のサイズや圧縮率次第で効果は変わる。

再現:

```sh
uv run python -m scripts.benchmark_ui_operations --output /tmp/ui-components.json
uv run python scripts/prepare_mobile.py --download
node scripts/check_mobile_ui_runtime.mjs
```

## 検証と残る実機確認

- Python: `test_api_integrity_guard`、`test_mobile_runtime`、`test_operations_api`、`test_mobile_personal`、`test_operations_store`、`test_reconciliation_guards`の範囲を複数回に分けて確認。重複を除く121ケース。全ML suiteや実holdoutは実行していない。
- Web: `npm test` 22ファイル/141件成功、`npm run lint`、`npm run build`（TypeScript含む）成功。readonly表示、readinessの自動実行なし、遅延応答、取引再試行の既存assertを維持。
- `uv run ruff check .`、`uv run mypy src`（77source）成功。
- 固定Pyodide/WASM32をNodeで実行し、検査結果再使用・書込時無効化・破損拒否・入力context・operations復元を確認。これはWebView/native/Xiaomi試験ではない。
- Chromiumとheadless shellのダウンロードは0MiB/不正ZIPで失敗。Playwright E2Eは今回未実行。既存のE2Eは新APIへmock経路だけを更新し、assertを弱めていない。
- この環境にAndroid SDK・実機がなく、新nativeコードのコンパイル/instrumentation、APK作成、Xiaomi計測は未実施。追加native試験とCI対象を用意した。GitHub連携は書込403、git CLIは認証なしのため、今回branchのpush/PR/CI開始も未実施。
- 検証中の失敗を隠さない: WALのctimeが通常の接続openでも変わり再利用できない点を修正。Node版Pyodideのmodule形式とBufferの扱い、試験のhost/fixture時刻を修正。復元前の監視接続解放を追加し、試験側のSQLite接続も明示的にcloseした。

## 未解決の大きな原因

1. **起動時の全市場復元・依存package初期化**: 表示コピーがなければ初回の正本取得は依然待つ。小さな設定用データを独立して正本として読むには、保存世代・復旧・migrationの分離が必要。
2. **実行中の長いPython計算**: 単一の状態所有者で直列実行しているため、既に開始した重い計算を今回の軽量APIが追い越すことはできない。別writerを追加せず、次段階では計算snapshotと確定保存の境界を設計する。
3. **市場ingestごとの全状態保存**: 今回のoperations限定修正は市場更新を対象にしない。履歴増加で全ZIP/転送/暗号化が増えるため、次の大きな保存改善対象。
4. **台帳selector自体の全行検証**: 共通middlewareの重複は削減したが、正しい最新台帳の選択はD230の検証を維持する。実機traceで残存時間を測ってから、検証済みindex等を検討する。

受入時は同じ実データで「コールド起動」「初期化済み・アイドル」「市場取得中」「推論中」を分け、設定一覧表示/編集可能、実行結果入力可能、取引保存の確定応答を計測する。表示だけの短縮を保存完了の短縮と混同しない。
