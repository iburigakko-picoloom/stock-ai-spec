# 日次判断と資産会計の連続評価

2026-10-15。Drive v01 V19〜V23の戦略接続。`research evaluate-daily-strategy`は、各日の11:30情報からDecision Engineを実行し、実際の仮想約定・未約定・企業行動・決済を翌日の判断へ引き継ぐ。税前の研究評価であり、本人の口座設定や最新の推奨ではない。

## 入力

`DailyStrategyInput`は、初期現金/保有・全session・企業行動・費用policyを含む`NavInput`、全営業日の`DailyDecisionObservation`、固定された0/0/1のDecision Engine policyを持つ。固定注文との混在は拒否する。

各observationは同じ固定5日/20日forecastペアの`DailyOofDay`、その11:30時点で利用可能な生の参考価格、参考価格の観測時刻、銘柄/業種/単元/流動性の利用可能時刻、明示的な新候補リストを持つ。現在の保有は実際のledgerから毎日追加する。予測・市場時点の不一致、11:30以外、後から判明した情報、重複、calendar不足、horizon policyや単元の不一致は拒否する。

市場・銘柄・候補のsource認証は別工程であり、入力にsource名があるだけで実証済みにはしない。`data_mode=fixture`の数値はテスト専用。価格補正係数だけを分割/配当の確証にしない。

## 実行順序

1. 前回終値評価後から判断時刻までに効力が生じた企業行動と支払済み未収金を反映する。
2. 判断callbackへ、その時点の現金・予約額・保有株数/取得単価・未収金だけを渡す。当日以降の約定値・終値は渡さない。
3. 新候補と全保有を同時評価する。必要な予測・価格・銘柄・流動性が欠ける日は理由付きで比較を停止する。前回終値より古い参考価格、当日の分割等より前の単位の価格も停止する。
4. 提案の増減数量を当日だけの仮想注文へ変換する。時刻・口座・IDを検証した後、既存NAV ledgerが売り→買いの順で処理する。株数・資金は実際に仮想約定した量だけ変更する。
5. 引けまでの企業行動/支払と終値評価を処理し、その状態を翌日に渡す。未約定数量を自動再発注しない。翌日も保有を再評価し、新たに必要な増減だけを提案する。

判断後の分割/現金交付で単位が変わった注文は既存NAV契約に従って失効する。売却後も既に得た配当権利は残り、実支払時点で現金になる。

未収金はNAVへ含めるが、支払まではDecision Engineの利用可能な資産・買付余力へ含めない。予約現金も買付には使わない。現行engineは同じ注文群の売却代金を買付計画に使えるが、ledger側の実際の支払条件で買付可能株数を再計算する。計画と実約定の差は隠さず、翌日の状態に反映する。

## 研究用提案と税

日次提案へ`DailyDecisionAudit`を付ける。予測・市場・現在portfolio・銘柄/流動性のhashと元report IDsを保持し、`is_research_only=true`を必須にする。既存の朝判断auditとは別の型で、混在を拒否する。前段adapterの提案は汎用engineの既定値によりこのflagがfalseだったため、日次の研究用lineageを追加して是正した。過去の研究結果の記録は上書きしない。

純粋なalphaの比較として、税率0・源泉徴収なしの明示的な研究用口座metadataを作る。口座bucket別の現金・保有は分離するが、これは本人の口座区分を推測する処理ではない。NISA枠、個人の税率・繰越・源泉徴収などを評価した結果として扱わない。個人税シナリオは別途必要。

## 結果と再現

全日の判断前状態、評価した全銘柄、停止理由、研究用提案、仮想注文、strategyと同一初期状態のHOLDの日次NAVを保存する。現金だけから開始したHOLDは現金維持であり、初期保有があるHOLDはその保有を維持する。

生成注文を含む`execution_input`も保存し、`evaluate_daily_nav`で再実行すると状態・NAV・費用が完全一致する。正本JSONは入力/結果、関連7 sourceファイルのSHA-256、Pydantic版、Decimal精度28を含むcontent-addressed receipt。

データ不足または離散探索の上限超過は、注文なし・保有持越しと理由を記録する。1日でも停止すると`decisions_complete=false`になる。これを完全な戦略比較やモデル不採用の根拠へ読み替えない。探索上限を無断で下げたり、別の最適化法へ置き換えたりしない。すべての結果は`research_only=true / adoption_eligible=false`。

```powershell
.venv/Scripts/python.exe -m stock_ai research evaluate-daily-strategy --input <明示的な研究入力JSON> --output-root artifacts/daily-strategies
```

実市場adapter、全baseline/候補の同条件比較、実用費用/企業行動能力、個人税設定、最終selection/holdout、最新予測・本人採用は未完。実注文台帳・クラウドの保有入力を書き換えず、実注文は行わない。
