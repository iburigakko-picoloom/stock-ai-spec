import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import process from "node:process";

interface Golden {
  synthetic_only: boolean; no_market_data: boolean; no_private_models: boolean;
  fitted_models: number; owner_approval_created: boolean;
  rows: Record<string, Record<string, unknown>[]>;
  rank_universes: Record<string, { decision_symbols: string[] }>;
  variants: {
    name: string; content: string; expected: Record<string, unknown>;
    snapshot: { snapshot_id: string; predictions: Record<string, unknown>[] };
    research_symbols: string[]; ranking_symbols: string[];
  }[];
}
interface Reply {
  error?: string; state: string | null;
  result: { status: number; body: Record<string, unknown> | Record<string, unknown>[] } | null;
}
const fixture = JSON.parse(readFileSync(process.env.STOCKAI_ENSEMBLE_GOLDEN ??
  new URL("../../.demo-artifacts/android/research-ensemble-golden-v2.json", import.meta.url), "utf8")) as Golden;
const nativeHostSource = readFileSync(new URL(
  "../android/app/src/main/java/jp/stockai/app/ComputeHost.java", import.meta.url), "utf8");
const nativeCsp = nativeHostSource.match(/headers\.put\("Content-Security-Policy", "([^"]+)"\);/)?.[1];
if (!nativeCsp) throw new Error("Native compute CSP must be present in ComputeHost.asset()");
const nativeHostSha256 = createHash("sha256").update(nativeHostSource).digest("hex");

