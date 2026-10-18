# 日次資産額の研究評価器 v1

2026-10-15。Drive v01のV18〜V23向け。固定された仮想注文を受け取り、各営業日の現金・保有・未収金・費用を追跡する。研究専用で、実約定台帳へ書き込まず、実注文を送信しない。現段階は税前・費用控除後の会計検証であり、実データ比較やモデル採用の完了ではない。

## 入力と出力

`src/stock_ai/ml/nav.py`の`NavInput`へ、初期現金/予約額・口座別保有、固定カレンダー、各sessionの時刻・生の約定参照価格/終値、注文、企業行動、費用policyを明示する。`price_basis=unadjusted`だけを受け付ける。調整後価格へ分割・配当を重ねて計上しない。forward returnや20日ラベルを会計入力として受け付けない。

`evaluate_daily_nav`は各日の現金・保有・未収金、約定/未約定理由、費用内訳、日次NAV/returnを返す。`compare_with_hold`は同じ初期状態・カレンダー・企業行動・費用契約のHOLDとの差を計算する。HOLDは注文なしの継続保有であり、全現金へ置き換えない。

```powershell
$env:PYTHONPATH='src'
.venv/Scripts/python.exe -m stock_ai research evaluate-nav --input <明示的な入力JSON> --output-root artifacts/nav-evaluations
```

正本JSONには入力、strategy/HOLDの全日次状態、差、入力hash、評価器/費用/基礎型sourceのhash、数値精度・Pydantic版を保存する。内容hashで命名し、既存fileを上書きしない。`load_nav_evaluation`はbyte hashと各入力identityを検証する。source IDは供給者の宣言であり、正規の市場データ認証を代替しない。

## 固定した研究用の資金解放（D169）

`research project-research-funding`は既存`DailyMarketRequest`で指定したcalendar raw/normalizedを認証し、`research-funding-schedule-v1`を私有保存する。最終期間に到達する要求はcatalogを開く前に拒否する。全暦日が連続して存在し、Date/HolDiv・現物営業日flag・元record hashと取得metadataが一致することを確認する。休日区分3（デリバティブの祝日取引）を現物営業日には数えず、欠落日を平日/休日で埋めない。取得時点の版を選び、後日のカレンダーを以前の取得へ遡及させない。

共通研究用policyは`t2-equity-calendar-proxy-t3-0900-jst-v1`。現物営業日を受渡しカレンダーのproxyとしてT+2の日付を算定し、資金はさらに次の現物営業日（T+3）の09:00 JSTからだけ利用可能とする。T+2制度の事実と、T+3/09:00という保守的な研究仮定を区別し、証券会社の実際の買付余力を確認したとは表示しない。2019-07-16より前は対応外。必要な将来カレンダーが末尾にない行は理由付き未確定とし、NAVに含まれる未受領の売却代金を現金へ移さない。

`build_funding_schedule`のcalendar IDと行別`sale_cash_available_at`をNavInput/NavSessionへ明示する。`require_research_funding`は再構築した規則/全日付/時刻と既存sessionを再生前に照合し、不一致・未確定・改変を拒否する。既存の時刻を黙って修正しない。口座間の資金転用・実台帳の更新は行わず、既存NAVの未収金・現金会計を再利用する。

D170で[実市場NAV入口](REAL_MARKET_NAV.md)の`research_funding_receipt`へ接続。元receiptのbyte hash・モデル/特徴量版・期間・市場と同じ取得版を確認してから既存sessionを照合し、適用したpolicyと`broker_verified=false`を評価結果へ残す。旧明示入力は新ルール未適用として区別する。この接続の通し試験も合成データであり、実市場損益や当時の口座余力の検証とは区別する。

```powershell
.venv/Scripts/python.exe -m stock_ai research project-research-funding --input <固定calendarの入力JSON> --output-root <私有保存先>
```

区間末尾を含む出力は`status=PARTIAL`になり得る。生成成功を、全評価日の資金が確定したことや実市場NAVの完了に読み替えない。カレンダーの内容hashは入力版の識別であり、JSCCの決済完了時刻・口座固有の買付余力・当時の入手可能性を認証しない。実市場の企業行動・方向別売買状態/容量・PITと採用gateは別に残る。

