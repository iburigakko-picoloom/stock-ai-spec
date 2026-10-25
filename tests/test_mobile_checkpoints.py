import json
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from mobile.python import checkpoints, features

from stock_ai.fixtures import market_fixture
from tests.test_mobile_features import frozen_selection


@pytest.fixture(autouse=True)
def clear_context():
    checkpoints.configure()
    yield
    checkpoints.configure()


def test_checkpoint_preserves_exact_frames_including_nan_precision_and_timezones():
    frames = market_fixture(270)
    for frame in frames:
        restored = checkpoints.decode(checkpoints.encode(frame))
        pd.testing.assert_frame_equal(frame, restored, check_exact=True)
    frame = pd.DataFrame(
        {
            "value": [np.nextafter(1.0, 2.0), -0.0, np.inf, np.nan],
            "time": [pd.Timestamp("2026-01-01T01:02:03.123456789Z"), pd.NaT] * 2,
        }
    )
    pd.testing.assert_frame_equal(
        frame, checkpoints.decode(checkpoints.encode(frame)), check_exact=True
    )


def test_interrupted_feature_batches_resume_without_recomputing_completed_results(monkeypatch):
    frames = market_fixture(270)
    # Different history lengths create independent production batches.
    daily = frames[0]
    symbol = sorted(daily.symbol.unique())[0]
    frames = (
        daily.loc[
            ~((daily.symbol == symbol) & (daily.trading_date == daily.trading_date.min()))
        ].copy(),
        *frames[1:],
    )
    payload = dict(zip(("daily", "market", "sector", "financials"), frames, strict=True))
    payload["as_of"] = (daily.available_at.max() + timedelta(minutes=1)).isoformat()
    selection = frozen_selection()
    expected = features.calculate(payload, selection)
    persisted, events = {}, []

    def save(text):
        value = json.loads(text)
        events.append(value)
        if value["data"] is not None:
            persisted[value["key"]] = value["data"]
        if value["key"].startswith("features-"):
            raise InterruptedError("Synthetic process interruption after durable batch")

    checkpoints.configure({"records": {}, "startedAt": payload["as_of"]}, save)
    checkpoints.plan(10)
    with pytest.raises(InterruptedError):
        features.calculate(payload, selection)
    assert len(persisted) == 1
    prior = set(persisted)

    def resumed(text):
        value = json.loads(text)
        if value["key"] in prior:
            assert value["data"] is None
        events.append(value)

    checkpoints.configure({"records": dict(persisted), "startedAt": payload["as_of"]}, resumed)
    checkpoints.plan(10)
    assert features.calculate(payload, selection) == expected
    assert any(event["data"] is None and event["key"] in prior for event in events)
    complete = checkpoints.encode(expected)
    checkpoints.configure({"records": {"features-result": complete}}, resumed)
    assert checkpoints.cached(
        "features-result", lambda: pytest.fail("Repeated full feature merge"), phase="features"
    ) == expected


def test_prepared_inputs_and_model_outputs_survive_a_fresh_context():
    saved = {}

    def persist(text):
        message = json.loads(text)
        if message["data"] is not None:
            saved[message["key"]] = message["data"]

    checkpoints.configure({"records": {}, "startedAt": "2026-01-01T00:00:00Z"}, persist)
    value = {"daily": market_fixture(270)[0], "source_snapshot_ids": [["daily", "a" * 64]]}
    checkpoints.cached("inputs", lambda: value)
    checkpoints.cached("model-" + "b" * 64, lambda: [0.1, np.nextafter(1.0, 2.0)])
    checkpoints.configure({"records": saved, "startedAt": "2026-01-01T00:00:00Z"}, persist)

    def forbidden():
        raise AssertionError("Saved unit must not be recalculated")

    pd.testing.assert_frame_equal(
        checkpoints.cached("inputs", forbidden)["daily"], value["daily"], check_exact=True
    )
    assert checkpoints.cached("model-" + "b" * 64, forbidden) == [0.1, np.nextafter(1.0, 2.0)]


