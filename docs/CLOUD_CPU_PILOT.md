# Goal 3 CPU cloud pilot — ローカル設計・外部未実行

更新日: 2026-10-03 JST

## 現在地と今回の境界

候補学習は計算待ちではなくメモリ不足で停止している。attempt20の最終観測は
2026-10-02 23:59 JST。前処理で `(89, 3985623) float64 / 2.64 GiB` の確保に失敗し、
CatBoost seed29 ranking fold6は進んでいない。h5は7/9完了、seed43はPENDING、h20候補は未作成。
保存済み11 outer fold（regression 1–6、ranking 1–5）と4 tuning unitを保全する。
11 foldの実ファイル認証は前回復旧作業で済み、今回の調査は合成fixtureだけである。

同条件再起動は行わず、StockAI-Goal3-Candidatesの一時Disabledを維持する。
VM作成、契約、鍵生成・登録、外部転送、外部学習、課金、他アプリ終了、OS変更は未実施。
2026-09-09のHetzner/3,000円案は未承認の旧参考案であり、今回の起動許可・料金保証ではない。

## 値を変えない前処理パッチの検証

初期usable / development / tuningの3箇所の `frame.loc[mask].copy()` を、
各列のExtensionArray.takeで同じ行をコピーし、DataFrame(copy=False)で列を保持する方法へ置き換える。
maskのindex一致を検証し、nullable maskのNAは従来locと同じく除外する。
列順・dtype・index・attrs・重複ラベル方針を保持し、各列は元データから独立する。
development構築後は不要なusable参照を解放する。float64をfloat32等へ変えず、列は削らない。

- 本体のsrc・依存・runner・campaign・checkpointは今回変更しない。検証用overlayと未適用patchは
  `C:/Users/manat/Documents/Codex/2026-10-01/task/stock-memory-review/` に保存する。
- patch: initial-preprocessing.patch、再生成: ../stock_memory_prepare.py、fixture: test_preprocessing_parity.py。
- 38 fixture pass（9.46秒）。89 float64列を含む64行、欠損・無限大・各種extension dtype、
  4種類のindex、全選択・空・nullable mask、CoW on/off、変更独立性、内容hash一致を確認。
- LightGBM / CatBoost各270行・5 iterations・1 tuning trialの合成fixtureで旧新OOFの完全一致、
  report ID、指標、分割境界、ensemble、seed stability、選択parameterの一致を確認した。
  これは本番の41/51特徴・300 iterationsを変更したものではなく、テスト専用条件である。
- 既存checkpoint / stage splitの対象13 test pass（3.62秒、32 deselected）。
- 未適用overlayのRuff pass、strict mypyは48 sourceすべてpass。
- 64行fixtureの選択後float64総量は旧新とも22,784 bytes。一番大きい連続blockは
  旧22,784 bytesから新256 bytesへ分割される。総データ量を1/89へ減らしたという意味ではない。

大きな連続確保を列単位へ分けられることは確認したが、実データのピークRAM・収束は未検証。
foldのiloc(...).copy()、sort、diagnosticsには後続の深いcopyが残る。fragmented frameに対する
deep copyはpandasで再結合され得る。小さな31 MiB確保にも失敗した過去があり、これだけで復旧を保証しない。
追加copy変更は同様の意味・証拠一致試験を別途通す。条件変更が必要ならそこで停止して設計を返す。

## 固定identityと転送対象

- source pin: 94aab783dce5d01cf5ee153297891a42cfdfe53e
- build_id: 2fc936a7ca9b939d8016ad3c5efea17c53ffd5264d5ece398a8329bf2f2dfe5f
- dataset_id: 3d837e220b4662d2405dafd295b91645813af6e8ffed8cd52a44988b49847a7d
- selection_id: 13c8676f84f24eaceaa2015395794cda0e1b2e249dfe5412640a31b6e8e9c81d
- seed29 checkpoint_id: 67616cc829bbb148c59aead9d3ea1cea79a8b759e11d02b962abe69de699deda
- 条件: CatBoost 1.2.10、CPU、1 thread、300 iterations、seed17/29/43、h5=41/h20=51特徴。

