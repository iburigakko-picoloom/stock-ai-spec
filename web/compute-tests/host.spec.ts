import { expect, test } from "@playwright/test";

test("production compute entry boots offline under the native CSP and returns durable state", async ({ page, context }) => {
  await context.route("https://**", route => route.abort());
  await page.route("**/compute.html", async route => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), "Content-Security-Policy": "default-src 'none'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; worker-src 'self' blob:; connect-src 'self'; frame-src 'none'; base-uri 'none'; form-action 'none'" } });
  });
  await page.addInitScript(() => {
    const host = window as unknown as { StockAICompute: unknown; ready: boolean; replies: Record<string, unknown>; transferMetrics: { maximumChunk: number; maximumReply: number } };
    host.replies = {}; host.ready = false;
    const nextInput = new Map<string, number>();
    host.transferMetrics = { maximumChunk: 0, maximumReply: 0 };
    const states = new Map<string, { length: number; received: number; pieces: string[] }>();
    host.StockAICompute = {
      ready: () => { host.ready = true; },
      inputChunk: (id: string, index: number) => {
        const source = sessionStorage.getItem("native-test-input") ?? "";
        if (index !== (nextInput.get(id) ?? 0) || index * 256 * 1024 >= source.length) throw new Error("invalid input chunk");
        nextInput.set(id, index + 1);
        return source.slice(index * 256 * 1024, (index + 1) * 256 * 1024);
      },
      inputDone: (id: string) => (nextInput.get(id) ?? 0) === Math.ceil((sessionStorage.getItem("native-test-input") ?? "").length / (256 * 1024)),
      beginState: (id: string, length: number) => { states.set(id, { length, received: 0, pieces: [] }); return true; },
      stateChunk: (id: string, index: number, fragment: string) => {
        const transfer = states.get(id);
        if (!transfer || index !== transfer.pieces.length || fragment.length > 256 * 1024) return false;
        transfer.pieces.push(fragment); transfer.received += fragment.length;
        host.transferMetrics.maximumChunk = Math.max(host.transferMetrics.maximumChunk, fragment.length);
        return true;
      },
      complete: (id: string, payload: string) => {
        host.transferMetrics.maximumReply = Math.max(host.transferMetrics.maximumReply, payload.length);
        const reply = JSON.parse(payload);
        if (reply.state === true) {
          const transfer = states.get(id);
          if (!transfer || transfer.received !== transfer.length) throw new Error("incomplete native transfer");
          reply.state = transfer.pieces.join(""); states.delete(id);
        } else if (!reply.error && reply.state !== null) throw new Error("native reply contains a capsule");
        host.replies[id] = reply;
      },
    };
  });
  await page.goto("/compute.html");
  await expect.poll(() => page.evaluate(() => (window as unknown as { ready: boolean }).ready)).toBe(true);
  async function send(id: number, command: Record<string, unknown>): Promise<{ error?: string; state: string | null; result: { status: number; body: { orderSubmissionAvailable?: boolean; portfolio?: { holdings_status: string } } } | null }> {
    await page.evaluate(value => (window as unknown as { stockAICompute: (input: unknown) => void }).stockAICompute(value), { ...command, id });
    await expect.poll(() => page.evaluate(key => Boolean((window as unknown as { replies: Record<string, unknown> }).replies[key]), String(id)), { timeout: 120_000 }).toBe(true);
    return page.evaluate(key => (window as unknown as { replies: Record<string, never> }).replies[key], String(id));
  }
  const initialized = await send(1, { command: "initialize", state_length: 0 });
  expect(initialized.error).toBeUndefined();
  expect(initialized.state).toBeTruthy();
  const health = await send(2, { command: "request", method: "GET", path: "/api/v1/health" });
  expect(health.result).toMatchObject({ status: 200, body: { orderSubmissionAvailable: false } });
  expect(health.state).toBeNull();
  const saved = await send(3, { command: "request", method: "POST", path: "/api/v1/mobile/portfolio", body: JSON.stringify({ schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: null, maximum_drawdown_percent: null, accounts: [], holdings: [] }) });
  expect(saved.error).toBeUndefined();
  expect(saved.result).toMatchObject({ status: 200, body: { portfolio: { holdings_status: "none" } } });
  expect(saved.state).toBeTruthy();
  const invalid = await send(4, { command: "request", method: "POST", path: "/api/v1/mobile/portfolio", body: "{" });
  expect(invalid.result?.status).toBe(422);
  expect(invalid.state).toBeTruthy();
  const afterFailure = await send(5, { command: "request", method: "GET", path: "/api/v1/mobile/portfolio" });
  expect(afterFailure.result).toEqual(saved.result);
  expect(afterFailure.state).toBeNull();
  const exception = await send(6, { command: "request", method: "POST", path: "/api/v1/mobile/features", body: "null" });
  expect(exception.error).toBe("COMPUTE_WORKER_FAILED");
  const afterException = await send(7, { command: "request", method: "GET", path: "/api/v1/mobile/portfolio" });
  expect(afterException.result).toEqual(saved.result);
  expect(afterException.state).toBeNull();
  const reference = await send(20, { command: "request", method: "POST", path: "/api/v1/mobile/daily/generate", body: JSON.stringify({ reference_only: true }) });
  expect(reference.error).toBeUndefined();
  expect(reference.result).toMatchObject({ status: 200, body: { phase: "blocked", scope: { analysis_mode: "latest_available_reference" } } });
  expect(reference.state).toBeTruthy();
  const daily = await send(21, { command: "request", method: "GET", path: "/api/v1/mobile/daily" });
  expect(daily.result).toMatchObject({ status: 200, body: null });
  const metrics = await page.evaluate(() => (window as unknown as { transferMetrics: { maximumChunk: number; maximumReply: number } }).transferMetrics);
  expect(metrics.maximumChunk).toBeGreaterThan(0);
  expect(metrics.maximumChunk).toBeLessThanOrEqual(256 * 1024);
  expect(metrics.maximumReply).toBeLessThan(8192);
  await page.evaluate(payload => sessionStorage.setItem("native-test-input", payload), saved.state!);
  await page.reload();
  await expect.poll(() => page.evaluate(() => (window as unknown as { ready: boolean }).ready)).toBe(true);
  const restored = await send(8, { command: "initialize", state_length: saved.state!.length });
  expect(restored.error).toBeUndefined();
  const afterReload = await send(9, { command: "request", method: "GET", path: "/api/v1/mobile/portfolio" });
  expect(afterReload.result).toEqual(saved.result);
  const delta = await send(13, { command: "request", method: "POST", operations_only: true, path: "/api/v1/mobile/portfolio", body: JSON.stringify({ schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: null, maximum_drawdown_percent: null, accounts: [], holdings: [] }) });
  expect(delta.error).toBeUndefined();
  expect(delta.state).toBeTruthy();
  // Native startup restores the authenticated base and operations overlay separately.
  await page.evaluate(payload => sessionStorage.setItem("native-test-input", payload), initialized.state!);
  await page.reload();
  await expect.poll(() => page.evaluate(() => (window as unknown as { ready: boolean }).ready)).toBe(true);
  const base = await send(10, { command: "initialize", optimized_startup: true, defer_initialize: true, state_length: initialized.state!.length });
  expect(base.error).toBeUndefined();
  expect(base.result).toEqual({ persistence: "deferred" });
  expect(base.state).toBeNull();
  await page.evaluate(payload => sessionStorage.setItem("native-test-input", payload), delta.state!);
  const overlay = await send(11, { command: "initialize_operations", optimized_startup: true, state_length: delta.state!.length });
  expect(overlay.error).toBeUndefined();
  expect(overlay.result).toEqual({ persistence: "none" });
  expect(overlay.state).toBeNull();
  expect((await send(12, { command: "request", method: "GET", path: "/api/v1/mobile/portfolio" })).result).toEqual(saved.result);
});

