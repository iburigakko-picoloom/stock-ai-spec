package jp.stockai.app;

import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.HashSet;
import java.util.Set;
import java.util.function.BooleanSupplier;
import java.util.function.Supplier;
import org.json.JSONArray;
import org.json.JSONObject;

/** One bounded acquisition slice or one guarded calculation; never owns an Activity. */
final class DailyPipeline {
    interface Core { JSONObject request(String method, String path, String body) throws Exception; }
    interface Market {
        JSONObject fetch(boolean membership, String day, BooleanSupplier stopped) throws Exception;
        void acknowledge(boolean membership, String day, String acquisition) throws Exception;
    }
    interface Progress {
        void state(String state, String day) throws Exception;
        void notice(String key, String text) throws Exception;
    }
    static final class ProviderFailure extends Exception {
        final boolean credentials;
        ProviderFailure(int status) { super("PROVIDER_UNAVAILABLE"); credentials = status == 401 || status == 403; }
    }
    static final class CoreFailure extends Exception {
        CoreFailure() { super("CORE_VALIDATION_FAILED"); }
    }
    final Core core;
    final Market market;
    final Progress progress;
    final BooleanSupplier stopped;
    final Supplier<Instant> clock;
    static final ZoneId JST = ZoneId.of("Asia/Tokyo");

    DailyPipeline(Core core, Market market, Progress progress, BooleanSupplier stopped, Supplier<Instant> clock) {
        this.core = core; this.market = market; this.progress = progress; this.stopped = stopped; this.clock = clock;
    }
    void check() throws InterruptedException { if (stopped.getAsBoolean() || Thread.currentThread().isInterrupted()) throw new InterruptedException(); }
    JSONObject api(String method, String path, JSONObject body) throws Exception {
        check();
        JSONObject response = core.request(method, "/api/v1/mobile/" + path, body == null ? "null" : body.toString());
        check();
        if (response.getInt("status") != 200) throw new CoreFailure();
        return response.getJSONObject("body");
    }

    boolean currentCutoff(JSONObject value, String day) throws CoreFailure {
        try {
            Instant cutoff = LocalDate.parse(day).atTime(11, 30).atZone(JST).toInstant();
            Instant asOf = java.time.OffsetDateTime.parse(value.getJSONObject("scope").getString("as_of")).toInstant();
            return cutoff.equals(asOf);
        } catch (org.json.JSONException | java.time.DateTimeException error) { throw new CoreFailure(); }
    }

    boolean currentForecast(JSONObject value, String day) throws CoreFailure {
        return value != null && currentCutoff(value, day)
            && ("published".equals(value.optString("phase")) || "cash_only".equals(value.optString("phase")));
    }

    // Reference results are separate from the 11:30 forecast and can never
    // activate a share decision. At most one automatic attempt per day.
    boolean referenceFallback(String today) throws Exception {
        check();
        JSONObject response = core.request("GET", "/api/v1/mobile/daily/reference", "null");
        check();
        if (response.getInt("status") != 200 || !response.has("body")
                || (!response.isNull("body") && !(response.get("body") instanceof JSONObject))) throw new CoreFailure();
        JSONObject previous = response.optJSONObject("body");
        if (previous != null) {
            try {
                if (java.time.OffsetDateTime.parse(previous.getString("checked_at")).atZoneSameInstant(JST)
                        .toLocalDate().equals(LocalDate.parse(today))) {
                    progress.state("reference_saved".equals(previous.optString("phase"))
                        && previous.optJSONObject("snapshot") != null ? "reference_saved" : "inputs", today);
                    return false;
                }
            } catch (org.json.JSONException | java.time.DateTimeException error) { throw new CoreFailure(); }
        }
        progress.state("calculating", today);
        JSONObject reference = api("POST", "daily/generate", new JSONObject().put("reference_only", true));
        if (!today.equals(clock.get().atZone(JST).toLocalDate().toString())) return true;
        if ("reference_saved".equals(reference.optString("phase")) && reference.optJSONObject("snapshot") != null
                && "latest_available_reference".equals(reference.getJSONObject("scope").optString("analysis_mode"))) {
            progress.state("reference_saved", today);
            progress.notice(today + ":reference", "参考ランキングを保存しました。株数提案とは別の予測です。");
        } else {
            progress.state("inputs", today);
            progress.notice(today + ":inputs", "ランキングの計算を完了できません。市場データとモデルを確認してください。");
        }
        return false;
    }

    boolean acquire(boolean membership, String day) throws Exception {
        check(); progress.state(membership ? "membership" : "history", day);
        JSONObject receipt = market.fetch(membership, day, stopped);
        check();
        int status = receipt.getInt("status");
        if (status == 202) return false;
        if (status != 200) throw new ProviderFailure(status);
        if (!day.equals(receipt.getString("date")) || !receipt.has("acquisitionId") || !receipt.has("received_at")
                || !receipt.has("datasets") || (membership ? !receipt.optString("purpose").equals("membership") : !receipt.has("valuations")))
            throw new IllegalStateException("INCOMPLETE_RECEIPT");
        api("POST", membership ? "market/membership" : "market/ingest", receipt);
        check(); // Only acknowledge after the encrypted shared state commit.
        market.acknowledge(membership, day, receipt.getString("acquisitionId"));
        return true;
    }

    /** true requests another bounded slice; false leaves the durable periodic wake-up. */
    boolean tick(String firstDay) throws Exception {
        return tick(firstDay, false);
    }

