# Goal 3 CPU cloud pilot — 準備・未実行

更新日: 2026-09-09

## 現在地

1台の試運転で速度・メモリ・料金を測る。クラウド契約、VM作成、データ転送、学習起動は未実施。
既存local runner、正常worker、研究source、dependency lock、campaign、成果物は変更しない。
この文書は研究条件の変更でも、残batchのクラウド割当予約でもない。

## 確認済み

- ローカルにOpenSSHのssh / scp / ssh-keygenがある。鍵生成・登録はまだ行っていない。
- Production Buildは `2fc936a7ca9b939d8016ad3c5efea17c53ffd5264d5ece398a8329bf2f2dfe5f`。
- Datasetは `3d837e220b4662d2405dafd295b91645813af6e8ffed8cd52a44988b49847a7d`。
- Dataset Parquet単体は1,858,772,624 bytes。これは転送総量・必要RAMの見積もりではない。
- Build manifestのDataset / Feature / manifest参照にはWindows絶対パスがある。
  Linuxでそのまま使えるとは扱わず、元metadataのパスやhashを書き換えて認証を迂回しない。

## 起動前gate

1. ユーザー所有のクラウドアカウント、支払い登録、サービス・税込予算・終了期限を確認。
   現在の候補はHetzner、1台、予算3,000円。承認済みとは扱わない。
2. J-Quantsの契約上、本人専用クラウドへの保存・計算が許される範囲を確認。
   不明なら提供元へ確認する。公開共有・第三者提供はしない。
3. 隔離した作業領域でdevelopment-only export/importを実装・検証。
   元snapshotとsplitを認証し、holdout行と境界を跨ぐlabelを除外する。
   元IDとexport hash、順序付き列、row identity、split、config、code、依存版を結び付ける。
   元Buildを別物へ上書きせず、identity不一致はfail closedする。
4. Linuxで固定依存を再現できるかfixtureで確認。Windowsの.venvはコピーしない。
   OS / CPU / ライブラリ差を記録し、数値比較の許容差を実データ計測前に固定する。
5. 転送allowlistを固定。APIキー、.env、口座・保有情報、holdout、稼働中SQLiteは転送しない。
   Git repository全体やdata/live全体の無選別アップロードは禁止。
6. SSH鍵認証、host key検証、接続元を絞ったfirewall、非公開出力領域を用意する。
7. 成果物回収・hash照合・期限切れ時のVM削除までを試験する。
   予算アラートやOS shutdownだけを課金上限とみなさない。

## 試運転設計

- 候補構成はx86_64 dedicated vCPU / RAM 32 GiB以上。実際のSKU・空き・価格は発注画面で再確認。
- 最初は1 worker、既存と同じ1 thread。RAMピーク未測定で複数workerを詰め込まない。
- LightGBMとCatBoostの固定development foldを別々に測る案とする。
  exact fold / task / seed / parameterは起動前に固定し、精度を見て変えない。
- pilotは時間比較用の隔離成果物。既存正式campaignのreportやcheckpointへ自動登録しない。
  比較に必要な限定的再計算を正式batchの重複完走へ拡大しない。
- wall time、CPU time、peak RSS、swap、disk I/O、出力hashと数値差、課金時間をrunnerが保存する。
  CodexがPID / CPUを継続監視する設計にはしない。
- 同じ仕事のlocal実測がない場合は速度倍率を断定しない。
  一つのfamilyの倍率を全family / horizonへ外挿しない。
- 本番移行は別gate。local runnerとremote間のbatch所有権を安全境界で固定できるまで
  PENDING batchもremote起動しない。5日→20日の順序を無断変更しない。
- 全seed、walk-forward、Full Ablation、評価基準は削らず、holdout未開封を維持する。

## 費用の判断

公式価格表のEU CCX33参考単価は税・IPv4別で$0.2612/時。
仮に1ドル150円なら24時間のVM本体は約940円。為替150円は例示であり現在レートではない。
実際のSKU・メモリ容量・税・IP・保存容量・転送・為替を含めて起動前に再見積もりする。
3,000円は予算案であり、自動的に超過を防ぐ保証はない。

- [公式価格表](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/)
- [課金FAQ](https://docs.hetzner.com/cloud/billing/faq/)

サーバーは電源OFFでも存在する限り課金される。終了時は成果物を回収・認証し、
試運転VMと不要な課金対象IP / volume / snapshotを明示IDで削除し、削除結果を確認する。
回収失敗時も期限を無断延長しない。削除前に成果物保全とユーザー承認済み期限方針を確認する。

## 次の作業

アカウント・予算確認と並行して、隔離環境でdevelopment export/importとLinux fixture検証を用意する。
これらのgateを通す前に課金VMを作らない。現段階ではクラウドでの高速化・正式成果物再利用は未検証。