全行4,058,130。Dataset 1,858,772,624 bytes、V0 532,215,136、V1 1,236,163,031、
V2 1,495,713,188、計5,122,863,979 bytes（4.771 GiB）。Candidate checkpointは約0.647 GiB、
完了report/OOF約0.547 GiB。合計約5.965 GiBはローカル資産容量であり、承認済み転送量ではない。
後続選択には18件のAblation report/OOFとcampaign・selection根拠も必要。容量を別途allowlistで確定する。

元Dataset/V0/V1/V2の丸ごとuploadは禁止。locked holdoutを含み、元loaderは全体hash・shapeを要求する。
本人の許諾確認後、ローカルで元Buildとsnapshotを認証し、holdout行と境界を跨ぐlabelを除いた
development-only exportを生成する。derived IDを付け、元Dataset IDへ偽装しない。
最初のpilotはcampaign全体ではなく、固定済みのdevelopment fold/taskを直接検証する専用入口とする。
切り出し後のframeへ通常のholdout予約を再適用すると境界が変わるため、そのままrun_advanced_researchを呼ばない。

## export manifestの設計（未実装）

新schemaのimmutable manifestへ次を結び付ける。

1. 元Build/Dataset/Feature/selection ID、元metadata hash、source commit、patch hash、依存lock hashと実版。
2. 派生export ID、各ファイルのrelative logical path・byte size・SHA256・content hash・row count。
3. 順序付き全columnとdtype、元row ordinal・symbol/date/as_of、全列の値、index identity。
   export側の通し番号だけに置き換えず、元foldが参照した位置順も別に保存する。
4. 元holdout_start、label_end purge predicate、tuning/outer境界、各foldのtrain/validation row IDsと順序。
   export内にholdout行・境界を跨ぐlabelが無いことのローカル認証receiptを含める。
5. config_hash、seed、task、horizon、選択feature順、学習parameter、CPU実行方針と数値照合基準。
6. 元証拠を認証したローカル検証結果と信頼経路。receipt自体のhashだけで認証済みとは扱わず、
   承認されたmanifest hashまたは検証鍵を別経路で固定し、差替えを検出する。

Windows絶対pathを持つ元JSON・fold metadata・progressは一切書き換えない。
別manifestのpath mapがlogical IDから新OSのallowlist root内ファイルへ解決する。
loaderは元hashとexport hashの両方を検証し、root外・欠落・重複・順序/dtype/hash不一致をfail closedする。
Windowsの同一絶対layoutならpath問題は減るが、許諾・全体holdout転送禁止・実行環境差は別途解決が必要。
Windows .venvをLinuxへコピーせず、固定lockから別環境を作り、OS/CPU/Python/library版を記録する。

## 11完了foldの再利用方法（設計、未実装）

既存namespaceはcode_commit・全config・Dataset/Feature ID・feature順を含むhashで固定されている。
前処理patch適用やdevelopment exportでこれらが変われば新namespaceになる。
旧commitを名乗る実行やmetadata hashの書換えで既存checkpointへ接続しない。

認証済みimport bridgeを別途実装する。元namespace/progress/各fold metadataを読み取り専用で認証し、
元checkpoint_id・unit_id・Parquet byte hash・content hash・shape/columnと完全なevidenceを照合する。
新入力に対して元train/validation位置hash、日付境界、feature/parameter/configを再導出する。
indexを再採番したexportでは元位置map経由の照合が必要で、見かけの日付一致だけでは受け入れない。

旧11foldのOOFをimmutable入力として新namespaceへatomic publishし、source checkpoint / fold /
hash / 旧新code / 相違一覧 / equivalence receiptを明示的なimport provenanceとして記録する。
再利用した結果は旧CPU版が計算したものと明示し、新版が計算したことにしない。
bridgeを使う新experimentも追跡し、現行campaignへの採用と残foldへの継続は別の承認済み互換境界で行う。
任意のunitをSUCCEEDEDへ直接書換えず、保存checkpointは削除・上書きしない。

合成fixtureのOOF完全一致と既存再利用testは今回passしたが、実データ11foldの新evidence照合、
import/reload/tamper fail-closed試験、環境間結果一致は未実施。したがって正式再利用可能とはまだ宣言しない。
4 tuning unitは独立した認証設計で結果JSON・trialとparameterを照合し、稼働中SQLiteは転送しない。

## CPU thread変更・GPUの扱い

