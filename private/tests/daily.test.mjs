import test from "node:test";
import assert from "node:assert/strict";
import { cloudPayload, validateSync, sha256 } from "../lib/daily.ts";

const readiness = {
  schema_version: "daily-cloud-v1", kind: "readiness", source_snapshot_id: null,
  as_of: "2026-10-15T01:00:00+09:00", generated_at: "2026-10-15T01:00:00+09:00",
  data_as_of: null, mode: "research", model_version: null, feature_version: null,
  unit: "fractional_return", risk_horizon: 20, price_semantics: "daily_close_research_proxy",
  label_definition: "next_session_adjusted_close_to_h_sessions_later",
  large_loss_threshold: null, downside_quantile_alpha: null, adoption_review_id: null,
  training_completed: 18, training_total: 18, blockers: ["未評価"], forecasts: [], research: [],
};
const forecast = { symbol: "fixture", holding: false, expected_return_1d: null,
  expected_return_5d: .01, expected_return_20d: .02, downside_quantile: -.05,
  large_loss_probability: .1, uncertainty: .02 };
const prediction = { ...readiness, kind: "predictions", source_snapshot_id: "a".repeat(64),
  data_as_of: "2026-10-14T16:00:00+09:00", model_version: "test", feature_version: "test",
  large_loss_threshold: -.1, downside_quantile_alpha: .1,
  forecasts: [forecast] };

test("original JSON bytes are authenticated and survive unchanged", async () => {
  const payload_json = JSON.stringify(readiness);
  const snapshot_id = await sha256(payload_json);
  const result = await validateSync({ payload_json, snapshot_id });
  assert.equal(result.request.payload_json, payload_json);
  await assert.rejects(validateSync({ payload_json: payload_json + " ", snapshot_id }));
});
test("reject unknown fields, invented 1d and incomplete provenance", () => {
  assert.equal(cloudPayload.parse(prediction).forecasts[0].expected_return_1d, null);
  assert.throws(() => cloudPayload.parse({ ...readiness, api_key: "do-not-send" }));
  assert.throws(() => cloudPayload.parse({ ...prediction, source_snapshot_id: null }));
  assert.throws(() => cloudPayload.parse({ ...prediction, large_loss_threshold: null }));
  assert.throws(() => cloudPayload.parse({ ...prediction, mode: "owner_approved" }));
  assert.throws(() => cloudPayload.parse({ ...prediction, forecasts: [{ ...forecast, expected_return_1d: 0 }] }));
  assert.throws(() => cloudPayload.parse({ ...readiness, forecasts: [forecast] }));
});
test("bounded universe preserves holdings without duplicate symbols", () => {
  assert.throws(() => cloudPayload.parse({ ...prediction, forecasts: [forecast, forecast] }));
  const many = Array.from({ length: 21 }, (_, i) => ({ ...forecast, symbol: `fixture-${i}` }));
  assert.throws(() => cloudPayload.parse({ ...prediction, forecasts: many }));
  many[20].holding = true;
  assert.equal(cloudPayload.parse({ ...prediction, forecasts: many }).forecasts.length, 21);
});
test("future data and invalid probability fail closed", () => {
  assert.throws(() => cloudPayload.parse({ ...prediction, data_as_of: "2026-10-16T00:00:00Z" }));
  assert.throws(() => cloudPayload.parse({ ...prediction, forecasts: [{ ...forecast, large_loss_probability: 1.5 }] }));
});
