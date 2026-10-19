"""Synthetic assumption-entry accounting/safety tests; no vendor evidence claims."""

import json
from datetime import datetime, timedelta
from decimal import Decimal as D
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from typer.testing import CliRunner

from stock_ai.cli import app
from stock_ai.ml import assumed_market as module
from stock_ai.ml.assumed_market import (
    AssumedMarketRequest,
    KnownActionBlocker,
    ResearchAssumptions,
    SavedScoreSource,
    evaluate_assumed_market,
    reported_share_ratio,
)
from stock_ai.ml.daily_market import DailyMarketRequest
from stock_ai.ml.fixed_rule import FixedRulePolicy, FixedRuleRequest, FixedSignalDay
from stock_ai.ml.market_nav import MarketReceipt, PinnedEvidence
from stock_ai.ml.nav import NavAction, NavCash, NavInput, NavPrice, NavSession, fixed_bps_policy
from stock_ai.ml.research_funding import build_funding_schedule
from tests.test_daily_nav import DATES, INITIAL, at


def pin(path):
    return PinnedEvidence(path=path, sha256=module._sha(path))


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(
        module,
        "load_development_feature_selection",
        lambda _: SimpleNamespace(
            feature_selection_id="TEST",
            data_snapshot_id="DATA",
            locked_holdout_start="2026-08-01",
        ),
    )

    def make(*, horizon=5, bps=20, rights=None, affected="1000", task="regression"):
        folder = tmp_path / f"h{horizon}-{bps}-{rights}-{affected}-{task}"
        folder.mkdir()

        def save(name, value):
            p = folder / name
            p.write_text(json.dumps(value), encoding="utf-8")
            return pin(p)

        symbols = [str(1000 + i) for i in range(21)]
        days = DATES[:2]
        first, last = INITIAL.date(), days[-1] + timedelta(days=14)
        calendar = [
            (first + timedelta(days=i), int((first + timedelta(days=i)).weekday() < 5))
            for i in range((last - first).days + 1)
        ]
        schedule = build_funding_schedule(calendar, start=first, end=last)
        source = DailyMarketRequest(
            catalog_path=folder / "TEST.duckdb",
            store_root=folder,
            feature_selection_path=folder / "features.json",
            start=first,
            end=last,
            source_snapshot_as_of=at(1, 16) + timedelta(days=30),
        )
        schedule.update(
            request=source.model_dump(mode="json"),
            feature_selection_id="TEST",
            model_data_snapshot_id="DATA",
            locked_holdout_start="2026-08-01",
            holdout_rows_read=False,
        )
        funding_pin = save("funding.json", schedule)
        funding = MarketReceipt(**funding_pin.model_dump(), start=first, end=last)
        frame = pd.DataFrame(
            [
                dict(
                    symbol=s,
                    as_of=at(i, 11),
                    trading_date=pd.Timestamp(INITIAL.date() if i == 0 else days[i - 1]),
                    horizon=horizon,
                    seed=17,
                    model_family="lightgbm",
                    task=task,
                    prediction=-float(j),
                    target="FUTURE OUTCOME MUST NOT BE READ",
                )
                for i in range(2)
                for j, s in enumerate(symbols)
            ]
        )
        parquet = folder / "saved-oof.parquet"
        frame.to_parquet(parquet, index=False)
        score = SavedScoreSource(
            path=parquet,
            sha256=module._sha(parquet),
            horizon=horizon,
            family="lightgbm",
            seed=17,
            task=task,
        )
        registry = save(
            "registry.json",
            dict(
                status="AUTHENTICATED_OOF",
                feature_selection_id="TEST",
                candidates=[
                    dict(
                        horizon=horizon,
                        family="lightgbm",
                        seed=17,
                        authenticated_reports={
                            "TEST": dict(oof_path=str(parquet), oof_file_sha256=score.sha256)
                        },
                    )
                ],
            ),
        )
        domains = save("domain.json", {"days": {at(i, 11).isoformat(): symbols for i in range(2)}})
        raw, instruments, sessions, signals, actions = [], [], [], [], []
        for i, day in enumerate((INITIAL.date(), *days)):
            for s in symbols:
                split = rights == "1" and i == 2 and s == affected
                close = "100" if split else "300"
                raw.append(
                    dict(
                        trading_date=str(day),
                        symbol=s,
                        symbol_status="standard_equity_code",
                        raw_close=close,
                        raw_volume=2000000,
                        bar_state="reported_trade",
                        adjustment_factor=(1 / 3 if split else 1),
                        adjustment_requires_event_evidence=bool(
                            i == 2 and s == affected and rights
                        ),
                        ex_rights_type=rights if i == 2 and s == affected else None,
                        source_record_hash=f"SYNTHETIC-{i}-{s}",
                    )
                )
                instruments.append(
                    dict(trading_date=str(day), symbol=s, round_lot_size=100, tick_size="1")
                )
        if rights == "1":
            actions.append(
                NavAction(
                    event_id="split-test",
                    symbol=affected,
                    kind="split",
                    effective_at=at(1, 9),
                    available_at=at(1, 9),
                    numerator=3,
                    denominator=1,
                    source_id=f"reported-split-assumption:SYNTHETIC-2-{affected}",
                )
            )
        for i, day in enumerate(days):
            prices = tuple(
                NavPrice(
                    symbol=s,
                    execution_price="100" if rights == "1" and i == 1 and s == affected else "300",
                    close_price="100" if rights == "1" and i == 1 and s == affected else "300",
                    buy_status="tradable",
                    sell_status="tradable",
                    capacity_shares=100000,
                    tick_size="1",
                    source_id="SYNTHETIC declared execution",
                )
                for s in symbols
            )
            release = next(
                x["sale_cash_available_at"]
                for x in schedule["rows"]
                if x["trading_date"] == str(day)
            )
            sessions.append(
                NavSession(
                    trading_date=day,
                    execution_at=at(i, 16),
                    close_at=at(i, 16),
                    sale_cash_available_at=datetime.fromisoformat(release),
                    prices=prices,
                )
            )
            prior_at = INITIAL if i == 0 else at(i - 1, 16)
            signals.append(
                FixedSignalDay(
                    as_of=at(i, 11),
                    available_at=at(i, 11),
                    reference_price_at=at(i, 9) if rights == "1" and i == 1 else prior_at,
                    horizon=horizon,
                    score_unit="ranking_score" if task == "ranking" else "fractional_return",
                    scores=tuple((s, -float(j)) for j, s in enumerate(symbols[:20])),
                    reference_prices=tuple(
                        (s, D(100 if rights == "1" and i == 1 and s == affected else 300))
                        for s in symbols
                    ),
                    source_id=score.sha256,
                )
            )
        market_request = source.model_copy(update={"end": days[-1]})
        market_pin = save(
            "market.json",
            dict(
                schema_version="daily-market-projection-v1",
                request=market_request.model_dump(mode="json"),
                price_basis="unadjusted",
                feature_selection_id="TEST",
                data_snapshot_id_declared_by_features="DATA",
                locked_holdout_start="2026-08-01",
                holdout_rows_read=False,
                rows=raw,
                source_objects=[],
            ),
        )
        market = MarketReceipt(**market_pin.model_dump(), start=first, end=days[-1])
        instrument_pin = save(
            "instruments.json",
            dict(
                schema_version="daily-instrument-rules-v1",
                feature_selection_id="TEST",
                holdout_rows_read=False,
                request=market_request.model_dump(mode="json"),
                rows=instruments,
            ),
        )
        frozen = save("snapshot.json", dict(snapshot_id="SYNTHETIC", objects=[]))
        accounting = NavInput(
            data_mode="historical_research",
            source_snapshot_id="SYNTHETIC",
            calendar_id=schedule["calendar_id"],
            calendar_dates=days,
            price_basis="unadjusted",
            execution_semantics="daily_close_research_proxy",
            initial_as_of=INITIAL,
            cash=(NavCash(bucket="research", amount=10000000),),
            sessions=tuple(sessions),
            actions=tuple(actions),
            cost_policy=fixed_bps_policy(D(bps)),
        )
        return AssumedMarketRequest(
            schema_version="assumed-market-fixed-rule-request-v1",
            assumptions=ResearchAssumptions(
                version="daily-close-declared-assumptions-v1",
                entitlement_basis="confirmed-current-Light-frozen-acquisition",
                known_future_information_present=False,
                execution="reported-close-with-5pct-volume-capacity",
                limit_touches="withhold-buy-on-UL-sell-on-LL",
                action_scope="reported-splits-only-unreported-coverage-unverified",
                revision_policy="single-as-revised-vintage-not-historical-known-at",
                timing="saved-OOF-asof-after-feature-day-before-next-close-proxy",
                split_factor_interpretation="small-rational-with-identical-float-representation",
            ),
            feature_selection_path=source.feature_selection_path,
            frozen_source_manifest=frozen,
            candidate_registry=registry,
            score_source=score,
            eligible_universe=domains,
            market_receipts=(market,),
            instrument_receipts=(instrument_pin,),
            research_funding_receipt=funding,
            rule=FixedRuleRequest(
                evaluation_tier="price_only_research",
                policy=FixedRulePolicy(horizon=horizon, one_way_bps=D(bps)),
                accounting=accounting,
                signals=tuple(signals),
            ),
        )

    return make