def test_preparation_resumes_verified_source_days_with_identical_full_identities(tmp_path):
    from mobile.python import market

    from tests.test_mobile_features import timely_history
    from tests.test_mobile_input_cache import assert_same

    path = tmp_path / "mobile.sqlite3"
    cutoff = timely_history(path, sessions=12)
    expected = market.feature_inputs(path, cutoff, True, decision_symbols=["1000", "1003"])
    saved, events = {}, []

    def interrupt(text):
        event = json.loads(text)
        events.append(event)
        if event["data"] is not None:
            saved[event["key"]] = event["data"]
        # First source's profiles and several verified daily projections.
        if len(saved) == 16:
            raise InterruptedError("Synthetic preparation process death")

    checkpoints.configure({"records": {}, "startedAt": cutoff.isoformat()}, interrupt)
    checkpoints.plan(100)
    with pytest.raises(InterruptedError):
        market.feature_inputs(path, cutoff, True, decision_symbols=["1000", "1003"])
    assert events[-1]["done"] == 16
    events.clear()
    checkpoints.configure({"records": saved.copy(), "startedAt": cutoff.isoformat()},
                          lambda text: events.append(json.loads(text)))
    checkpoints.plan(100)
    actual = market.feature_inputs(path, cutoff, True, decision_symbols=["1000", "1003"])
    assert_same(actual, expected)
    reused = [event for event in events if event["key"] in saved]
    assert len(reused) == len(saved)
    assert all(event["data"] is None for event in reused)
    assert events[-1]["done"] > 16


def test_lazy_checkpoint_reads_only_the_requested_unit_without_retaining_payloads():
    values = {"inputs": checkpoints.encode({"value": 42}),
              "source-" + "a" * 64: checkpoints.encode([1, 2, 3])}
    context = {"records": dict.fromkeys(values), "startedAt": "2026-01-01T00:00:00Z"}
    reads = []

    def read(key):
        reads.append(key)
        return values[key]

    checkpoints.configure(context, lambda value: None, read)
    assert checkpoints.cached("inputs", lambda: pytest.fail("Recalculation")) == {"value": 42}
    assert reads == ["inputs"]
    assert all(value is None for value in context["records"].values())
    assert checkpoints.cached("new", lambda: [4]) == [4]
    assert "new" not in context["records"]


def test_budget_yields_only_after_new_checkpoint_and_cached_resume_completes(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(checkpoints.time, "monotonic", lambda: clock[0])
    saved, messages = {}, []

    def save(text):
        value = json.loads(text)
        messages.append(value)
        if value["data"] is not None:
            saved[value["key"]] = value["data"]

    context = {"records": {}, "startedAt": "2026-01-01T00:00:00Z", "budgetSeconds": 480}
    checkpoints.configure(context, save)
    checkpoints.plan(10)
    clock[0] = 481
    with pytest.raises(checkpoints.CheckpointPause):
        checkpoints.cached("model-" + "a" * 64, lambda: [1.25], units=1, phase="predicting")
    assert saved and messages[-1]["data"] is not None
    assert any(x["phase"] == "predicting" and x["data"] is None for x in messages)
    checkpoints.configure({**context, "records": saved}, save)
    clock[0] = 2000
    assert checkpoints.cached(
        "model-" + "a" * 64, lambda: pytest.fail("Repeated"), units=1
    ) == [1.25]


def test_runtime_maps_continuation_to_internal_response_not_input_failure(tmp_path, monkeypatch):
    import asyncio

    from mobile.python import forecasts

    from tests.test_mobile_runtime import device

    runtime = device.__wrapped__(tmp_path, monkeypatch)

    def pause(*args, **kwargs):
        raise checkpoints.CheckpointPause()

    monkeypatch.setattr(forecasts, "generate", pause)
    result = asyncio.run(runtime.request("POST", "/api/v1/mobile/daily/generate", "{}"))
    assert result == {"status": 202, "body": {"code": "CHECKPOINT_CONTINUE"}}