for (const variant of fixture.variants) {
  test(`bundled WASM matches PC research ensemble, complete ranks and restored snapshot: ${variant.name}`, async ({ page, context }) => {
    test.setTimeout(180_000);
    expect(fixture).toMatchObject({ synthetic_only: true, no_market_data: true,
      no_private_models: true, fitted_models: 0, owner_approval_created: false });
    page.on("console", message => console.log(`WASM console: ${message.text()}`));
    page.on("pageerror", error => console.log(`WASM page error: ${error.message}`));
    await context.route("https://**", route => route.abort());
    // ComputeHost.java asset():76 sets this exact native CSP on all local
    // responses; ServiceWorkerClient:100 and WebViewClient:104 use asset().
    // Match that policy on the entry and worker, whose response defines its
    // WASM execution policy, instead of the ASGI fixture server's web UI CSP.
    await page.route(/\/(compute\.html|assets\/compute-worker-[^/]+\.js)$/, async route => {
      const response = await route.fetch();
      await route.fulfill({ response, headers: { ...response.headers(),
        "Content-Security-Policy": nativeCsp } });
    });
    await page.addInitScript(() => {
      const host = window as unknown as {
        StockAICompute: unknown; ready: boolean; replies: Record<string, unknown>;
        maximumChunk: number;
      };
      host.ready = false; host.replies = {}; host.maximumChunk = 0;
      const source = sessionStorage.getItem("SYNTHETIC-ensemble-state") ?? "";
      let nextInput = 0;
      const states = new Map<string, { length: number; received: number; pieces: string[] }>();
      host.StockAICompute = {
        ready: () => { host.ready = true; },
        progress: (id: string, phase: string) => console.log(`Native progress ${id}: ${phase}`),
        inputChunk: (_id: string, index: number) => {
          if (index !== nextInput++) throw new Error("Invalid synthetic state chunk order");
          return source.slice(index * 256 * 1024, (index + 1) * 256 * 1024);
        },
        inputDone: () => nextInput === Math.ceil(source.length / (256 * 1024)),
        beginState: (id: string, length: number) => {
          states.set(id, { length, received: 0, pieces: [] }); return true;
        },
        stateChunk: (id: string, index: number, fragment: string) => {
          const transfer = states.get(id);
          if (!transfer || index !== transfer.pieces.length || fragment.length > 256 * 1024) return false;
          transfer.pieces.push(fragment); transfer.received += fragment.length;
          host.maximumChunk = Math.max(host.maximumChunk, fragment.length); return true;
        },
        complete: (id: string, payload: string) => {
          const reply = JSON.parse(payload);
          if (reply.state === true) {
            const transfer = states.get(id);
            if (!transfer || transfer.received !== transfer.length) throw new Error("Incomplete synthetic state");
            reply.state = transfer.pieces.join(""); states.delete(id);
          }
          host.replies[id] = reply;
        },
      };
    });
    await page.goto("/compute.html");
    await expect.poll(() => page.evaluate(() => (window as unknown as { ready: boolean }).ready)).toBe(true);
    let sequence = 0;
    async function send(command: Record<string, unknown>): Promise<Reply> {
      const id = ++sequence;
      await page.evaluate(value => (window as unknown as {
        stockAICompute: (input: unknown) => void;
      }).stockAICompute(value), { ...command, id });
      await expect.poll(() => page.evaluate(key => Boolean((window as unknown as {
        replies: Record<string, unknown>;
      }).replies[key]), String(id)), { timeout: 120_000 }).toBe(true);
      const response = await page.evaluate(key => (window as unknown as {
        replies: Record<string, Reply>;
      }).replies[key], String(id));
      expect(response.error).toBeUndefined();
      return response;
    }
    const request = (method: string, path: string, body?: unknown) => send({
      command: "request", method, path, ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    await send({ command: "initialize", state_length: 0 });
    const originalHome = await request("GET", "/api/v1/home");
    const originalModel = await request("GET", "/api/v1/mobile/models");
    const parityInput = { content: variant.content, rows: fixture.rows,
      rank_universes: fixture.rank_universes };
    const calculated = await request("POST", "/api/v1/mobile/models/bundle/parity", parityInput);
    expect(calculated.result).toEqual({ status: 200, body: variant.expected });
    expect(calculated.result?.body).toMatchObject({ persisted: false, research_only: true, model_adopted: false });
    const reversed = Object.fromEntries(Object.entries(fixture.rows).map(([horizon, rows]) => [horizon, [...rows].reverse()]));
    const reordered = await request("POST", "/api/v1/mobile/models/bundle/parity", { ...parityInput, rows: reversed });
    expect(reordered.result).toEqual(calculated.result);
    const partial = Object.fromEntries(Object.entries(fixture.rows).map(([horizon, rows]) => [horizon, rows.slice(1)]));
    expect((await request("POST", "/api/v1/mobile/models/bundle/parity", { ...parityInput, rows: partial })).result?.status).toBe(422);
    expect((await request("GET", "/api/v1/mobile/models")).result).toEqual(originalModel.result);
    expect((await request("GET", "/api/v1/home")).result).toEqual(originalHome.result);

    // Save only the declared unadopted synthetic snapshot through the existing
    // manual import. No policy pins, models, holdings or executions are created.
    const snapshotText = JSON.stringify(variant.snapshot);
    const preview = await request("POST", "/api/v1/daily/import/preview", { json_text: snapshotText });
    expect(preview.result?.status).toBe(200);
    const previewBody = preview.result?.body as { confirmation_hash: string; writes_performed: boolean };
    expect(previewBody.writes_performed).toBe(false);
    const saved = await request("POST", "/api/v1/daily/import/confirm", {
      json_text: snapshotText, confirmation_hash: previewBody.confirmation_hash,
    });
    expect(saved.result).toMatchObject({ status: 200, body: { record: variant.snapshot } });
    expect(saved.state).toBeTruthy();
    const latest = await request("GET", "/api/v1/daily/latest");
    expect(latest.result).toMatchObject({ status: 200, body: {
      snapshot: variant.snapshot, research_symbols: variant.research_symbols,
    } });
    const ranking = await request("GET", "/api/v1/ranking?rankType=overall&limit=50");
    const ranked = ranking.result?.body as { symbol: string; total_universe: number; portfolio_action: unknown }[];
    expect(ranked.map(row => row.symbol)).toEqual(variant.ranking_symbols);
    expect(ranked.every(row => row.total_universe === 27 && row.portfolio_action === null)).toBe(true);
    expect(variant.research_symbols).toHaveLength(22);
    expect(variant.research_symbols.slice(20)).toEqual(["1000", "1001"]);
    for (const prediction of variant.snapshot.predictions) {
      expect(prediction.downside_quantile).toBeNull();
      expect(prediction.large_loss_probability).toBeNull();
      expect(prediction.uncertainty).toBeNull();
      if (variant.name === "rank_only") expect(prediction.expected_return_20d).toBeNull();
    }
    expect((await request("GET", "/api/v1/home")).result).toEqual(originalHome.result);
    await page.evaluate(state => sessionStorage.setItem("SYNTHETIC-ensemble-state", state), saved.state!);
    await page.reload();
    await expect.poll(() => page.evaluate(() => (window as unknown as { ready: boolean }).ready)).toBe(true);
    await send({ command: "initialize", state_length: saved.state!.length });
    expect((await request("GET", "/api/v1/daily/latest")).result).toEqual(latest.result);
    expect((await request("GET", "/api/v1/ranking?rankType=overall&limit=50")).result).toEqual(ranking.result);
    expect((await request("POST", "/api/v1/mobile/models/bundle/parity", parityInput)).result).toEqual(calculated.result);
    expect((await request("GET", "/api/v1/mobile/models")).result).toEqual(originalModel.result);
    expect((await request("GET", "/api/v1/home")).result).toEqual(originalHome.result);
    const maximumChunk = await page.evaluate(() => (window as unknown as { maximumChunk: number }).maximumChunk);
    expect(maximumChunk).toBeGreaterThan(0);
    expect(maximumChunk).toBeLessThanOrEqual(256 * 1024);
    await test.info().attach("synthetic-pc-wasm-ensemble.json", {
      contentType: "application/json",
      body: JSON.stringify({ synthetic_only: true, actual_android_device: false,
        runtime: "bundled Pyodide WASM through production compute host",
        variant: variant.name, bundle_sha256: variant.expected.sha256,
        native_csp: nativeCsp, native_host_sha256: nativeHostSha256,
        symbols_per_horizon: 27, raw_component_predictions: 216,
        exact_pc_match: true, maximum_absolute_error: 0,
        reordered_inputs_equal: true, partial_population_rejected: true,
        top20_plus_all_holdings: variant.research_symbols,
        snapshot_restored_exactly: true, optional_risk_null: true,
        model_policy_unchanged: true, personal_state_unchanged: true,
        model_adopted: false, maximum_native_state_chunk: maximumChunk,
      }, null, 2),
    });
  });
}