@pytest.mark.parametrize("horizon,bps", [(5, 20), (20, 20), (5, 40), (20, 40)])
def test_assumption_research_reuses_ledger_with_hand_nav_costs_and_cash_hold(
    prepared, horizon, bps
):
    request = prepared(horizon=horizon, bps=bps)
    result = evaluate_assumed_market(request)
    expected = D(10000000) - D(9000000) * D(bps) / 10000
    assert result["status"] == "COMPLETE_ASSUMPTION_RESEARCH"
    assert [D(d["nav"]) for d in result["strategy"]["days"]] == [expected, expected]
    assert D(result["strategy"]["total_trading_cost"]) == 10000000 - expected
    assert D(result["strategy"]["maximum_drawdown"]) == (10000000 - expected) / 10000000
    assert D(result["hold"]["total_return"]) == 0
    assert D(result["metrics"]["turnover"]) == D(9000000) / expected
    assert (
        result["not_actual_execution_reconstruction"] and result["not_standalone_adoption_evidence"]
    )
    assert result["adoption_eligible"] is False and result["holdout_scored"] is False


def test_reported_thirds_preserve_shares_and_value_without_double_adjustment(prepared):
    result = evaluate_assumed_market(prepared(rights="1"))
    assert result["status"] == "COMPLETE_ASSUMPTION_RESEARCH"
    first, last = result["strategy"]["days"]
    assert D(first["nav"]) == D(last["nav"]) == D(9982000)
    assert next(p["shares"] for p in first["positions"] if p["symbol"] == "1000") == 1500
    assert next(p["shares"] for p in last["positions"] if p["symbol"] == "1000") == 4500


