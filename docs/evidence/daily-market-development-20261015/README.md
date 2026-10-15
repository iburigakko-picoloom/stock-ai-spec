# 開発期間全体の日足raw/normalized照合

2024-07-31〜2026-03-03を14暦日ごとの42窓に分割して読み取り専用で認証した。
価格は1,702,477行、386営業日、raw/normalized 772 object。全receiptのcontent identity/byte hashと集計を独立に再確認した。

| 行の状態 | 件数 | 全行比 |
| --- | ---: | ---: |
| reported_no_trade | 73,469 | 4.32% |
| reported_trade | 1,629,008 | 95.68% |

特殊provider codeは1,675行、調整イベント要確認は394行。無約定・欠損・特殊codeを削除していない。
学習時の識別値に一致する営業日カレンダーに対し、価格行が全くない期待営業日は0、予定外の日付は0。OHLC大小関係の違反は0。個々の銘柄が完全に揃うことをこの日付照合だけで保証しない。

catalog/manifest/byte SHA、raw/normalizedの行metadata・キー・生OHLC/出来高/売買代金/調整係数を既存projectionで認証。終了時にも全対象ファイルのbyte hashと対象catalogが不変であることを確認した。日別件数/無約定/特殊code/調整要確認をsummary.jsonへ保存。明細はローカルartifactに残し、この証拠へ再配布しない。

固定vintageは2026-08-29。カレンダー全体のsource ID再計算には最終評価期間に当たる暦日も含むが、価格partitionは2026-03-04以降を読まず、予測・target・運用成績・最終評価を採点していない。
PIT投資対象銘柄の完全性、訂正前vintage、配当/分割/現金交付、終値での約定能力、呼値、決済、実用費用は未確認。evaluation_ready=false、adoption_eligible=falseを維持する。日付網羅や元ファイルとの一致をNAV・モデル採用の合格へ置き換えない。実注文なし。

独立集計の初回実行はWindows既定cp932で日本語pathを誤読し、content identity照合で停止した。元receiptのbyte hashと末尾改行を除くidentityは一致し、元ファイルは不変。JSON読込をUTF-8へ明示して全42receiptを再確認した。初回scriptと原因・修復範囲をverification-recovery.jsonへ記録し、元auditを再実行していない。