    boolean tick(String firstDay, boolean acquisitionOnly) throws Exception {
        ZonedDateTime now = clock.get().atZone(JST);
        String today = now.toLocalDate().toString();
        JSONObject membership = api("GET", "market/membership", null);
        if (!today.equals(membership.getString("date"))) return true;
        if (!membership.isNull("acquisitionId")) market.acknowledge(true, today, membership.getString("acquisitionId"));
        if (!now.toLocalTime().isBefore(LocalTime.of(10, 30)) && now.toLocalTime().isBefore(LocalTime.of(11, 30))
                && membership.isNull("latest_received_at")) {
            if (!acquire(true, today)) return true;
            membership = api("GET", "market/membership", null);
        }
        JSONObject saved = api("GET", "market", null);
        JSONArray committed = saved.optJSONArray("committed_acquisitions");
        if (committed != null) for (int i = 0; i < committed.length(); i++) {
            check(); JSONObject receipt = committed.getJSONObject(i);
            market.acknowledge(false, receipt.getString("date"), receipt.getString("acquisitionId"));
        }
        Set<String> completed = new HashSet<>();
        JSONArray days = saved.getJSONArray("completed_dates");
        for (int i = 0; i < days.length(); i++) completed.add(days.getString(i));
        LocalDate first = LocalDate.parse(firstDay), last = now.toLocalDate().minusDays(1);
        if (first.isAfter(last)) throw new IllegalArgumentException("INVALID_HISTORY_RANGE");
        for (LocalDate day = first; !day.isAfter(last); day = day.plusDays(1)) {
            if (!completed.contains(day.toString())) {
                acquire(false, day.toString());
                return true;
            }
        }
        // A continued acquisition burst must not consume the next long
        // calculation's execution budget. Let a fresh Worker handle it.
        if (acquisitionOnly) return true;
        check(); now = clock.get().atZone(JST);
        if (!today.equals(now.toLocalDate().toString())) return true;
        if (Boolean.FALSE.equals(membership.opt("is_business_day"))) { progress.state("closed", today); return false; }
        if (now.toLocalTime().isBefore(LocalTime.of(11, 30))) { progress.state("waiting_cutoff", today); return false; }
        if (!membership.optBoolean("available_at_cutoff")) {
            return referenceFallback(today);
        }
        check();
        JSONObject existing = core.request("GET", "/api/v1/mobile/research/plan", "null");
        check();
        if (existing.getInt("status") == 200 && today.equals(existing.getJSONObject("body").optString("day"))) {
            progress.state("numerical_saved", today); return false;
        }
        JSONObject response = core.request("GET", "/api/v1/mobile/daily", "null");
        check();
        if (response.getInt("status") != 200 || !response.has("body")
                || (!response.isNull("body") && !(response.get("body") instanceof JSONObject))) throw new CoreFailure();
        JSONObject numerical = response.optJSONObject("body");
        if (!currentForecast(numerical, today)) {
            progress.state("calculating", today);
            numerical = api("POST", "daily/generate", new JSONObject());
            if (!currentForecast(numerical, today)) {
                JSONArray reasons = numerical.optJSONArray("blocking_reasons");
                String reason = reasons == null || reasons.length() != 1 ? "" : reasons.optString(0);
                if (reason.equals("PERSONAL_HOLDINGS_UNCONFIRMED") || reason.equals("PERSONAL_INPUT_AFTER_ALPHA_CUTOFF")
                        || reason.equals("LEDGER_RECEIVED_AFTER_ALPHA_CUTOFF") || reason.equals("HOLDINGS_NEED_RECONCILIATION"))
                    return referenceFallback(today);
                progress.state("inputs", today);
                progress.notice(today + ":inputs", "計算に必要な情報が不足しています。モデル・本人設定を確認してください。");
                return false;
            }
            if (!today.equals(clock.get().atZone(JST).toLocalDate().toString())) return true;
            progress.state("forecast_saved", today);
            return true; // Yield after the encrypted forecast commit; do not recompute it next slice.
        }
        progress.state("deciding", today);
        JSONObject decision = api("POST", "decision/generate", new JSONObject());
        if (!today.equals(clock.get().atZone(JST).toLocalDate().toString())) return true;
        JSONArray blocks = decision.optJSONArray("blocking_reasons");
        JSONObject comparison = decision.optJSONObject("comparison");
        if (!decision.optBoolean("is_active") && currentCutoff(decision, today)
                && "blocked".equals(decision.optString("phase"))
                && "blocked".equals(decision.optString("outcome"))
                && blocks != null && blocks.length() == 1
                && "FORECAST_RISK_UNAVAILABLE".equals(blocks.optString(0))
                && comparison != null && comparison.has("proposal") && comparison.isNull("proposal")
                && comparison.optString("manual_context_sha256").matches("[0-9a-f]{64}")) {
            progress.state("consultation_ready", today);
            progress.notice(today + ":" + decision.getString("run_id"),
                "研究用の予測を保存しました。株数の自動判定はなく、ChatGPTへの相談と回答の検算を利用できます。");
            return false;
        }
        if (!decision.optBoolean("is_active") || !currentCutoff(decision, today)) {
            progress.state("inputs", today);
            progress.notice(today + ":inputs", "株数の判定を完了できません。本人設定と台帳を確認してください。");
            return false;
        }
        progress.state("numerical_saved", today);
        progress.notice(today + ":" + decision.getString("run_id"), "今日の数値判定を保存しました。ChatGPT調査の状態をアプリで確認してください。");
        return true; // Research gets a fresh WorkRequest and execution budget.
    }
}