def test_known_unhandled_rights_stop_an_actual_held_exposure(prepared):
    result = evaluate_assumed_market(prepared(rights="3"))
    assert result["status"] == "INCOMPLETE" and result["strategy"] is None
    assert result["unresolved_exposures"][0]["symbol"] == "1000"
    assert result["unresolved_exposures"][0]["related_held_value_yen"] == "450000"


def test_known_event_outside_actual_holdings_and_orders_does_not_block(prepared):
    assert evaluate_assumed_market(prepared(rights="3", affected="1020"))["status"] == (
        "COMPLETE_ASSUMPTION_RESEARCH"
    )


@pytest.mark.parametrize(
    "kind",
    [
        "score-bytes",
        "market-bytes",
        "future-feature",
        "wrong-score",
        "early-funding",
        "unknown-entitlement",
    ],
)
def test_corruption_future_information_and_changed_conditions_are_not_normal_results(
    prepared, kind
):
    request = prepared()
    if kind == "score-bytes":
        with request.score_source.path.open("ab") as f:
            f.write(b"changed")
    elif kind == "market-bytes":
        request.market_receipts[0].path.write_text("{}")
    elif kind == "future-feature":
        frame = pd.read_parquet(request.score_source.path)
        frame["trading_date"] = frame.as_of.dt.tz_localize(None).dt.normalize()
        frame.to_parquet(request.score_source.path, index=False)
        score = request.score_source.model_copy(
            update={"sha256": module._sha(request.score_source.path)}
        )
        reg = json.loads(request.candidate_registry.path.read_text())
        reg["candidates"][0]["authenticated_reports"]["TEST"]["oof_file_sha256"] = score.sha256
        request.candidate_registry.path.write_text(json.dumps(reg))
        request = request.model_copy(
            update={
                "score_source": score,
                "candidate_registry": pin(request.candidate_registry.path),
            }
        )
    elif kind == "wrong-score":
        signals = list(request.rule.signals)
        signals[0] = signals[0].model_copy(
            update={"scores": (("1000", 999.0), *signals[0].scores[1:])}
        )
        request = request.model_copy(
            update={"rule": request.rule.model_copy(update={"signals": tuple(signals)})}
        )
    elif kind == "early-funding":
        accounting = request.rule.accounting
        sessions = (
            accounting.sessions[0].model_copy(
                update={"sale_cash_available_at": accounting.sessions[0].close_at}
            ),
            *accounting.sessions[1:],
        )
        request = request.model_copy(
            update={
                "rule": request.rule.model_copy(
                    update={"accounting": accounting.model_copy(update={"sessions": sessions})}
                )
            }
        )
    else:
        request = request.model_copy(
            update={
                "assumptions": request.assumptions.model_copy(
                    update={"entitlement_basis": "unknown"}
                )
            }
        )
    with pytest.raises(ValueError):
        evaluate_assumed_market(request)


