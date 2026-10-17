import { beforeEach, expect, test, vi } from "vitest";
import { apiGet, apiPost } from "../api";
import { StockAI } from "./native";
import { acquireMembership, acquireRange, pendingDates, shiftDate, type MarketStatus, type MembershipStatus } from "./market";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("./native", () => ({ StockAI: { fetchMarket: vi.fn(), acknowledgeMarket: vi.fn(), restartMarket: vi.fn(),
  fetchMembership: vi.fn(), acknowledgeMembership: vi.fn(), restartMembership: vi.fn() } }));
const empty: MarketStatus = { latest_data_date: null, completed_dates: [] };
const plan = { first_day: "2026-01-05", last_day: "2026-01-06" };
const receipt = (day: string) => ({ date: day, acquisitionId: `fixture-${day}`, status: 200,
  received_at: "2026-01-07T01:00:00Z", datasets: {}, valuations: [] });
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiGet).mockResolvedValue(empty);
  vi.mocked(apiPost).mockImplementation(async (path, input) => path.endsWith("/ingest")
    ? { latest_data_date: (input as { date: string }).date, completed_dates: [(input as { date: string }).date] } : plan);
  vi.mocked(StockAI.fetchMarket).mockImplementation(async ({ date }) => receipt(date));
  vi.mocked(StockAI.acknowledgeMarket).mockResolvedValue(undefined);
});
test("calendar iteration validates actual ISO dates and range even if all dates are saved", () => {
  expect(shiftDate("2024-02-28", 1)).toBe("2024-02-29");
  expect(() => shiftDate("2026-02-30", 0)).toThrow();
  expect(() => pendingDates({ first_day: "2020-01-01", last_day: "2026-01-01" }, [])).toThrow();
  expect(pendingDates(plan, ["2026-01-05"])).toEqual(["2026-01-06"]);
});
test("only pending dates are fetched and receipt cleanup follows durable shared commit", async () => {
  const events: string[] = [];
  vi.mocked(apiGet).mockResolvedValue({ latest_data_date: "2026-01-05", completed_dates: ["2026-01-05"],
    committed_acquisitions: [{ date: "2026-01-05", acquisitionId: "saved" }] });
  vi.mocked(apiPost).mockImplementation(async path => { events.push(path); return empty; });
  vi.mocked(StockAI.acknowledgeMarket).mockImplementation(async ({ date }) => { events.push(`ack-${date}`); });
  await acquireRange(plan, vi.fn(), () => false);
  expect(StockAI.fetchMarket).toHaveBeenCalledTimes(1);
  expect(StockAI.fetchMarket).toHaveBeenCalledWith({ date: "2026-01-06" });
  expect(events).toEqual(["ack-2026-01-05", "/api/v1/mobile/market/plan", "/api/v1/mobile/market/ingest", "ack-2026-01-06"]);
});
test("failed durable commit never acknowledges or starts another date", async () => {
  vi.mocked(apiPost).mockImplementation(async path => {
    if (path.endsWith("/ingest")) throw new Error("synthetic durable write failure");
    return plan;
  });
  await expect(acquireRange(plan, vi.fn(), () => false)).rejects.toThrow("durable write");
  expect(StockAI.acknowledgeMarket).not.toHaveBeenCalled();
  expect(StockAI.fetchMarket).toHaveBeenCalledTimes(1);
});
test.each([403, 429, 503])("HTTP %s preserves native pages and does not advance shared state", async status => {
  vi.mocked(StockAI.fetchMarket).mockResolvedValue({ date: plan.first_day, acquisitionId: "pending", status });
  await expect(acquireRange(plan, vi.fn(), () => false)).rejects.toThrow();
  expect(apiPost).not.toHaveBeenCalledWith("/api/v1/mobile/market/ingest", expect.anything());
  expect(StockAI.acknowledgeMarket).not.toHaveBeenCalled();
});
test("stop takes effect after committing current day and refresh preserves initial range", async () => {
  let stop = false;
  await acquireRange(plan, (_day, _done, _total, saved) => { if (saved) stop = true; }, () => stop);
  expect(StockAI.fetchMarket).toHaveBeenCalledTimes(1);
  expect(StockAI.acknowledgeMarket).toHaveBeenCalledTimes(1);
  vi.mocked(apiPost).mockClear();
  await acquireRange({ first_day: plan.first_day, last_day: plan.first_day }, vi.fn(), () => false, "corrections");
  expect(apiPost).not.toHaveBeenCalledWith("/api/v1/mobile/market/plan", expect.anything());
});
test("explicit fresh acquisition retires rejected pages before fetching one date", async () => {
  const events: string[] = [];
  vi.mocked(StockAI.restartMarket).mockImplementation(async () => { events.push("restart"); });
  vi.mocked(StockAI.fetchMarket).mockImplementation(async ({ date }) => { events.push("fetch"); return receipt(date); });
  await acquireRange({ first_day: plan.first_day, last_day: plan.first_day }, vi.fn(), () => false, "restart");
  expect(events).toEqual(["restart", "fetch"]);
  expect(apiPost).not.toHaveBeenCalledWith("/api/v1/mobile/market/plan", expect.anything());
});
test("simultaneous range starts are rejected before dispatch", async () => {
  let finish!: (value: Awaited<ReturnType<typeof StockAI.fetchMarket>>) => void;
  vi.mocked(StockAI.fetchMarket).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const first = acquireRange(plan, vi.fn(), () => false);
  await vi.waitFor(() => expect(StockAI.fetchMarket).toHaveBeenCalledTimes(1));
  await expect(acquireRange(plan, vi.fn(), () => false)).rejects.toThrow("取得中");
  finish(receipt(plan.first_day));
  await first;
});