for (const failure of ["none", "input-short", "input-auth", "input-nonascii", "input-oversize", "output-rejected", "output-legacy-string", "output-order", "output-early-complete", "output-nonascii"] as const) {
  test(`native transfer keeps large capsules outside command/reply JSON: ${failure}`, async ({ page }) => {
    await page.addInitScript(({ failure }) => {
      const host = window as unknown as { StockAICompute: unknown; ready: boolean; reply?: Record<string, unknown>; received?: string; output?: string; maximumChunk: number; replyLength: number; inputFinished: boolean; inputReads: number; transferred?: boolean; Worker: unknown };
      const chunk = 256 * 1024;
      const source = "a".repeat(chunk - 7) + "b".repeat(chunk) + "c".repeat(30);
      const pieces = [source.slice(0, chunk - 7), source.slice(chunk - 7, 2 * chunk - 7), source.slice(2 * chunk - 7)];
      const output: string[] = [];
      host.ready = false; host.maximumChunk = 0; host.inputFinished = false; host.inputReads = 0;
      host.StockAICompute = {
        ready: () => { host.ready = true; },
        inputChunk: (_id: string, index: number) => {
          host.inputReads++;
          return failure === "input-short" && index === 2 ? "" : failure === "input-nonascii" && index === 0 ? "あ".repeat(pieces[0].length) : pieces[index];
        },
        inputDone: () => { host.inputFinished = failure !== "input-auth"; return host.inputFinished; },
        beginState: (_id: string, length: number) => length === source.length && host.inputFinished,
        stateChunk: (_id: string, index: number, fragment: string) => {
          host.maximumChunk = Math.max(host.maximumChunk, fragment.length);
          if (index !== output.length || fragment.length > chunk || failure === "output-rejected" && index === 1) return false;
          output.push(fragment); return true;
        },
        complete: (_id: string, payload: string) => { host.replyLength = payload.length; host.reply = JSON.parse(payload); host.output = output.join(""); },
      };
      host.Worker = class {
        onmessage?: (event: { data: unknown }) => void;
        private next = 0;
        private respond(data: unknown) { queueMicrotask(() => this.onmessage?.({ data })); }
        postMessage(input: { id: number; command: string; index?: number; ok?: boolean; state?: string; state_bytes: ArrayBuffer }, transfer: Transferable[] = []) {
          if (input.command === "state_ack") {
            if (!input.ok) return;
            if (input.index !== this.next - 1) throw new Error("chunk sent before native ACK");
            if (input.index !== -1 && output.length !== this.next) throw new Error("ACK before native persistence");
            if (failure === "output-early-complete") { this.respond({ id: input.id, state: true }); return; }
            const offset = this.next * chunk;
            if (offset >= source.length) {
              this.respond({ id: input.id, result: { status: 200, body: {} }, state: true }); return;
            }
            const fragment = source.slice(offset, offset + chunk);
            const index = this.next++;
            this.respond({ id: input.id, state_chunk: failure === "output-nonascii" ? "あ".repeat(fragment.length) : fragment, index: failure === "output-order" ? index + 1 : index }); return;
          }
          host.transferred = transfer.length === 1 && transfer[0] === input.state_bytes && input.state === undefined;
          const received = structuredClone(input, { transfer });
          host.transferred = host.transferred && input.state_bytes.byteLength === 0;
          host.received = new TextDecoder().decode(received.state_bytes);
          if (failure === "output-legacy-string") this.respond({ id: input.id, result: { status: 200, body: {} }, state: source });
          else this.respond({ id: input.id, state_begin: source.length });
        }
      };
    }, { failure });
    await page.goto("/compute.html");
    await expect.poll(() => page.evaluate(() => (window as unknown as { ready: boolean }).ready)).toBe(true);
    await page.evaluate(failure => {
      // Native evaluateJavascript dispatches without awaiting the JS return.
      // Completion is the authenticated bridge reply checked below.
      (window as unknown as { stockAICompute: (input: unknown) => void }).stockAICompute({ id: 1, command: "initialize", state_length: failure === "input-oversize" ? 256 * 1024 * 1024 + 1 : 2 * 256 * 1024 + 23 });
    }, failure);
    await expect.poll(() => page.evaluate(() => Boolean((window as unknown as { reply?: unknown }).reply))).toBe(true);
    const actual = await page.evaluate(() => {
      const host = window as unknown as { reply: Record<string, unknown>; received?: string; output: string; maximumChunk: number; replyLength: number; inputFinished: boolean; inputReads: number; transferred?: boolean };
      return { ...host.reply, receivedLength: host.received?.length, outputLength: host.output.length, exact: host.output === host.received, maximumChunk: host.maximumChunk, replyLength: host.replyLength, inputFinished: host.inputFinished, inputReads: host.inputReads, transferred: host.transferred };
    });
    expect(actual.replyLength).toBeLessThan(1024);
    expect(actual.maximumChunk).toBeLessThanOrEqual(256 * 1024);
    if (failure === "none") {
      expect(actual).toMatchObject({ state: true, exact: true, receivedLength: 2 * 256 * 1024 + 23, inputFinished: true, transferred: true });
    } else {
      expect(actual).toMatchObject({ error: "COMPUTE_WORKER_FAILED", code: "state_other" });
      expect(actual).not.toHaveProperty("state");
      if (failure.startsWith("input")) expect(actual.receivedLength).toBeUndefined();
      if (failure === "input-oversize") expect(actual.inputReads).toBe(0);
    }
  });
}