def test_holdout_declaration_is_rejected_before_source_files_open(prepared):
    request = prepared()
    ref = request.research_funding_receipt.model_copy(
        update={
            "end": DATES[-1].replace(month=8, day=1),
            "path": request.research_funding_receipt.path.with_name("MUST_NOT_OPEN.json"),
        }
    )
    with pytest.raises(ValueError, match="holdout"):
        evaluate_assumed_market(request.model_copy(update={"research_funding_receipt": ref}))


@pytest.mark.parametrize(
    "kind",
    ["registry", "policy", "universe", "instrument", "reference", "price", "capacity", "units"],
)
def test_altered_lineage_domain_prices_and_execution_assumptions_are_rejected(prepared, kind):
    request = prepared()
    rule = request.rule
    if kind in ("registry", "universe", "instrument"):
        field = {
            "registry": "candidate_registry",
            "universe": "eligible_universe",
            "instrument": "instrument_receipts",
        }[kind]
        ref = request.instrument_receipts[0] if kind == "instrument" else getattr(request, field)
        value = json.loads(ref.path.read_text())
        if kind == "registry":
            value["status"] = "UNAUTHENTICATED"
        elif kind == "universe":
            day = next(iter(value["days"]))
            value["days"][day].append(value["days"][day][0])
        else:
            for row in value["rows"]:
                row["round_lot_size"] = None
        ref.path.write_text(json.dumps(value))
        request = request.model_copy(
            update={field: (pin(ref.path),) if kind == "instrument" else pin(ref.path)}
        )
    elif kind == "policy":
        request = request.model_copy(
            update={
                "rule": rule.model_copy(
                    update={
                        "policy": rule.policy.model_copy(update={"invested_fraction": D("0.8")})
                    }
                )
            }
        )
    elif kind in ("reference", "units"):
        signal = rule.signals[0]
        change = (
            {"score_unit": "ranking_score"}
            if kind == "units"
            else {"reference_prices": (("1000", D("301")), *signal.reference_prices[1:])}
        )
        request = request.model_copy(
            update={
                "rule": rule.model_copy(
                    update={"signals": (signal.model_copy(update=change), *rule.signals[1:])}
                )
            }
        )
    else:
        accounting = rule.accounting
        session = accounting.sessions[0]
        price = session.prices[0]
        change = {"close_price": D("301")} if kind == "price" else {"capacity_shares": 100}
        session = session.model_copy(
            update={"prices": (price.model_copy(update=change), *session.prices[1:])}
        )
        request = request.model_copy(
            update={
                "rule": rule.model_copy(
                    update={
                        "accounting": accounting.model_copy(
                            update={"sessions": (session, *accounting.sessions[1:])}
                        )
                    }
                )
            }
        )
    with pytest.raises(ValueError):
        evaluate_assumed_market(request)