出典（2026-10-18確認）：[T+2開始日](https://www.jpx.co.jp/news/0010/20190714.html)、[JPX決済期間の説明](https://www.jpx.co.jp/equities/clearing-settlement/tplus2-settlement-cycle/)、[J-Quantsカレンダー](https://jpx-jquants.com/ja/spec/mkt-cal)、[休日区分](https://jpx-jquants.com/ja/spec/mkt-cal/holiday-division)。T+3/09:00はこれらが定めた口座規則ではなく、本研究で追加した遅延である。

## 固定した会計規則

- 注文判断は前回valuation以後、当回executionより厳密に前。同じ終値を観察して同時刻に約定する入力は拒否する。日足終値proxyはexecutionとcloseが同時刻・同価格であることを要求し、実際の昼の約定と表示しない。
- 売り→買い、同方向ではorder ID順。未約定分は当sessionで失効し、翌日へ再提案なしで再発注しない。保有は継続する。
- 正の100株単位が既定。呼値、方向別の停止/特別気配/値幅制限/未確認状態、共有capacity、fill fractionを検査する。capacity不明は約定させない。部分約定も単元へ切り下げる。
- 買付は口座別の現金から予約額を除いた範囲。費用と最低手数料を含めた支払可能単元数を再計算する。借入・空売り・口座間の現金転用はない。
- 売却代金は実際に指定された買付余力解放時刻まで未収金。NAVには含めるが、その前の買付には使わない。T+Nを推測しない。
- 費用はcommission/spread/slippage/impactを約定分に一度だけ控除する。固定0/10/20/30/50bpsは片道all-inの仮定をslippage欄に一度だけ置く。実際の証券手数料無料やrealistic costの証明ではない。費用増で約定数が変わる場合、固定約定数の単調性検査と混同しない。
- 分割は株数・取得単価・参考旧価格を変換する。端数は金額と支払時刻の明示された現金権利だけを計上し、不明なら停止する。判断後の分割/現金交付で単位が変わる注文は失効扱いにする。
- 配当は権利発生時点の保有へ未収配当を計上し、支払日に現金へ振り替える。権利後に売却しても未収権利は残る。権利後の購入には付与しない。
- 確認済みの全株現金交付は実時刻に株式を未収金へ置換する。上場廃止や価格欠損だけで清算しない。根拠のavailable_atがeffective_atより後の企業行動は拒否する。
- 現在の終値がない保有は削除せず、当日のNAVをnullにする。旧価格から0/50/100%評価減を仮定した値を別欄へ出すが、観測NAV・売却・現金回収とは扱わない。欠損をまたぐ日次returnと全期間最大drawdownは未確定。期末NAVが確定していれば始終点returnは計算できるが、経路の完全性とは区別する。
- Decimal精度28を局所固定し、呼出元の数値設定に依存させない。証券会社の円単位丸め、税務申告・源泉徴収の計算ではない。

## 検証と残作業

`tests/test_daily_nav.py`は独立手値で、片道/往復費用、41session中の21個の20日保有cohort、同じ初期保有からのHOLD/入替差、分割、端数、権利落・配当・売却後受取、現金交付、予約現金、決済待ち、no-fill/partial-fill、欠損、時刻・入力違反を検査する。すべて合成のテスト専用入力であり、本人の資金や市場成績ではない。

Decision Engineを日ごとに呼ぶ[状態付き戦略adapter](DAILY_STATEFUL_STRATEGY.md)を追加した。判断時点の状態だけを渡し、実際の仮想約定/未約定/支払から次の判断を作る。固定注文の既存APIも同じ会計経路を使う。

[実市場接続](REAL_MARKET_NAV.md)を追加した。保存済み予測と生終値を固定し、独立した企業行動・時点・執行/受渡し・費用の根拠が揃う場合だけ既存会計へ渡す。不足は理由と実測時間付きのBLOCKED receiptへ保存する。全種類の権利処理、個人口座の税シナリオ、全候補・各baselineの実市場比較は未完。現在のprovider価格調整係数だけを分割/配当の確証としない。これらが不足する実データ経路をfixtureで補完しない。holdoutを読む経路はこの評価器にはない。

個人税の接続条件と実装順は[PERSONAL_TAX_NAV.md](PERSONAL_TAX_NAV.md)。税帰属日と買付余力の解放日、同日取得費、源泉徴収と申告還付、年次損失/NISA簿価を区別する。現行の簡易実台帳や、税前注文の後処理を完全な税引後NAVとは扱わない。
