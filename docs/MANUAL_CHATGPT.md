# 本人用ChatGPT連携

2026-10-18、D162/D163。初期方式はAndroidに保存した入力を本人がChatGPTへコピーし、回答JSONをアプリへ戻す方式。有料OpenAI APIを前提にしない。モデル・推論設定はChatGPT側で選ぶ。手動経路では実際の利用モデルをアプリが認証できないため、確認できないモデル名や推論量を生成しない。

## 入力と回答

入力は新規候補上位20銘柄と順位外を含む全保有、別々の5日/20日予測・意味・単位、既知の不確実性/リスク、口座別株数/利用可能資金/NISA残枠、設定済み費用とリスク制限、予測/データ時刻・モデル版・口座snapshotを含む。ランキングscoreを期待リターン率へ変換せず、5日/20日を加算しない。不明値や未校正の確信度を作らない。

D185（2026-10-19）：D184の起点判断を撤回。実際の保存OOFと2実weightは本番研究用`build_production_supervised_dataset`／`_add_horizon_labels`を使用し、Tを入力株価日として`adjusted_close[T+1+h] / adjusted_close[T+1] - 1`（翌営業日終値を起点にh営業日後）である。基本研究用`build_supervised_dataset`のT→T+hと混同しない。元datasetのidentityと保存OOF/fit入力の開発期間の値を照合済み。新規snapshot/bundleは元のnext-session記述を使用し、c710/0.1.17のquote-session記述原本は保全して新規判断使用を拒否する。モデル採用認証とは別。数値・weight・NAV・18候補比較は不変。0.1.17候補は撤回。修正版0.1.18はCI39197573498の必要試験・署名候補の検証済み。

外部用口座名はA1等のaliasとし、口座番号・broker名・APIキー・認証情報・モデルweightは出さない。アプリ内表示名への対応は端末内だけで使う。入力項目の射影と検証実装hashをsnapshot IDへ含める。個人比較receiptと原予測/台帳/設定/価格の一致を検査し、比較後15分・JST同日を超える入力は拒否する。

対象は上位20銘柄×全口座に、実際に保有する順位外の銘柄/口座pairを加えた集合。全保有を残し、空の順位外口座との不要な直積は作らない。既存の最大30口座・200保有では最大800pair。回答は全pairを一度ずつ含める。

| 回答項目 | 契約 |
| --- | --- |
| schema_version | `chatgpt-target-shares-v1` |
| input_snapshot_id | 入力のSHA256 IDと完全一致 |
| evidence_as_of | timezone付き根拠時刻。入力以降・検証時点以前 |
| targets | symbol、account alias、target_shares、reason、sources |
| target_shares | 0〜100,000,000の整数。文字列・bool・小数は不可 |
| reason / sources | 空白だけでない理由、資格情報を含まないHTTPS出典 |
| unknowns | 未確認事項。確認できない情報を補完しない |

独立した企業分析・公開IR調査・反対根拠・不確実性を求め、モデルへの同調を求めない。原予測が良いことやChatGPTが収益性を改善することは仮定しない。

## 拒否と保存

256KiB超、不正/深すぎるJSON、重複key、NaN/Infinity、不明field、株数の型違反、空の理由、重複/不足/対象外pair、異なる/古いsnapshotや将来時刻を拒否する。JSONの囲みを除去したり数値を丸めたりして受け入れない。エラー後は入力を編集して再試行できる。

売買株数は目標株数−現在株数としてアプリが計算する。既存Decision Engineの評価部品で単元、保有、資金/費用/税、予算、口座/NISA制約、流動性、銘柄/業種/現金比率、回転率等の設定制限を検査する。高度な配分探索は追加しない。未約定売却の代金を新規買付資金へ算入しない。制約違反は理由付きで拒否し、黙って補正しない。

入力package・原文回答・検証結果を既存SQLite metadataへhash付き不変recordとして保存する。同一回答の再取込は最初の受理時刻を維持し、履歴を増殖させない。原予測、ChatGPT提案、本人の実約定は別の記録で、回答取込だけでは保有・現金・税台帳を更新しない。実際の約定確認後だけ既存の手動約定処理で反映する。直近20件を画面で再表示でき、現在の保有と取り違えない。

新しいDB tableや別のwriterは設けず、既存native owner・transaction・暗号化保存/backupを再利用する。backup/restoreでは入力/回答/許可recordのhashと参照関係も検査する。

