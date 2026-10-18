# 実市場データから日次NAVへの接続

## D176: 明示した仮定付き研究経路

2026-10-19 D178：固定152条件の実行は83分48.760秒で終了。56条件は`COMPLETE_ASSUMPTION_RESEARCH`、96条件は`INCOMPLETE`（保有の配分参考価格欠損50、日次保有評価欠損28、既知未処理企業行動18）。5日76条件中16、20日76条件中40が仮定付き完走。単純baselineも不完全なので、その成績差は未定義のまま残す。結果、停止理由、全seed/種類別の安定性、日付/銘柄/最後に確認できた関連額/追加根拠を私有の比較表とJSONへ保存した。5日/20日・各役割の採否はHOLD、最終holdout未開封、追加fitなし。

一部結果を確認した後に追加した報告用の「観測された端点収益」は、宣言した全営業日の会計が継続し、期首と期末のNAVが実際に確定したcaseだけに表示する。日中の経路や欠損日の完全性を証明せず、事前固定した選定指標へ昇格しない。欠損価格の補完・期間変更・新しい戦略・別NAV計算器は追加しない。原結果/正常完了区分は維持し、不完全caseのMDD/turnoverは未定義。保有の参考価格がなく既存fixed ruleが停止した50条件には、同じ凍結入力/同じ会計処理による例外時点だけの私有診断を添えた。正常成績やgateを変更しない。

2026-10-19 D177：共通開発比較を結果前に固定した。5日は保存forward ensembleの全177営業日（2025-04-24〜2026-01-15）、20日は140営業日（2025-04-14〜2025-11-06）。期間は保存出力の利用可能範囲から決め、各horizon内で全候補へ同じ期間/銘柄キーを適用する。horizon間は別評価。全18候補の4出力キーと保存ensemble/baselineの一致を確認した。共通の国内100株単元条件以外に、成績や価格欠損による銘柄除外を追加しない。

Aは候補の順位score、Bは回帰return順位。Cは既存の日別平均percentile rankを回帰/順位で均等平均、Dは`(rank(return)+rank(ranking)+rank(q10)-rank(P(return<=-0.08)))/4`の一方式だけ。rankは元OOFの同日母集団上で`2*(average percentile-.5)`、国内対象への絞込みはその後。C/Dは無単位、期待returnとは表示しない。Eは保存forward-crossfitの`weighted_return`、単純baselineは保存`momentum_20d`のみを利用し、再fit/再校正/新ensembleは作らない。各9候補×A〜D＋E/baselineの2本、2horizon×20/40bpsで152条件。全seedを残し、最良seedだけを選ばない。

`SavedScoreSource.task`でA〜Dを明示し、`SavedBenchmarkSource`では元receiptとD170の認証済みreplayをpinする。元hash/特徴量版/研究区分/最終未使用/重み不変を照合し、目標/将来label列は読まない。対象の保有候補だけをメモリへ保持しても、市場receipt全体のhash・日付・重複チェックは省略しない。単一workerと既存RAM guardを維持し、各caseの入力は実行前に固定する。

全期間で保有評価価格が欠けたcaseは`INCOMPLETE`とする。対象銘柄・日付・最後に確認できた保有額・影響case・必要な追加根拠を私有`full/unresolved-issues.json`へまとめる。終値/出来高nullという確認事実を、売買停止や損失ゼロの確認へ読み替えない。欠損日を切り取った比較、仮の現金化、carry-forwardを確定価格にする処理は追加しない。

`research evaluate-assumed-market --input REQUEST.json --output-root PRIVATE_DIR`は既存の市場receipt/保存OOF/固定ルール/状態付きNAVを接続する専用入口。厳密な`evaluate-market-strategy`の企業行動全体・方向別執行・PIT等の根拠チェックと既定動作は変えない。仮定を必須のliteralとして入力し、実行前に入力をcontent-addressed `plans/`へ保存する。

研究条件は資金1,000万円・上位20・90%均等配分・100株単位・片道20または40bps、既存5日/20日入替・研究資金解放receipt。実口座の費用ではない。OOFの特徴量日は予測日より前を要求し、予測利用可能時刻より後の日足終値proxyで約定する。11:30/12:30の実約定を再現したとはしない。HOLDは同じ初期保有/資金で、今回の全現金開始では全現金維持。

確認事実は元OOF/特徴量ID、現Light固定取得版、raw価格、当該日の国内普通株100株単元/呼値、報告済みイベント種別/係数と全入力hash。研究仮定は日足出来高5%上限・UL買い/LL売り見送り・既存研究資金解放・単一後日取得版・報告された分割のみの会計。未報告企業行動の網羅性、厳密な方向別売買可能性、実容量/費用、当時の訂正版/公表時点は未確認として結果に残す。配当は除外でありゼロ確認ではなく、税引前。

1/3等のfloat係数は分母10,000以下の有理数へ戻して同じfloat表現と完全一致する場合だけ使用する。丸めた近似値は受け入れず、raw株価と株数を一度だけ調整する。通常の分割へ変換できない既知イベントは、その銘柄が保有または注文に影響する日に停止/不完全とする。保有評価不能も不完全とし、買えない銘柄の削除や仮の現金化をしない。

利用権限不明、byte破損、既知の未来情報、未処理の既知企業行動を正常完了にしない。結果に仮定・入力版・期間・未解決事項・コードhash・費用後NAV/MDD/費用/未約定/件数/停止理由を保存する。turnoverは「filled買付+売却総額 / 日末NAV平均」。`not_actual_execution_reconstruction=true`、`not_standalone_adoption_evidence=true`、採用不可/最終未実施を必ず付ける。仮定付き比較だけで採用条件を満たさず、根拠不足はHOLD、holdoutを消費しない。

