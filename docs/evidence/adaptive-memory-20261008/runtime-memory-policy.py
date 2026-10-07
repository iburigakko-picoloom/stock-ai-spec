"""Explicit execution-only policy; scientific model inputs/config/source stay unchanged."""

import ctypes
import gc
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from stock_ai.ml import advanced, memory


class MemorySafetyStop(BaseException):
    pass


def process_memory():
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
                "PrivateUsage",
            )
        ]

    value = Counters()
    value.cb = ctypes.sizeof(value)
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    handle = kernel.GetCurrentProcess()
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(value), value.cb):
        raise OSError("process memory read failed")
    return value.WorkingSetSize, value.PrivateUsage


class AdaptiveMemoryPolicy:
    reserve_gib = 1.25
    backend_allowance_gib = 0.25
    factors: ClassVar[dict[str, float]] = {"lightgbm": 3.0, "xgboost": 4.0, "catboost": 5.0}

    def __init__(
        self,
        path,
        notify=lambda *args, **kwargs: None,
        available=memory._available_physical_bytes,
        sleep=time.sleep,
        counters=process_memory,
    ):
        self.path = Path(path)
        self.notify = notify
        self.available = available
        self.sleep = sleep
        self.counters = counters
        self.observed = {}
        self.emergency = False
        self.current = None

    def write(self, kind, **values):
        record = {"time_utc": datetime.now(UTC).isoformat(), "kind": kind, **values}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def requirement(self, train_x, validation_x, family, task):
        # Inputs are already allocated: reserve further conversion/backend copies,
        # fixed native overhead, and OS headroom, not a total process RAM target.
        matrix_bytes = sum(
            len(frame) * sum(dtype.itemsize for dtype in frame.dtypes)
            for frame in (train_x, validation_x)
        )
        ranking_bytes = len(train_x) * 32 if task == "ranking" else 0
        estimate = (
            self.factors[family] * matrix_bytes + ranking_bytes + self.backend_allowance_gib * 2**30
        )
        observed = self.observed.get((family, task))
        if observed is not None:
            previous_bytes, increment = observed
            estimate = max(estimate, 1.25 * increment * matrix_bytes / max(1, previous_bytes))
        return matrix_bytes, estimate / 2**30 + self.reserve_gib

    def wait(self, train_x, validation_x, family, task, metadata=None):
        if self.emergency:
            raise MemorySafetyStop("Actual OS memory emergency; explicit review required")
        matrix_bytes, required = self.requirement(train_x, validation_x, family, task)
        gc.collect()
        workspace = memory._ACTIVE.get()
        if workspace is not None:
            workspace.reap()
        while True:
            available = self.available() / 2**30
            if available < required:
                # Release unused Arrow storage; never drop live model/input buffers.
                memory.pa.default_memory_pool().release_unused()
                available = self.available() / 2**30
            passed = available >= required
            record = {
                "available_gib": available,
                "required_gib": required,
                "os_reserve_gib": self.reserve_gib,
                "matrix_bytes": matrix_bytes,
                "family": family,
                "task": task,
                "passed": passed,
                **(metadata or {}),
            }
            self.write("fit_admission", **record)
            if workspace is not None:
                workspace.fit_checks.append(
                    {
                        "checked_at_utc": datetime.now(UTC).isoformat(),
                        **record,
                        "minimum_gib": required,
                        "policy": "adaptive-input-and-observed-increment-v1",
                    }
                )
                workspace.path.with_suffix(".fit-headroom.json").write_text(
                    json.dumps(workspace.fit_checks, indent=2), encoding="utf-8"
                )
            if passed:
                self.notify("FIT_ADMITTED", **record)
                ws, private = self.counters()
                self.current = {
                    **record,
                    "before_ws": ws,
                    "before_private": private,
                    "peak_ws": ws,
                    "peak_private": private,
                }
                return
            self.notify("WAITING_FOR_MEMORY", **record)
            # The learning process waits for this same prepared fold. No fit is
            # started, restarted or re-created, and no Codex monitor is involved.
            self.sleep(60)

    def check(self):
        caller = sys._getframe(1)
        if caller.f_code.co_name not in ("generate_oof_predictions", "oos_permutation_diagnostics"):
            raise RuntimeError("Unknown fit boundary; adaptive admission refused")
        local = caller.f_locals
        task = local.get("task", "regression")
        evidence = local.get("checkpoint_evidence", {})
        self.wait(
            local["train_x"],
            local["validation_x"],
            local["family"],
            task,
            {
                "checkpoint_scope": evidence.get("checkpoint_scope", "diagnostics"),
                "fold": evidence.get("fold"),
                "horizon": local.get("horizon"),
            },
        )

    def finish_observation(self):
        if self.current is None:
            return
        sample = self.current
        ws, private = self.counters()
        sample["peak_ws"] = max(sample["peak_ws"], ws)
        sample["peak_private"] = max(sample["peak_private"], private)
        increment = max(
            0,
            sample["peak_ws"] - sample["before_ws"],
            sample["peak_private"] - sample["before_private"],
        )
        key = (sample["family"], sample["task"])
        self.observed[key] = (
            sample["matrix_bytes"],
            max(increment, self.observed.get(key, (0, 0))[1]),
        )
        self.write(
            "model_fit_iteration_memory_audit",
            **sample,
            iteration_sampled_increment_bytes=increment,
            allocation_between_iterations_not_fully_observed=True,
        )
        if not self.emergency:
            self.notify(
                "MODEL_FIT_COMPLETED",
                family=sample["family"],
                task=sample["task"],
                checkpoint_scope=sample.get("checkpoint_scope"),
                fold=sample.get("fold"),
                sampled_increment_gib=increment / 2**30,
            )
        self.current = None

    def install(self):
        advanced.check_fit_headroom = self.check
        original = advanced._fit_predict

        def fit(**kwargs):
            # Endpoints are an audit, not a claim of a continuously measured peak.
            before_ws, before_private = self.counters()
            result = original(**kwargs)
            after_ws, after_private = self.counters()
            size, _ = self.requirement(
                kwargs["train_x"], kwargs["validation_x"], kwargs["family"], kwargs["task"]
            )
            delta = max(0, after_ws - before_ws, after_private - before_private)
            key = (kwargs["family"], kwargs["task"])
            self.observed[key] = (size, max(delta, self.observed.get(key, (0, 0))[1]))
            self.write(
                "fit_completed_endpoint_audit",
                family=key[0],
                task=key[1],
                matrix_bytes=size,
                working_set_before=before_ws,
                working_set_after=after_ws,
                private_commit_before=before_private,
                private_commit_after=after_private,
                endpoint_increment_bytes=delta,
                peak_not_measured=True,
            )
            return result

        advanced._fit_predict = fit
        self.install_emergency_callback()

    def install_emergency_callback(self):
        policy = self

        def observe():
            if policy.current is not None:
                ws, private = policy.counters()
                policy.current["peak_ws"] = max(policy.current["peak_ws"], ws)
                policy.current["peak_private"] = max(policy.current["peak_private"], private)
            available = policy.available() / 2**30
            if available < 0.5:
                policy.emergency = True
                policy.write("actual_os_emergency", available_gib=available)
                policy.notify("ACTUAL_OS_MEMORY_EMERGENCY", available_gib=available)
                raise MemorySafetyStop("Available physical RAM below emergency OS reserve0.5GiB")

        # Inline callbacks on the existing model thread; no background monitor.
        import lightgbm as lgb

        original_fit = lgb.LGBMModel.fit

        def lightgbm_fit(model, *args, **kwargs):
            callbacks = list(kwargs.get("callbacks") or [])
            callbacks.append(lambda env: observe())
            kwargs["callbacks"] = callbacks
            try:
                return original_fit(model, *args, **kwargs)
            finally:
                policy.finish_observation()

        lgb.LGBMModel.fit = lightgbm_fit

        import xgboost as xgb

        class XgbObserver(xgb.callback.TrainingCallback):
            def after_iteration(self, model, epoch, evals_log):
                observe()
                return False

        def wrap_xgb(original):
            def fit(model, *args, **kwargs):
                callbacks = model.get_params().get("callbacks")
                model.set_params(callbacks=[*(callbacks or []), XgbObserver()])
                try:
                    return original(model, *args, **kwargs)
                finally:
                    policy.finish_observation()
                    model.set_params(callbacks=callbacks)

            return fit

        for cls in (xgb.XGBModel, xgb.XGBClassifier, xgb.XGBRanker):
            cls.fit = wrap_xgb(cls.fit)

        import catboost

        class CatObserver:
            def after_iteration(self, info):
                observe()
                return True

        def wrap_cat(original):
            def fit(model, *args, **kwargs):
                kwargs["callbacks"] = [*(kwargs.get("callbacks") or []), CatObserver()]
                try:
                    result = original(model, *args, **kwargs)
                finally:
                    policy.finish_observation()
                if policy.emergency:
                    raise MemorySafetyStop("Actual OS emergency during native fit")
                return result

            return fit

        for cls in (
            catboost.CatBoostRegressor,
            catboost.CatBoostClassifier,
            catboost.CatBoostRanker,
        ):
            cls.fit = wrap_cat(cls.fit)
