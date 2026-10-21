# 端末用モデル一式の受け渡し

D216（2026-10-21）：`stockai-mobile-research-ensemble-v1`を別schemaとして追加。複数portable componentと前処理hash、horizon/役割別の単位・保存重み・recipe・校正・順位母集団を保持する。全基本出力の後に平均percentile順位を計算し、batch/入力順による変更と欠落した順位母集団を拒否する。全市場rankをTOPIX内rankへ置換しない。既存64MiB/policy evidence pin/実機一致/公開承認を維持する。

研究ensembleの原予測はschema4/snapshotv2でreturnとrankを分離し、未提供return/riskはnull。ranking20を優先し、なければ20日returnを使い、5/20を加算しない。全保有を残して手動相談へ渡し、回答取込は提案保存のみ。optional raw riskの値があっても採用/校正がそろうとは扱わず、自動株数提案を許可しない。保存読戻しでcomponent/recipe/全対象/合成値を再検査する。現時点では合成統合試験済みで、実選定ensemble bundleやXiaomi完了を意味しない。

各horizonにreturnまたはrankingが必要で、riskだけのbundleは保存前に拒否する。順位母集団が`decision_symbols`なら、特徴量が一つでも欠けた際は`ENSEMBLE_RANK_POPULATION_INCOMPLETE`として対象と棄権理由を保存する。欠けた銘柄を取り除いた母集団を新たに宣言して順位を成功扱いにしない。全市場順位が必要なrecipeは、候補限定cacheでは`ENSEMBLE_REQUIRES_ALL_MARKET_FEATURES`として停止する。

D213（2026-10-20）：現在の私有研究bundleは5日CatBoost/20日LightGBM・seed17の2回帰であり、重み・前処理・元fit plan・bundleの対応を再照合した。正式採用bundleは0件。以下の通常4head契約と研究2回帰契約を区別する。ランキングhead、rank-space合成、保存forward-crossfit weighted_return、riskなしの採用構成をそのまま表現できるとは扱わない。候補が確定した後、その構成に必要な最小対応と不足fitだけを行う。既存2weightを使いやすさだけで採用せず、未提供のrisk/校正はnullを維持する。採用審査・配備の未接続をbundle取込で回避しない。

モデルの学習と大規模な検証はPCで行い、端末にはデータだけのJSONを一度取り込む。重み・市場履歴・本人の口座情報を公開APKやGitへ含めない。正式採用bundleは0件であり、研究用2回帰bundleや形式・テストの完成を最終モデル採用とは数えない。

## 内容と時点

`stockai-mobile-bundle-v1` は次をまとめる。

- 5日リターン回帰、20日リターン回帰、20日下振れ分位点、20日大幅下落確率の4つのportable head。各headのtask・horizon・model ID・元のJSON文字列・SHA256。
- 凍結済みのfeature selection IDとmanifest hash、モデル選択ID、学習情報の締切・学習日時・作成日時。
- 受領済みの過去20日リターンの残差から得たRMSE、校正の行数・日数（最低20日）、最新ラベルの利用可能時刻、校正日時と根拠のhash。RMSEは信頼区間や利益保証ではない。
- `fractional_return`、日次終値を使う研究用の入口・出口定義、下振れの分位点と大幅下落の閾値。1日予測や前場予測を補って作らない。
- 同じモデル選択に対する本人レビュー。`continue_paper` と `adopt` の記録を区別し、取込・pin・レビュー文字列だけで実運用モードへ昇格しない。既存の評価/holdout/設定の認証ゲートは維持する。

全体のbundle IDと配布ファイルそのもののSHA256を別々に照合する。headの木構造、全split、leaf、前処理を空の入力でも検査する。ファイル上限はUTF-8で64MiB。一部のheadだけを採用する取込は行わない。

## PC側のパッケージ作成

すでにexportとレビューを済ませたheadを使う。新しい学習、holdout開封、APIアクセス、承認を行うコマンドではない。

```powershell
uv run python -m mobile.pc.package_bundle --metadata data/private-delivery/metadata.json --heads data/private-delivery/heads.json --selection data/private-delivery/frozen-feature-selection.json --output data/private-delivery/model-bundle.json
```

`metadata.json` は `mobile/python/model_bundle.py` の `ModelBundle` から `bundle_id` と `heads` を除いた項目。本人レビューは既存のreview IDと内容が一致する記録、校正情報は認証済みの実際の計算結果を使う。IDや時刻を取込可能にするために作り直さない。

`heads.json` は `horizon`、`task`、`model_id`、`path` を持つ4件の配列。相対pathはheads.jsonの場所から解決する。selectionには、元の `feature_selection` wrapper付きの凍結artifact、または同じID・manifest・horizonsを含む抽出済みJSONを使える。

作成されるのはprivate bundleと `.pin-proposal.json`。proposalは `distribution_review=pending`、PC/実機parity evidenceは未設定のままで、取込できる承認を自動生成しない。実際の分配条件、採用・評価、PC/実機一致の根拠を確認した後に、APKの `mobile/model-policy.json` へ公開可能なhashと確認状態だけをpinする。出力先が存在する場合は上書きしない。

pin前の一致確認には端末内の `POST /api/v1/mobile/models/bundle/parity` を使える。`content` に同じファイル文字列、`rows` に凍結特徴量名を使った `5` / `20` の入力配列（合計1,000行まで）を渡し、4つの出力とbundle/headのhashをPC参照値と比較する。この処理はモデルを保存・承認せず、原予測も作らない。実機の試験記録と差分を別保存し、WASMでのfixture一致だけを実機証拠へ昇格しない。

## 端末での取込・計算

設定の「モデル一式を取り込む」でファイルを1回選ぶ。確認済みファイルの完全一致と全head・校正・レビューを検証してから一括保存する。単体headの古い保存データから校正情報を作らない。保存した重みが壊れた場合は、同じpinに一致するファイルの再取込で修復する。修復時刻を新しい利用可能時刻にし、締切前へ遡及しない。

「当日の数値予測を計算・保存」は、締切内に受領した当日の銘柄一覧、前営業日までの市場履歴、締切内のモデル選択と本人入力を使う。市場・業種の計算母集団は広いまま、抽出対象と全保有に対して4つのheadを評価する。履歴不足の新規候補は元の抽出票と理由を残して予測から除外し、保有の予測不足は全体を未完了にする。作れた出力は別に保持する。

元の5/20日予測は共有 `PredictionSnapshot` に保存し、ChatGPT調査が参照できる。数値の生成時刻、入力の締切、実際の参照情報の受領時刻を分ける。同じ条件の再計算は元の生成時刻と数値を再利用する。保存途中のintentからの復旧と、完了markerを失った保存済みsnapshotの照合を行う。本人入力が途中で変わった場合、新しいsnapshotの保存transactionで拒否する。ポートフォリオや約定は変更しない。

モデル等の前提が揃った場合の株数提案、300社に対応する研究用探索、日次background取得/計算/ChatGPT調査への接続はPR内に実装済み。実データ・実アカウント、最終モデル採用、Xiaomiの計算能力/更新/配送時刻の受入は未完で、合成入力やemulatorの成功とは区別する。全現金で銘柄予測が不要な状態も、仮の銘柄や予測値を作らずに記録する。現在の工程別の証拠は[完成条件](FINISHING_PLAN.md)を参照する。