def test_float_factor_resolution_never_rounds_approximate_values():
    assert reported_share_ratio(1 / 3) == Fraction(3)
    assert reported_share_ratio(0.5) == Fraction(2)
    for value in (0, 1, float("nan"), 0.333333):
        with pytest.raises(ValueError):
            reported_share_ratio(value)


@pytest.mark.parametrize("changed", ["version", "missing_held_reference", "comparison_use"])
def test_reference_gap_sensitivity_requires_a_separate_explicit_exploratory_contract(
    prepared, changed
):
    values = prepared().assumptions.model_dump()
    values[changed] = {
        "version": "daily-close-declared-assumptions-v2",
        "missing_held_reference": "skip_rebalance",
        "comparison_use": "post_result_exploratory_sensitivity",
    }[changed]
    with pytest.raises(ValueError, match="explicit v2 exploratory"):
        ResearchAssumptions.model_validate(values)


def test_exploratory_replay_cannot_claim_original_comparison_or_adoption(prepared):
    request = prepared()
    original = evaluate_assumed_market(request)
    assumptions = ResearchAssumptions.model_validate({
        **request.assumptions.model_dump(),
        "version": "daily-close-declared-assumptions-v2",
        "missing_held_reference": "skip_rebalance",
        "comparison_use": "post_result_exploratory_sensitivity",
    })
    result = evaluate_assumed_market(request.model_copy(update={"assumptions": assumptions}))
    assert result["strategy"] == original["strategy"]  # No reference gap in this fixture.
    assert result["comparison_use"] == "post_result_exploratory_sensitivity"
    assert result["decision_policy_sha256"] != original["decision_policy_sha256"]
    assert result["input_sha256"] != original["input_sha256"]
    assert result["metrics"]["skipped_rebalances"] == 0
    assert not result["supersedes_original_comparison"]
    assert not result["adoption_eligible"] and not result["holdout_scored"]


def test_exploratory_mode_still_stops_a_known_unsupported_right(prepared):
    request = prepared(rights="3")
    assumptions = ResearchAssumptions.model_validate({
        **request.assumptions.model_dump(),
        "version": "daily-close-declared-assumptions-v2",
        "missing_held_reference": "skip_rebalance",
        "comparison_use": "post_result_exploratory_sensitivity",
    })
    result = evaluate_assumed_market(request.model_copy(update={"assumptions": assumptions}))
    assert result["status"] == "INCOMPLETE"
    assert result["stopped_reason"] == "KNOWN_UNRESOLVED_CORPORATE_ACTION"
    assert not result["adoption_eligible"]