D164：画面再作成・アプリ再起動後は、保存済み入力の元ID・本文・有効期限を読み取り専用で再表示する。現在の原予測/口座/設定・検証版と送信許可が一致する場合だけ再利用し、再表示で入力を再生成したり、期限/確認時刻を延長したりしない。古い入力は保存したままコピー対象から外し、提案履歴は引き続き読める。コピーを押した時点でも端末内で再照合し、不一致・期限切れ・確認失敗ならクリップボードへ書き込まない。確認中は作成/コピー/回答検証を直列化し、回答欄を保持する。新規外部送信や確認欄の自動有効化は行わない。

## 実データ送信の条件

[J-Quants公式FAQ](https://jpx-jquants.com/ja/help/usage)の生成AI項目を2026-10-18に確認。本人分析のみ、学習等の二次利用なし、第三者に入力を公開しない、生成結果を配信/公開しない、の4条件をサービス別に確認する。集約・匿名化だけを許可根拠にしない。銘柄/順位・予測/リスク/価格とlineageを含むJ-Quants由来fieldを対象とし、取得/利用範囲の契約権限も別に確認する。

本人は手動ChatGPTの設定・運用4条件を確認済みと回答し、その後Light契約済みと連絡した（D167）。LightのTOPIX要求はHTTP200、開発期間の基本5種類も新しい保存先へ取得済み。契約未確認による一律停止は解除し、現在のLight範囲と確認済みの項目から研究を進める。旧Standard取得原本を現在のLight権限で一律利用可能と読み替えず、保持/利用範囲の論点を残して確認なく削除しない。再取得を規約上の必須条件や過去の利用の解決と断定しない。今回の外部送信は未実施で、アプリの項目別許可・時刻・snapshot検証と本人の実操作受入は引き続き必要。過去403は履歴として保持し、新規課金は行わない。

操作時には許可根拠の版・対象サービス・timezone付き確認時刻と4条件・データ権限を保存し、24時間超/未来/不一致/未確認を拒否する。手動ChatGPTの確認を任意のアカウント接続へ転用しない。確認欄を自動で有効にしない。保存済みの完了済み調査を読むだけの操作には新しい送信確認を要求しない。

[OpenAIのデータコントロール](https://help.openai.com/en/articles/7730893-data-controls-in-chatgpt)で新規会話の学習設定とfeedbackの例外を確認した。会話共有・公開・feedback送信等で条件を崩さない。アプリはChatGPTの設定を直接確認したとは表示しない。

## 実装の境界と検証

- `operations/chatgpt_manual.py`：外部入力射影、厳密JSON、snapshotと既存制約の検証、不変receipt。network/注文送信なし。
- `mobile/python/manual_chatgpt.py`：端末内の現行comparison/台帳との照合、直列保存と履歴。
- Android local API：`GET /api/v1/mobile/chatgpt-manual/status`、`POST .../export`、`POST .../answer`。
- 既存任意接続：`POST /api/v1/research/permission`でサービス別確認、未確認claimはprovider request作成前に停止。
- `/today/chatgpt`：入力作成→コピー→回答検証の2段階。ボタン高さ48px以上・間隔12px以上、320/390px・文字150%で確認する。

合成データでPC/通信遮断WASMの入力・費用・回答検証一致、再取込、保存/再読込/backup復元、拒否時の台帳不変を試験する。合成試験を実アカウント・Xiaomi実機・本番モデル採用の証拠にしない。固定ルール成績との比較は別管理し、今後の仮想運用/本人実約定を過去シミュレーションへ混ぜない。

契約確認と独立したブラウザー受入は`web/mobile-tests/manual-flow.spec.ts`で再現する。既存の`scripts/prepare_mobile.py`と`python -m scripts.generate_mobile_golden`でローカルruntime/合成fixtureを用意してから、webで`npx playwright test --config playwright.mobile.config.ts mobile-tests/manual-flow.spec.ts`を実行する。製品の画面とAPI adapterから同梱Pythonの厳密検証まで接続し、実clipboard、画面再作成時の本文/期限一致、不正回答の編集、正常取込、履歴の重複抑止、期限切れコピー/取込拒否と台帳/原予測不変を確認する。PC fixtureの確認時刻は画面と同じUTC表記とする。Windows clipboardの改行変換を区別し、保存した入力原文の完全一致は維持する。

試験専用native bridgeは使い捨てbrowserのsessionStorageで状態を渡す。合成承認と時計の注入は試験worker内だけに置き、製品へ含めない。この試験は実データ、外部ChatGPT、Android native暗号化保存やXiaomiの操作確認を代替しない。

受領履歴からの接続は`tests/test_mobile_forecasts.py::test_received_history_to_forecast_manual_review_and_restore_without_feature_doubles`でPC検証する。24銘柄/270営業日の合成履歴を実際に正規化/保存し、特徴量計算・4head推論・個人比較を通して作った入力で、上位20＋順位外保有の21pairを確認する。回答取込/同一回答再取込、原予測と実台帳の不変、全tableのschema/型付き内容のbackup復元を照合する。試験用model/selection設定だけを供給し、製品policy・採用・送信確認を有効化しない。これは前記browser/WASMやnativeの試験とは別のPC統合証拠である。

`web/mobile-tests/received.spec.ts`は同じ受領履歴の予測前状態から、同梱WASM自身で対象抽出/41・51特徴量/4head予測→費用込み株数比較→21pairの目標株数回答を検証する。別の合成設定で非ゼロの売買費用を確認し、snapshot違いの拒否、重複回答1件、原予測/台帳不変・実約定0、操作27＋市場等17tableの全schema/typed cell一致をexport前後/復元後/再取込後に要求する。元の無売買PCケースも保持する。PC/WASMの数値は既存portable許容差、金額文字列・株数・その他の非数値は完全一致。既知のPandas32/64bitの欠損値hashだけを元masterから計算してWASMのデータIDを予測し、全data proof（特徴量内容hashを含む）を完全照合する。製品の出所IDは変更しない。提案の派生ID/出所guardは各環境で既存実装が照合し、環境間で同一IDとは主張しない。

準備は上記と同じで、webから`npx playwright test --config playwright.mobile.config.ts mobile-tests/received.spec.ts mobile-tests/feature-input.spec.ts`を実行する。2026-10-18には3件が212.292秒、fail/skip/retry0で成功。新しい通し部分は63.982秒。合成のモデル/承認/時計とSQLite証拠utilityは試験harnessだけに供給し、製品APKへ含めない。WindowsのEdge/WASM検証であり、実ChatGPT・Android native保存・採用モデル・全市場model推論・Xiaomiの受入とは区別する。


## D188：risk未提供の研究用相談

research bundleの5日/20日returnだけでも、通常の原予測保存から相談を作れる。自動proposalがない場合は、他の全照合が成功し、唯一の停止理由が `FORECAST_RISK_UNAVAILABLE` で、現行口座/原予測/設定へ結び付いたdigestが一致することを要求する。最新run/model pin、本人/設定revision、実約定が変われば拒否する。

入力には未提供risk/uncertaintyをnullと `model_risk_available=false` で渡す。nullをゼロリスクと解釈せず、外部回答の株数・資金検算もモデルriskの検証とは扱わない。既存の費用/税/単元/口座/数量/利用可能資金/設定済み制限と、未約定売却を買付余力へ使わない規則は同じengineで維持する。自動効用の比較は行わない。

15分超の回答は従来どおり拒否する。明示的な最新条件の再照合で新しい相談contextを作れるが、原予測の時刻/価格を更新せず、旧入力/回答の履歴を残す。正常回答も別の提案保存に留める。合成受領履歴を実feature計算から通すPC/WASM試験にreturn-only分岐を加え、非ゼロ費用、snapshot拒否、全tableの復元と実台帳不変を確認した。実bundleのbrowser-WASM取込/予測一致/再読込は別証拠であり、Xiaomiや本人実ChatGPT操作の代替ではない。

## D200：実保存予測を使うAndroid通常APIの接続確認

2026-10-20、製品58c8a2e・既存署名0.1.22は変更せず、実730日/研究2回帰から保存した原予測で、上位20の入力、回答拒否、維持案/費用付き株数案の検算、重複抑止、別processの読戻し、期限切れと新contextを確認した。全入力射影・株数・費用・現金見込みはPC一致し、原予測/実台帳/実約定は不変。全17mobile/全operation tableと回答recordをhostで独立検査した。試験口座・試験回答とprivate clockによる通常APIの試験であり、外部ChatGPTへの実送信、実時刻OS更新、Xiaomiの本人操作を実施済みとはしない。許可欄の自動有効化や新しい外部連携を追加しない。集約結果は[evidence](evidence/android-runtime-20261020/manual-exchange.json)、本人操作は既存の一括受入票へまとめる。