最初のpilotは1 worker / CPU 1 threadを固定し、family/horizonを別々に測る。
複数threadは新execution variantとして別experimentを登録し、同じrow/split/seed/parameterで
前処理・予測のexact照合を先に行う。OS差による許容差が必要なら測定前に値と採否規則を固定する。
一致を確認する前に旧結果と混ぜず、浮いたvCPU数から速度倍率を推定しない。
[CatBoost公式thread_count](https://catboost.ai/docs/en/references/training-parameters/performance)は
CPU thread数は結果を変えないと説明しているが、source/provenance互換手順は省略しない。

GPUは別experiment。GPU学習は非決定的で、未指定border_countもCPU254から通常GPU128へ変わる。
YetiRank/RMSE/Quantile/Loglossの実設定・CPU/GPU既定値を展開して固定し、数値差と性能を別評価する。
hostのpandas前処理が今回の停止箇所なのでGPU利用だけで解消するとはみなさない。
[GPU training](https://catboost.ai/docs/en/features/training-on-gpu) /
[parameter tuning](https://catboost.ai/docs/en/concepts/parameter-tuning)

## 価格参考と費用対効果（2026-10-03 JST公式ページ確認）

| 候補 | 公称容量 | 本体時間単価USD | 本体1/6/24時間USD |
| --- | --- | --- | --- |
| DigitalOcean Memory-Optimized | 64 GiB / 8 vCPU | 0.50 | 0.50 / 3.00 / 12.00 |
| DigitalOcean Memory-Optimized | 128 GiB / 16 vCPU | 1.00 | 1.00 / 6.00 / 24.00 |
| RunPod RTX 6000 Ada | RAM167 GB / VRAM48 GB / 10 vCPU | 0.84 | 0.84 / 5.04 / 20.16 |

これは計算例であり、所要時間見積もり・空き・region/host実容量・購入条件の保証ではない。
税、為替、disk/volume、停止中storage、snapshot、IP、超過転送等を別に見積もる。
[DigitalOcean公式価格](https://www.digitalocean.com/pricing/droplets) /
[RunPod公式価格](https://www.runpod.io/pricing)

64 GiB CPUは現在条件を守る最初の候補。128 GiBの倍額が効くかはpeak RSS・swap・wall timeで判断する。
GPUと64 GiB CPUの本体単価だけなら、GPUがCPUの0.50/0.84≒59.5%以下の時間で
同じ承認済み仕事を完了したとき費用を下げ得る。転送・環境準備・検証費用と研究結果の差は別である。
速度実測が無く、総残時間・総額・日数を作らない。実装/移行作業時間と計算待ち時間を分けて記録する。

## 許諾・起動前の未解決事項

- 本人契約J-Quantsのplan/申告目的と、本人専用クラウドの保存・計算・バックアップの可否。
  不明点は提供元へ確認する。第三者が利用可能になる設定や公開共有を認めない。
  [公式規約第8条](https://jpx-jquants.com/ja/termsofservice)は本人の私的使用に限定し、
  編集加工データも含む。規約最終改定2026-01-19、確認2026-10-03 JST。
- ユーザー所有account、サービス・SKU・region/host、税込予算、利用期限、成果物回収失敗時の方針。
- 開発export/import、path map、checkpoint bridge、Linux fixtureと実データ証拠照合の未実装を解消する。
- APIキー/.env/口座/保有/実行済み取引/live SQLite/holdoutはallowlistに入れない。
  repo全体やdata/live全体を無選別uploadしない。
- SSH host key、接続元を限定したfirewall、本人だけの非公開保存、期限後のデータ消去を確認する。
- local/remoteのbatch所有権を安全境界で固定し、同じbatchの二重実行を防ぐ。
  PENDINGも先走って起動せず、5日→20日の順序と評価・holdout未開封を守る。
- runner終了時のdurableなwall/CPU time・peak RSS・swap・disk I/O・出力hash・課金時間を取得する。
  Codexの継続PID/CPU監視を使わず、単発の成果物確認だけにする。
- 成果物を回収・認証後、承認済み期限方針に従って明示IDのVMと不要volume/IP/snapshotを削除し、
  結果を確認する。shutdownや予算アラートを課金停止・上限保証とみなさず、期限を勝手に延長しない。

この調査で外部へのupload、クラウド契約、課金VM作成、学習再開、実注文は一切行っていない。