@pytest.mark.parametrize("event_day", [0, 1])
def test_supplemental_delisting_evidence_blocks_new_orders_and_existing_holdings(
    prepared, event_day
):
    request = prepared()
    # A genuine fixture file stands in for the externally retained document.
    document = request.feature_selection_path.parent / "synthetic-delisting-document.txt"
    document.write_text("Synthetic evidence only", encoding="utf-8")
    blocker = KnownActionBlocker(
        symbol="1000", effective_from=DATES[event_day],
        kind="delisting_cash_accounting_unresolved", evidence=pin(document),
    )
    if event_day:
        market = request.market_receipts[0]
        value = json.loads(market.path.read_text(encoding="utf-8"))
        value["rows"] = [r for r in value["rows"]
                         if (r["symbol"], r["trading_date"]) != ("1000", str(DATES[1]))]
        market.path.write_text(json.dumps(value), encoding="utf-8")
        sessions = list(request.rule.accounting.sessions)
        sessions[1] = sessions[1].model_copy(
            update={"prices": tuple(p for p in sessions[1].prices if p.symbol != "1000")}
        )
        request = request.model_copy(update={
            "market_receipts": (market.model_copy(update={"sha256": module._sha(market.path)}),),
            "rule": request.rule.model_copy(update={
                "accounting": request.rule.accounting.model_copy(
                    update={"sessions": tuple(sessions)}
                )
            }),
        })
    result = evaluate_assumed_market(
        request.model_copy(update={"known_action_blockers": (blocker,)})
    )
    assert result["status"] == "INCOMPLETE"
    assert result["stopped_reason"] == "KNOWN_UNRESOLVED_CORPORATE_ACTION"
    issue = result["unresolved_exposures"][0]
    assert issue["symbol"] == "1000" and issue["date"] == str(DATES[event_day])
    assert issue["event_kind"] == "delisting_cash_accounting_unresolved"
    assert (D(issue["related_held_value_yen"]) > 0) == bool(event_day)
    assert not result["adoption_eligible"] and not result["holdout_scored"]


def test_supplemental_event_evidence_cannot_be_changed_or_open_the_holdout(prepared):
    request = prepared()
    document = request.feature_selection_path.parent / "synthetic-delisting-document.txt"
    document.write_text("Synthetic evidence only", encoding="utf-8")
    blocker = KnownActionBlocker(
        symbol="1000", effective_from=DATES[1],
        kind="delisting_cash_accounting_unresolved", evidence=pin(document),
    )
    document.write_text("Changed fixture evidence", encoding="utf-8")
    with pytest.raises(ValueError):
        evaluate_assumed_market(request.model_copy(update={"known_action_blockers": (blocker,)}))
    blocker = blocker.model_copy(update={"effective_from": DATES[0].replace(month=8, day=1)})
    with pytest.raises(ValueError, match="locked holdout"):
        evaluate_assumed_market(request.model_copy(update={"known_action_blockers": (blocker,)}))


@pytest.mark.parametrize("task", ["rank_return", "rank_return_risk"])
def test_fixed_combinations_use_percentile_ranks_and_reverse_loss_probability(task):
    frame = pd.DataFrame(
        [
            {
                "as_of": at(0, 11),
                "trading_date": pd.Timestamp(INITIAL.date()),
                "symbol": str(1000 + i),
                "task": name,
                "prediction": value,
            }
            for name, values in {
                "regression": [1, 3, 2],
                "ranking": [3, 1, 2],
                "quantile": [3, 2, 1],
                "large_loss": [0.1, 0.5, 0.9],
            }.items()
            for i, value in enumerate(values)
        ]
    )
    observed = module.saved_score_mapping(frame, task)[at(0, 11)]
    expected = [1 / 3, 1 / 3, 1 / 3] if task == "rank_return" else [0.5, 1 / 6, -1 / 6]
    assert list(observed.values()) == pytest.approx(expected)
    if task == "rank_return_risk":
        with pytest.raises(ValueError, match="every saved task"):
            module.saved_score_mapping(
                frame.loc[~((frame.task == "quantile") & (frame.symbol == "1000"))], task
            )


