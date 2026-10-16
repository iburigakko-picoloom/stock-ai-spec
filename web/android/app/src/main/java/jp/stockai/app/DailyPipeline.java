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
        check(); now = clock.get().atZone(JST);
        if (!today.equals(now.toLocalDate().toString())) return true;
        if (Boolean.FALSE.equals(membership.opt("is_business_day"))) { progress.state("closed", today); return false; }
        if (now.toLocalTime().isBefore(LocalTime.of(11, 30))) { progress.state("waiting_cutoff", today); return false; }
        if (!membership.optBoolean("available_at_cutoff")) {
            progress.state("late", today);
            progress.notice(today + ":late", "11:30までの当日情報が不足しています。保存状態を確認してください。");
            return false;
        }
        progress.state("calculating", today);
        JSONObject numerical = api("POST", "daily/generate", new JSONObject());
        if (!"published".equals(numerical.optString("phase")) && !"cash_only".equals(numerical.optString("phase"))) {
            progress.state("inputs", today);
            progress.notice(today + ":inputs", "計算に必要な情報が不足しています。モデル・本人設定を確認してください。");
            return false;
        }
        JSONObject decision = api("POST", "decision/generate", new JSONObject());
        if (!decision.optBoolean("is_active") || !decision.getJSONObject("scope").getString("as_of").startsWith(today + "T")) {
            progress.state("inputs", today);
            progress.notice(today + ":inputs", "株数の判定を完了できません。本人設定と台帳を確認してください。");
            return false;
        }
        progress.state("numerical_saved", today);
        progress.notice(today + ":" + decision.getString("run_id"), "今日の数値判定を保存しました。ChatGPT調査の状態をアプリで確認してください。");
        return false;
    }
}
