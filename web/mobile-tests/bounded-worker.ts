/// <reference lib="webworker" />
// Synthetic browser test entry; never imported or packaged by the app build.
self.onmessage = async (event: MessageEvent<Record<string, unknown>>) => {
  try {
    const url = new URL("/python/pyodide.mjs", self.location.origin).href;
    const { loadPyodide } = await import(/* @vite-ignore */ url);
    const python = await loadPyodide({ indexURL: "/python/" });
    await python.loadPackage(["pydantic", "tzdata"]);
    python.unpackArchive(new Uint8Array(await (await fetch("/python/stock_ai.zip")).arrayBuffer()), "zip", { extractDir: "/stockai-code" });
    python.globals.set("fixture_json", JSON.stringify(event.data));
    await python.runPythonAsync(`
import sys, json
sys.path.insert(0, '/stockai-code')
from datetime import datetime
from stock_ai.domain import PortfolioState
from stock_ai.decision.engine import DailyPortfolioDecisionEngine, DecisionCandidate, DecisionEngineConfig
from stock_ai.decision.costs import CostPolicy, TransactionCostEngine
from stock_ai.decision.tax import SimpleJapanTaxEngine, TaxPolicy
fixture = json.loads(fixture_json)
assert fixture['synthetic_only'] is True
engine = DailyPortfolioDecisionEngine(
    config=DecisionEngineConfig.model_validate(fixture['config']),
    cost_engine=TransactionCostEngine(CostPolicy.model_validate(fixture['cost_policy'])),
    tax_engine=SimpleJapanTaxEngine(TaxPolicy.model_validate(fixture['tax_policy'])),
)
portfolio = PortfolioState.model_validate(fixture['portfolio'])
candidates = tuple(DecisionCandidate.model_validate(x) for x in fixture['candidates'])
`);
    const started = performance.now();
    const result = JSON.parse(String(await python.runPythonAsync(`
result = engine.propose(portfolio=portfolio, candidates=candidates,
    generated_at=datetime.fromisoformat(fixture['generated_at']),
    model_bundle_version=fixture['model_bundle_version'])
json.dumps(result.model_dump(mode='json'))
`)));
    self.postMessage({ result, elapsed_ms: performance.now() - started });
  } catch (error) { self.postMessage({ error: String(error) }); }
};
