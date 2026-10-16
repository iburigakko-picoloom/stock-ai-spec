import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiPost } from "../api";
import { ChatGPT, type ResearchRunView } from "./chatgpt";
import { runResearch } from "./research";

vi.mock("../api", () => ({ apiPost: vi.fn() }));
vi.mock("./chatgpt", () => ({ ChatGPT: { respond: vi.fn(), recoverExecution: vi.fn(), forgetExecution: vi.fn() } }));
afterEach(() => { vi.resetAllMocks(); });
beforeEach(() => { vi.mocked(ChatGPT.forgetExecution).mockResolvedValue(); });
const configuration = { model: "synthetic-model", effort: "high" as const, prompt_version: "v1" };
const base: ResearchRunView = {
  run: { run_id: "run", context: { prediction_snapshot_id: "snapshot", symbol: "A", company_name: "試験会社",
    numerical_as_of: "2026-10-16T11:30:00+09:00", research_as_of: "2026-10-16T11:35:00+09:00", configuration, revision: 1 } },
  passes: [], attempts: [], record: null,
};
const firstAttempt = { attempt_id: "a".repeat(32), run_id: "run", phase: "independent" as const, status: "running" as const,
  started_at: "2026-10-16T11:36:00+09:00", finished_at: null, pass_id: null, error_code: null };
const secondAttempt = { ...firstAttempt, attempt_id: "b".repeat(32), phase: "comparison" as const };
const output = (attemptId: string) => ({ attemptId, state: "completed" as const, startedAt: "2026-10-16T11:36:00+09:00",
  completedAt: "2026-10-16T11:37:00+09:00", response: { id: "provider", status: "completed" } });
const firstSaved = { ...base, attempts: [{ ...firstAttempt, status: "completed" as const, pass_id: "first" }] };
const pass = { pass_id: "first", context: base.run.context, phase: "independent" as const, served_model: configuration.model,
  started_at: firstAttempt.started_at, completed_at: output("").completedAt, text: "独立した見解", searched: true,
  sources: [{ url: "https://example.com/ir", title: "IR", published_at: null }] };
const done: ResearchRunView = { ...base, attempts: [firstSaved.attempts[0], { ...secondAttempt, status: "completed", pass_id: "second" }],
  passes: [pass, { ...pass, phase: "comparison" }],
  record: { research_id: "record", context: base.run.context, independent: pass, comparison: { ...pass, phase: "comparison" }, affects_numerical_proposal: false } };

test("each phase commits before the next request and repeated callers share one execution", async () => {
  const calls: string[] = [];
  let claims = 0;
  vi.mocked(apiPost).mockImplementation(async (path) => {
    calls.push(path);
    if (path.endsWith("/claim")) return { ...base, state: "ready", attempt: ++claims === 1 ? firstAttempt : secondAttempt,
      request_json: "provider-input", request_sha256: "digest" };
    return path.includes(firstAttempt.attempt_id) ? firstSaved : done;
  });
  vi.mocked(ChatGPT.respond).mockImplementation(async ({ attemptId }) => output(attemptId));
  const first = runResearch("run");
  expect(runResearch("run")).toBe(first);
  expect(await first).toEqual(done);
  expect(ChatGPT.respond).toHaveBeenCalledTimes(2);
  expect(calls).toEqual(["/api/v1/research/run/claim", `/api/v1/research/${firstAttempt.attempt_id}/receipt`,
    "/api/v1/research/run/claim", `/api/v1/research/${secondAttempt.attempt_id}/receipt`]);
  expect(ChatGPT.forgetExecution).toHaveBeenCalledTimes(2);
});

test("a completed native execution is recovered without issuing another provider call", async () => {
  vi.mocked(apiPost).mockImplementation(async path => path.endsWith("/claim")
    ? { ...base, state: "running", attempt: secondAttempt } : done);
  vi.mocked(ChatGPT.recoverExecution).mockResolvedValue(output(secondAttempt.attempt_id));
  expect(await runResearch("recover")).toEqual(done);
  expect(ChatGPT.respond).not.toHaveBeenCalled();
});

test("an observation failure leaves the pending attempt intact", async () => {
  vi.mocked(apiPost).mockResolvedValue({ ...base, state: "running", attempt: firstAttempt });
  vi.mocked(ChatGPT.recoverExecution).mockRejectedValue(new Error("native observation unavailable"));
  await expect(runResearch("unknown")).rejects.toThrow("observation unavailable");
  expect(apiPost).toHaveBeenCalledTimes(1);
  expect(ChatGPT.respond).not.toHaveBeenCalled();
});

test("bridge rejection recovers the specific execution before saving a terminal outcome", async () => {
  vi.mocked(apiPost).mockImplementation(async path => path.endsWith("/claim")
    ? { ...base, state: "ready", attempt: secondAttempt, request_json: "input", request_sha256: "digest" } : done);
  vi.mocked(ChatGPT.respond).mockRejectedValue(new Error("bridge closed"));
  vi.mocked(ChatGPT.recoverExecution).mockResolvedValue(output(secondAttempt.attempt_id));
  expect(await runResearch("bridge")).toEqual(done);
  expect(ChatGPT.respond).toHaveBeenCalledTimes(1);
  expect(ChatGPT.recoverExecution).toHaveBeenCalledWith({ attemptId: secondAttempt.attempt_id });
});

test("provider limits are recorded and never trigger paid or alternate-model inference", async () => {
  vi.mocked(apiPost).mockImplementation(async path => path.endsWith("/claim")
    ? { ...base, state: "running", attempt: firstAttempt }
    : { ...base, attempts: [{ ...firstAttempt, status: "failed", error_code: "subscription_sharing_usage_limit_exceeded" }] });
  vi.mocked(ChatGPT.recoverExecution).mockResolvedValue({ attemptId: firstAttempt.attempt_id, state: "failed", errorCode: "subscription_sharing_usage_limit_exceeded" });
  await expect(runResearch("limited")).rejects.toThrow("利用上限");
  expect(apiPost).toHaveBeenLastCalledWith(`/api/v1/research/${firstAttempt.attempt_id}/receipt`, {
    error_code: "subscription_sharing_usage_limit_exceeded", interrupted: false,
  });
  expect(ChatGPT.respond).not.toHaveBeenCalled();
});

test("failed ledger persistence retains the native response for a later recovery", async () => {
  vi.mocked(apiPost).mockImplementation(async path => {
    if (path.endsWith("/claim")) return { ...base, state: "running", attempt: secondAttempt };
    throw new Error("durable write failed");
  });
  vi.mocked(ChatGPT.recoverExecution).mockResolvedValue(output(secondAttempt.attempt_id));
  await expect(runResearch("storage")).rejects.toThrow("durable write failed");
  expect(ChatGPT.forgetExecution).not.toHaveBeenCalled();
  expect(ChatGPT.respond).not.toHaveBeenCalled();
});

test("a still-running native request stays pending and is not marked failed", async () => {
  vi.mocked(apiPost).mockResolvedValue({ ...base, state: "running", attempt: firstAttempt });
  vi.mocked(ChatGPT.recoverExecution).mockResolvedValue({ attemptId: firstAttempt.attempt_id, state: "running" });
  await expect(runResearch("running")).rejects.toThrow("実行中");
  expect(apiPost).toHaveBeenCalledTimes(1);
});