最初の接続確認は成績で選ばない25営業日（2024-09-13〜10-22）、LightGBM/seed17/回帰順位の5日/20日各1本を20/40bpsで実行した。4結果とも全日の資金・保有・未収金=NAV、非負資金/株数、単元、費用一回計上を検算済み。最新実測は各4.288〜4.698秒。私有結果/条件/コード原本は`.demo-artifacts/scoped-completion-20261018/`、収益値や市場派生結果はGitへ含めない。全候補の同期間比較は別の未完工程。

`research evaluate-market-strategy`は、保存済み5/20日予測と既存の状態付きDecision Engine・NAV会計を接続する研究専用CLI。再学習しない。個人税の設定を待たず、税引前・費用控除後で同じ初期保有/現金のHOLDと比較する。モデル採用や最終holdoutの実行経路ではない。

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='.;src'
.venv/Scripts/python.exe -m stock_ai research evaluate-market-strategy --input <固定した接続入力JSON> --output-root artifacts/market-nav
```

入力型は`stock_ai.ml.market_nav.MarketStrategyRequest`。既存の`DailyStrategyInput`、認証済み`daily-market-projection-v1`のpath/byte SHA-256/期間、`write_daily_oof_day`で保存した日別予測のpath/byte SHA-256/as_ofを固定する。feature selectionを既存loaderで認証し、dataset・feature selection・holdout境界を市場receiptと照合する。各日の予測は保存済み予測と全項目が一致しなければ拒否する。

D170：D169の共通研究用資金ルールを使う新しい再生では、`research_funding_receipt`へ`research project-research-funding`のpath/byte SHA-256/暦日期間を指定する。NAV入口で内容を認証し、モデル/特徴量/holdoutのidentity、宣言期間と全暦日、calendar ID、全sessionの資金解放時刻を照合する。市場receiptと同じcatalog/store・source_snapshot_as_of・訂正版方針を要求し、別版のカレンダーや早い資金解放、未知末尾を補正しない。宣言期間のholdout検査は市場/資金fileを開く前に行う。

結果の`research_funding_policy`にはpolicy版・calendar ID・元receipt hash・`research_assumption=true`・`broker_verified=false`を保存する。過去の独立した根拠と明示時刻を持つ入力は省略のまま読めるが、結果を`null`として新ルール適用済みとは表示しない。資金scheduleが一致しても企業行動・方向別売買状態/容量・当時の情報・費用の確認は必要で、資金仮定を本人の口座余力や市場データ充足の証明へ使わない。

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

D174：市場射影に保存した`ex_rights_type`も照合する。ライツ(3)は`UNSUPPORTED_RIGHTS_ISSUE`、未知codeは`UNRECOGNIZED_EX_RIGHTS_TYPE`で停止し、通常分割の会計イベントで代用しない。種類1/2は非単位の調整係数と同日・同銘柄・逆比率が一致する確認済み分割/併合を必要とする。係数1の報告イベントは`UNRESOLVED_ADJUSTMENT`のまま。旧receiptの列省略は従来どおり読めるが、企業行動網羅の根拠を省略できるわけではない。

固定Light版の報告flag一覧は確認対象を探す私有資料であり、`NavAction`や全期間網羅の証明ではない。公式FAQも個人向けAPIに企業行動全体と売買停止のdatasetがないことを示す。保存済みの別資料は取得元・利用権限・対象期間・訂正/時点・網羅範囲を確認してから再利用する。[公式データFAQ](https://jpx-jquants.com/ja/help/data)。

不足があれば`status=BLOCKED`、理由、入力と実測時間をcontent-addressed receiptへ保存し、CLIはexit 2を返す。前提不足のときは成績を生成しない。判断や保有評価が途中で不完全になった場合もBLOCKEDにする。全条件が揃う場合は既存`evaluate_daily_strategy`を呼び、日別状態・費用・strategy/HOLD・差分を保存する。関連source hash、Pydantic版、Decimal精度28も記録する。テストの数値は合成入力で、実市場成績ではない。

最初の1本と18候補・単純戦略・ensembleで、期間・銘柄の利用条件・初期資産・売買規則・費用・受渡しを統一する。開発期間でモデル・売買規則・採用基準を固定し、その後に既存の単回holdout手順へ進む。本CLIはholdout境界以後の宣言された市場/予測fileを開く前に拒否し、採用可能とは表示しない。個人税は独立工程として追加する。

配当通知の入口は[配当データ接続](DIVIDEND_DATA.md)。保存済みV2通知の訂正・削除・予想/決定・利用可能時刻を照合し、条件が揃う決定配当だけを既存NavActionへ変換する。この処理単独では企業行動の全期間網羅を成立させない。

公式仕様を2026-10-17に確認：日足の調整価格は後続イベントで再計算され、ULは高値の上限到達を示す。特別気配、当時の取得可能時刻、訂正前データは日足だけでは補えない。[J-Quants日足仕様](https://jpx-jquants.com/ja/spec/eq-bars-daily)。配当の通知系列・訂正削除・予想/決定を区別し、権利落日・金額・支払開始予定日を確認する。通知時刻をJ-Quantsでの取得可能時刻へ読み替えない。[配当仕様](https://jpx-jquants.com/ja/spec/fin-dividend)。T+2の受渡制度と口座の買付余力解放は別に扱う。[JPX受渡制度](https://www.jpx.co.jp/equities/clearing-settlement/tplus2-settlement-cycle/index.html)。