@pytest.mark.parametrize("recipe", ["weighted_return", "momentum_20d"])
def test_saved_benchmark_requires_authenticated_unchanged_development_receipt(prepared, recipe):
    request = prepared()
    folder = request.score_source.path.parent
    frame = pd.read_parquet(request.score_source.path)
    frame[recipe] = frame.prediction
    path = folder / "benchmark.parquet"
    frame[["as_of", "trading_date", "symbol", recipe]].to_parquet(path, index=False)
    proof = {
        "schema_version": "daily-forward-crossfit-v1"
        if recipe == "weighted_return"
        else "daily-regression-risk-simple-baselines-v3",
        "research_only": True,
        "holdout_scored": False,
        "adoption_eligible": False,
        "feature_selection_id": "TEST",
        "data_snapshot_id": "DATA",
        "results": [{"horizon": 5, "oof_path": str(path), "oof_byte_sha256": module._sha(path)}],
    }
    proof_path = folder / "benchmark-receipt.json"
    proof_path.write_text(json.dumps(proof))
    proof_ref = pin(proof_path)
    audit = {
        "status": "COMPLETE_RESEARCH",
        "holdout_opened": False,
        "training_performed": False,
        "weights_or_calibration_changed": False,
        "feature_selection_id": "TEST",
        "model_data_snapshot_id": "DATA",
        "input_receipts": {str(proof_ref.path): proof_ref.sha256},
        "results": [{"horizon": 5, "ensemble_predictions_reproduced_from_saved_models": True}],
    }
    audit_path = folder / "authenticated-replay.json"
    audit_path.write_text(json.dumps(audit))
    source = module.SavedBenchmarkSource(
        **pin(path).model_dump(),
        kind="saved-benchmark",
        horizon=5,
        recipe=recipe,
        receipt=proof_ref,
        authentication=pin(audit_path),
    )
    request = request.model_copy(update={"score_source": source})
    assert evaluate_assumed_market(request)["status"] == "COMPLETE_ASSUMPTION_RESEARCH"
    audit["weights_or_calibration_changed"] = True
    audit_path.write_text(json.dumps(audit))
    request = request.model_copy(
        update={"score_source": source.model_copy(update={"authentication": pin(audit_path)})}
    )
    with pytest.raises(ValueError, match="authenticated development"):
        evaluate_assumed_market(request)


@pytest.mark.parametrize("task", ["rank_return", "rank_return_risk"])
def test_combined_saved_heads_reach_the_same_fixed_rule_without_return_units(prepared, task):
    request = prepared()
    frame = pd.read_parquet(request.score_source.path)
    heads = [frame]
    for name, factor in [("ranking", 2), ("quantile", 0.3), ("large_loss", -0.05)]:
        head = frame.copy()
        head["task"] = name
        head["prediction"] = head.prediction * factor
        heads.append(head)
    pd.concat(heads, ignore_index=True).to_parquet(request.score_source.path, index=False)
    score = request.score_source.model_copy(
        update={"task": task, "sha256": module._sha(request.score_source.path)}
    )
    registry = json.loads(request.candidate_registry.path.read_text())
    registry["candidates"][0]["authenticated_reports"]["TEST"]["oof_file_sha256"] = score.sha256
    request.candidate_registry.path.write_text(json.dumps(registry))
    request = request.model_copy(
        update={"score_source": score, "candidate_registry": pin(request.candidate_registry.path)}
    )
    mapped = module._scores(request)
    signals = tuple(
        s.model_copy(
            update={
                "scores": tuple(sorted(mapped[s.as_of].items(), key=lambda x: (-x[1], x[0]))[:20]),
                "score_unit": "ranking_score",
            }
        )
        for s in request.rule.signals
    )
    request = request.model_copy(
        update={"rule": request.rule.model_copy(update={"signals": signals})}
    )
    result = evaluate_assumed_market(request)
    assert result["status"] == "COMPLETE_ASSUMPTION_RESEARCH"
    assert not result["adoption_eligible"]
    assert {o["symbol"] for o in result["generated_orders"]} == {str(1000 + i) for i in range(20)}


def test_cli_pins_assumptions_before_replay_without_claiming_strict_coverage(prepared, tmp_path):
    request = prepared(task="ranking")
    path = tmp_path / "input.json"
    path.write_text(request.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "research",
            "evaluate-assumed-market",
            "--input",
            str(path),
            "--output-root",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0, result.output
    receipt = json.loads(
        Path(json.loads(result.output)["evaluation_path"]).read_text(encoding="utf-8")
    )
    assert receipt["unverified"] and receipt["not_standalone_adoption_evidence"]
    assert receipt["frozen_input"]["sha256"] == module._sha(Path(receipt["frozen_input"]["path"]))
