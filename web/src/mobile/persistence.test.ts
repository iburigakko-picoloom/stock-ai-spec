import { expect, test } from "vitest";
import { operationsOnly, requiresPersistence } from "./persistence";

test.each([
  "/api/v1/stocks/7203/note", "/api/v1/mobile/personal/current/preview",
  "/api/v1/mobile/personal/current/confirm", "/api/v1/decisions/d/executions", "/api/v1/portfolio/apply-executions",
  "/api/v1/proposals/p/decisions", "/api/v1/imports/executions/preview",
  "/api/v1/imports/positions/preview", "/api/v1/imports/executions/p/confirm",
  "/api/v1/imports/positions/p/confirm",
])("ledger mutation %s persists operations, never the market archive", path => {
  expect(operationsOnly("POST", path)).toBe(true);
  expect(requiresPersistence("POST", path)).toBe(true);
  expect(operationsOnly("GET", path)).toBe(false);
});

test("only the audited read-only review avoids a POST commit; unknown routes fail safe", () => {
  expect(requiresPersistence("POST", "/api/v1/proposals/p/review")).toBe(false);
  for (const path of ["/api/v1/mobile/market/ingest", "/api/v1/new-route", "/api/v1/proposals/p/review?other=1"]) {
    expect(requiresPersistence("POST", path)).toBe(true);
    expect(operationsOnly("POST", path)).toBe(false);
  }
});
