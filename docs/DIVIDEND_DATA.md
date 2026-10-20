# 配当通知の時点照合とNAVへの変換

`research project-dividends`は、保存したJ-Quants V2 `/fins/dividend`応答を照合する研究用adapter。既存のNAV会計へ渡せる配当イベントを作る。API契約・当時の利用可能性・企業行動の網羅を自動承認する機能ではない。実注文・再学習・holdout評価を行わない。

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='.;src'
.venv/Scripts/python.exe -m stock_ai research project-dividends --input <固定した入力JSON> --output-root artifacts/dividend-projections
```

入力は`stock_ai.ml.dividends.DividendRequest`。凍結feature selection、元応答のpath/byte SHA-256、通知日の収録範囲、実受領日時、評価の情報時点を明示する。先にholdout境界を認証し、期間が触れるsource fileは開く前に拒否する。未取得ページのcursorが残る応答、収録期間外の通知、重複IDの異なる内容、未知の新schema項目を拒否する。原sourceは書き換えない。

各通知の`RefNo`へ、当時その通知が利用可能だった時刻と、その根拠fileのhashを付ける。`PubDate`/`PubTime`だけからJ-Quantsでの取得可能時刻を作らない。通知日・実受領日・利用可能時刻を区別する。現在の受信記録を過去の11:30へ戻さない。

訂正・削除は`CARefNo`で最初の通知へ結ぶ。RefNoの大小やファイル行順を公表順序とみなさず、確認できた公表・利用可能時刻で各時点の版を選ぶ。同じ公表時刻に優先順位不明の複数版がある系列、元の通知が欠ける系列は停止する。予想と決定は別系列として扱い、配当イベントには決定だけを使う。記念・特別の内訳をDivRateへ重ねて加算しない。金額の空欄・`-`を0円へ変換しない。

権利落日の開始時点で既に確認できる決定額だけを、未調整株数へ対応する配当権利として既存NAVへ渡す。支払開始予定日`PayDate`から実際の入金日時を推定せず、`DividendPayment`で対象通知・実入金時刻・根拠hashを別に固定する。後日確定した金額、権利発生後の訂正・削除・権利落日変更は過去へ上書きせず、ledgerの追加調整が必要な理由付きで停止する。将来の権利落日はpendingとして返し、将来の通知を使って現在の権利を選び直さない。

DivRateは基準日時点の株数を前提とする。`DividendShareBasis`で権利発生時の未調整株数と同じ単位であること、その根拠hashを確認する。分割前後の単位が一致しない通知は追加の企業行動会計が必要で、未確認の換算係数を補わない。同時点の分割/配当は既存NAVの明示的な順序条件も満たす必要がある。

資本払戻し・みなし配当等の分解を伴う通知、非標準code、欠けた権利条件・実支払根拠は、対応を確認するまで停止する。BLOCKED時は部分的に作れたイベントを本番入力として返さず、診断件数と理由を保存する。CLIはexit 2。COMPLETEであっても、配当以外の分割・現金交付・その他権利や「イベントなし」の期間網羅を確認したことにはならず、`corporate_action_coverage_verified=false`を維持する。

照合結果の`actions`は既存`NavAction`のJSON。元receiptを固定した[実市場NAV接続](REAL_MARKET_NAV.md)の`strategy.accounting.actions`へ渡し、別途確認した企業行動の全期間網羅根拠へ同じevent IDsを結ぶ。調整価格へ配当を重ねず、未収権利から実入金への振替を既存会計に任せる。個人税は別工程。

取得できない場合はHTTP状態と認可理由を保存し、有効な契約・対象endpoint/期間の利用資格を確認する。取得済みの正規応答を持ち込む場合も、同じsource hash・ページ完了・通知系列・時点性・入金根拠の条件を満たす必要がある。

公式仕様を2026-10-17に確認。[配当金情報](https://jpx-jquants.com/ja/spec/fin-dividend)、[訂正系列と予想/決定の関係](https://jpx-jquants.com/ja/spec/fin-dividend/reference-number)。通知データだけでは当時のJ-Quants利用可能時刻と実入金の証明を代替できない。