const member: MembershipStatus = { date: "2026-02-03", cutoff: "2026-02-03T11:30:00+09:00",
  latest_received_at: null, available_at_cutoff: false, is_business_day: null,
  acquisitionId: null, eligible_acquisition_id: null, after_cutoff: false };
test("membership commits before acknowledging and uses only date across the native bridge", async () => {
  const events: string[] = [];
  const incoming = { ...receipt(member.date), purpose: "membership" };
  vi.mocked(apiGet).mockResolvedValue(member);
  vi.mocked(StockAI.fetchMembership).mockResolvedValue(incoming);
  vi.mocked(apiPost).mockImplementation(async () => { events.push("commit"); return member; });
  vi.mocked(StockAI.acknowledgeMembership).mockImplementation(async () => { events.push("ack"); });
  await acquireMembership();
  expect(events).toEqual(["commit", "ack"]);
  expect(StockAI.fetchMembership).toHaveBeenCalledWith({ date: member.date });
});
test("committed pre-cutoff observation is reused after cutoff and lost acknowledgment is recovered", async () => {
  vi.mocked(apiGet).mockResolvedValue({ ...member, available_at_cutoff: true, after_cutoff: true,
    acquisitionId: "saved-late-observation", eligible_acquisition_id: "saved-pre-cutoff" });
  await acquireMembership();
  expect(StockAI.acknowledgeMembership).toHaveBeenCalledWith({ date: member.date, acquisitionId: "saved-late-observation" });
  expect(StockAI.fetchMembership).not.toHaveBeenCalled();
});
test("membership persistence failure retains native pages", async () => {
  vi.mocked(apiGet).mockResolvedValue(member);
  vi.mocked(StockAI.fetchMembership).mockResolvedValue({ ...receipt(member.date), purpose: "membership" });
  vi.mocked(apiPost).mockRejectedValue(new Error("durable write failed"));
  await expect(acquireMembership()).rejects.toThrow("durable write");
  expect(StockAI.acknowledgeMembership).not.toHaveBeenCalled();
});
test("membership failure and wrong purpose cannot publish successful acquisition", async () => {
  vi.mocked(apiGet).mockResolvedValue(member);
  vi.mocked(StockAI.fetchMembership).mockResolvedValue({ ...receipt(member.date), status: 403 });
  await expect(acquireMembership()).rejects.toThrow("403");
  vi.mocked(StockAI.fetchMembership).mockResolvedValue({ ...receipt(member.date), purpose: "history" });
  await expect(acquireMembership()).rejects.toThrow("不完全");
  expect(apiPost).not.toHaveBeenCalled();
  expect(StockAI.acknowledgeMembership).not.toHaveBeenCalled();
});
