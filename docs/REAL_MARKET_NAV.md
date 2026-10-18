# 実市場データから日次NAVへの接続

`research evaluate-market-strategy`は、保存済み5/20日予測と既存の状態付きDecision Engine・NAV会計を接続する研究専用CLI。再学習しない。個人税の設定を待たず、税引前・費用控除後で同じ初期保有/現金のHOLDと比較する。モデル採用や最終holdoutの実行経路ではない。

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='.;src'
.venv/Scripts/python.exe -m stock_ai research evaluate-market-strategy --input <固定した接続入力JSON> --output-root artifacts/market-nav
```

入力型は`stock_ai.ml.market_nav.MarketStrategyRequest`。既存の`DailyStrategyInput`、認証済み`daily-market-projection-v1`のpath/byte SHA-256/期間、`write_daily_oof_day`で保存した日別予測のpath/byte SHA-256/as_ofを固定する。feature selectionを既存loaderで認証し、dataset・feature selection・holdout境界を市場receiptと照合する。各日の予測は保存済み予測と全項目が一致しなければ拒否する。

`evaluation_tier`は`price_only_research`（配当を除く価格ベース）または`dividend_inclusive_research`（配当込み）。新しい配当なし比較では前者を明示する。省略した旧入力は従来の配当込み確認を要求し、勝手に条件を変更しない。CLI出力と成功/停止receiptの両方に区分と`dividend_treatment`を保存する。

配当なしでは`dividend_treatment=excluded_not_assumed_zero`を記録し、未知配当をゼロと判定しない。入力に配当イベントがあれば、市場fileを開く前に拒否する。イベントを黙って削除して実行しない。未調整価格の権利落ちによる価格変化はそのまま損益へ反映し、配当権利/入金を加算しない。同じ扱いをstrategyとHOLDに適用し、配当込み収益とは比較区分を分ける。研究用・税引前・採用不可は両区分で維持する。

市場receiptは未調整価格だけを許す。初期保有の評価額と各日のNAV終値を元receiptの生終値に照合し、日足終値proxyの約定値も同じ終値にする。日足の終値proxyを12:30の観測約定として表示しない。昼の約定を使う場合は、その観測と約定条件を別の根拠で固定する。

以下の独立した根拠fileをSHA-256で固定し、`evidence_sources`へ渡す。単にfile hashが一致することは、内容の正しさや供給元の認証を意味しない。根拠の取得・意味の確認は別途必要で、未確認の文書や自己宣言を「確認済み」として登録しない。

| 根拠 | 必要な内容 |
| --- | --- |
| `decision_evidence_sha256` | 保存予測の元OOF identity、当時の銘柄所属・特徴量・未調整参考価格・単元・流動性、11:30までの利用可能時刻の確認 |
| `execution_evidence_sha256` | 方向別の売買停止/特別気配/値幅状態、呼値、約定可能株数、観測約定値または明示した引けproxy、売却代金の買付余力解放時刻 |
| `cost_evidence_sha256` | commission/spread/slippage/impactを重複させない固定policy。実測費用と仮定のbps感度分析を区別 |
| `action_coverage` | 銘柄別の期間全体の分割・現金交付・その他権利と、配当込み区分の場合は配当の確認。元根拠のhashと宣言scope内の全event IDs。確認済みの「該当イベントなし」も期間を明示 |

配当なしの確認scopeは`splits_cash_conversions_and_other_rights_reviewed_excluding_dividends`。配当を含めた従来の`splits_dividends_cash_conversions_and_other_rights_reviewed`も利用できるが、いずれも宣言scopeで発見したイベントと会計入力を照合する。配当込み評価へ狭いscopeを渡すと`DIVIDEND_COVERAGE`で停止する。配当なしでも分割/併合・現金交付・その他権利の全期間確認、約定・受渡し・費用・PIT根拠と保存予測の一致は必要なままである。

調整係数が1であることやイベント配列が空であることから、企業行動なしとは推定しない。非単位の係数には当該日の独立した企業行動根拠を要求する。対応不能なライツ等がある期間は評価対象へ進めず、別途会計を実装して検証する。将来候補になる銘柄を過去の価格不足だけで排除しない。実際の保有の欠損はledgerで持ち越し、評価未完を記録する。

不足があれば`status=BLOCKED`、理由、入力と実測時間をcontent-addressed receiptへ保存し、CLIはexit 2を返す。前提不足のときは成績を生成しない。判断や保有評価が途中で不完全になった場合もBLOCKEDにする。全条件が揃う場合は既存`evaluate_daily_strategy`を呼び、日別状態・費用・strategy/HOLD・差分を保存する。関連source hash、Pydantic版、Decimal精度28も記録する。テストの数値は合成入力で、実市場成績ではない。

最初の1本と18候補・単純戦略・ensembleで、期間・銘柄の利用条件・初期資産・売買規則・費用・受渡しを統一する。開発期間でモデル・売買規則・採用基準を固定し、その後に既存の単回holdout手順へ進む。本CLIはholdout境界以後の宣言された市場/予測fileを開く前に拒否し、採用可能とは表示しない。個人税は独立工程として追加する。

配当通知の入口は[配当データ接続](DIVIDEND_DATA.md)。保存済みV2通知の訂正・削除・予想/決定・利用可能時刻を照合し、条件が揃う決定配当だけを既存NavActionへ変換する。この処理単独では企業行動の全期間網羅を成立させない。

公式仕様を2026-10-17に確認：日足の調整価格は後続イベントで再計算され、ULは高値の上限到達を示す。特別気配、当時の取得可能時刻、訂正前データは日足だけでは補えない。[J-Quants日足仕様](https://jpx-jquants.com/ja/spec/eq-bars-daily)。配当の通知系列・訂正削除・予想/決定を区別し、権利落日・金額・支払開始予定日を確認する。通知時刻をJ-Quantsでの取得可能時刻へ読み替えない。[配当仕様](https://jpx-jquants.com/ja/spec/fin-dividend)。T+2の受渡制度と口座の買付余力解放は別に扱う。[JPX受渡制度](https://www.jpx.co.jp/equities/clearing-settlement/tplus2-settlement-cycle/index.html)。
