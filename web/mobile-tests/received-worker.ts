/// <reference lib="webworker" />
// Received-history integration with synthetic configuration; never an APK entry.
self.onmessage = async (event: MessageEvent<Record<string, unknown>>) => {
  try {
    const url = new URL("/python/pyodide.mjs", self.location.origin).href;
    const { loadPyodide } = await import(/* @vite-ignore */ url);
    const python = await loadPyodide({ indexURL: "/python/" });
    await python.loadPackage(["numpy", "pandas", "pydantic", "sqlite3", "tzdata", "fastapi", "httpx"]);
    python.unpackArchive(new Uint8Array(await (await fetch("/python/stock_ai.zip")).arrayBuffer()), "zip", { extractDir: "/stockai-code" });
    python.globals.set("fixture_json", JSON.stringify(event.data));
    const output = JSON.parse(String(await python.runPythonAsync(`
import sys, json, types, math
from datetime import datetime, timedelta
sys.path.insert(0, '/stockai-code')
from stock_ai.mobile import runtime, models, forecasts, decisions, market
fixture = json.loads(fixture_json)
assert fixture['synthetic_only'] is True
return_only = fixture.get('return_only_research', False)
# Supply model/selection configuration and time only. No market/universe,
# features, predictions, cost calculation or validation doubles.
models.policy = lambda: fixture['policy']
models.bundled_selection = lambda: fixture['selection']
forecasts.bundled_selection = lambda: fixture['selection']
now = datetime.fromisoformat(fixture['now'])
class FixtureClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return now if tz is None else now.astimezone(tz)
runtime.datetime = FixtureClock
runtime.initialize(fixture['state'])
path, store = runtime.STATE / 'mobile.sqlite3', runtime._app.state.store
ledger = store.latest_portfolio()
assert store.latest_prediction_snapshot() is None
assert forecasts.latest(path) is None and decisions.latest(path) is None
numerical = await runtime.request('POST', '/api/v1/mobile/daily/generate', 'null')
assert numerical['status'] == 200, numerical
numerical = numerical['body']
assert numerical['phase'] == 'published', numerical['blocking_reasons']
snapshot = store.latest_prediction_snapshot()
assert len(snapshot.predictions) == len(snapshot.candidate_symbols) == 24
assert snapshot.holding_symbols == ('1023',)
assert snapshot.mode == 'research' and snapshot.adoption_review_id is None
assert not models.status(path, store)['model_adopted']
assert len(numerical['data_proof']['source_snapshot_ids']) == 5
assert numerical['data_proof'] == fixture['wasm_data_proof']
assert snapshot.data_snapshot_id == fixture['wasm_data_snapshot_id']
assert numerical['scope']['universe']['membership_verified']
assert snapshot.data_as_of < snapshot.as_of == datetime.fromisoformat(fixture['cutoff'])
daily = market.feature_inputs(path, now, True)['daily'].sort_values(['symbol', 'trading_date'])
assert len(daily) == 24*270
expected_loss = {}
for symbol, frame in daily.groupby('symbol'):
    prices = frame.close.to_numpy()
    expected_loss[symbol] = 1/(1+math.exp(2 if prices[-1]/prices[-6]-1 < 0 else 3))
assert len(set(expected_loss.values())) == 2
for prediction in snapshot.predictions:
    assert prediction.expected_return_5d == .01 and prediction.expected_return_20d == .04
    if return_only:
        assert prediction.schema_version == 3 and prediction.uncertainty is None
        assert prediction.large_loss_probability is None and prediction.downside_quantile is None
    else:
        assert math.isclose(prediction.large_loss_probability, expected_loss[prediction.symbol],
                            rel_tol=1e-6, abs_tol=1e-7)
comparison_reply = await runtime.request('POST', '/api/v1/mobile/decision/generate', 'null')
assert comparison_reply['status'] == 200, comparison_reply
comparison = decisions.latest(path, store)
proposal = comparison['comparison']['proposal']
if return_only:
    assert comparison['phase'] == 'blocked' and proposal is None
    assert comparison['blocking_reasons'] == ['FORECAST_RISK_UNAVAILABLE']
else:
    assert comparison['phase'] == 'published', comparison['blocking_reasons']
    assert proposal['is_research_only'] and not proposal['is_order_instruction']
    assert any(x['share_difference'] and sum(float(x['transaction_cost'][field])
               for field in ('commission', 'spread', 'slippage', 'market_impact')) > 0
               for x in proposal['lines']), 'nonzero trade costs must be exercised'
exported_reply = await runtime.request('POST', '/api/v1/mobile/chatgpt-manual/export',
                                      json.dumps(fixture['permission']))
assert exported_reply['status'] == 200, exported_reply
exported = exported_reply['body']
package = json.loads(exported['prompt'].split('\\n入力:\\n')[1])
targets = package['required_targets']
assert len(targets) == 21 and any(x['symbol'] == '1023' for x in targets)
proposed_shares = (fixture['target_shares'] if return_only else
                   {x['symbol']:x['recommended_shares'] for x in proposal['lines']})
answer = dict(schema_version='chatgpt-target-shares-v1',
              input_snapshot_id=package['input_snapshot_id'], evidence_as_of=now.isoformat(),
              targets=[dict(symbol=x['symbol'], account=x['account'],
                            target_shares=proposed_shares[x['symbol']], reason='合成試験の目標株数検証',
                            sources=[]) for x in targets], unknowns=['合成データのみ'])
answer_body = {'input_record_id':exported['input_record_id'],
               'answer_json':json.dumps(answer, ensure_ascii=False)}
invalid = {**answer, 'input_snapshot_id':'0'*64}
rejected = await runtime.request('POST', '/api/v1/mobile/chatgpt-manual/answer',
                                json.dumps({**answer_body, 'answer_json':json.dumps(invalid)}))
assert rejected['status'] == 422, rejected
accepted = await runtime.request('POST', '/api/v1/mobile/chatgpt-manual/answer', json.dumps(answer_body))
assert accepted['status'] == 200, accepted
assert not accepted['body']['review']['applied_to_ledger']
assert float(accepted['body']['review']['estimated_cost_yen']) > 0
assert any(x['share_difference'] for x in accepted['body']['review']['lines'])
assert ledger == store.latest_portfolio() and snapshot == store.latest_prediction_snapshot()
assert not store.executions()
store.verify_integrity()
# Use the same dependency-free typed-cell/schema proof as native controllers.
# The fixture was exported before prediction, so its technical cursor already
# exists. No table changes at all are allowed during export/restore.
evidence = types.ModuleType('synthetic_sqlite_evidence')
exec(fixture['sqlite_evidence_source'], evidence.__dict__)
reference = {name:evidence.table_snapshot(runtime.STATE/name)
             for name in ('operations.sqlite3', 'mobile.sqlite3')}
capsule = runtime.export_state()
assert reference == {name:evidence.table_snapshot(runtime.STATE/name) for name in reference}
runtime.initialize(capsule)
store = runtime._app.state.store
assert reference == {name:evidence.table_snapshot(runtime.STATE/name) for name in reference}
assert ledger == store.latest_portfolio() and snapshot == store.latest_prediction_snapshot()
assert forecasts.latest(path) == numerical and decisions.latest(path, store) == comparison
assert not store.executions()
now += timedelta(seconds=1)
duplicate = await runtime.request('POST', '/api/v1/mobile/chatgpt-manual/answer', json.dumps(answer_body))
assert duplicate == accepted
status = await runtime.request('GET', '/api/v1/mobile/chatgpt-manual/status', 'null')
assert status['status'] == 200 and status['body']['answers'] == [accepted['body']['review']]
assert reference == {name:evidence.table_snapshot(runtime.STATE/name) for name in reference}
store.verify_integrity()
json.dumps({'predictions':numerical['snapshot']['predictions'], 'proposal':proposal,
            'daily_rows':len(daily), 'target_pairs':len(targets), 'risk_groups':len(set(expected_loss.values())),
            'restored_exact':True, 'ledger_unchanged':True, 'executions':0,
            'rejected_status':rejected['status'], 'answer_count':len(status['body']['answers']),
            'table_counts':{name:len(value['tables']) for name,value in reference.items()},
            'manual_review':{key:accepted['body']['review'][key] for key in
                             ('lines', 'estimated_cost_yen', 'estimated_cash_after')},
            'model_risk_available':snapshot.risk_available,
            'adopted':models.status(path, store)['model_adopted']})
`)));
    self.postMessage(output);
  } catch (error) { self.postMessage({ error: String(error) }); }
};
