"""One launch, one admission exception; original policy remains immutable."""
from stock_runtime_memory import AdaptiveMemoryPolicy


class QuantileOncePolicy(AdaptiveMemoryPolicy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.batch_id = None
        self.consumed = False
        self._limited = False

    def requirement(self, train_x, validation_x, family, task):
        size, original = super().requirement(train_x, validation_x, family, task)
        if not self._limited:
            return size, original
        estimate = 3.5 * size + self.backend_allowance_gib * 2**30
        observed = self.observed.get((family, task))
        if observed is not None:
            previous_size, increment = observed
            estimate = max(estimate, 1.25 * increment * size / max(1, previous_size))
        return size, estimate / 2**30 + self.reserve_gib

    def wait(self, train_x, validation_x, family, task, metadata=None):
        meta = dict(metadata or {})
        match = (not self.consumed and self.batch_id == 'h20-catboost-s17'
                 and family == 'catboost' and task == 'quantile'
                 and meta.get('checkpoint_scope') == 'outer-model-evaluation'
                 and meta.get('fold') == 5 and meta.get('horizon') == 20)
        self._limited = match
        if match:
            meta.update(one_time_override=True, input_copy_factor=3.5,
                        original_input_copy_factor=5.0, override_batch_id=self.batch_id)
        try:
            super().wait(train_x, validation_x, family, task, meta)
            if match:
                self.consumed = True
                self.write('one_time_override_consumed', batch_id=self.batch_id,
                           scope='outer-model-evaluation', task=task, fold=5,
                           subsequent_admissions_use_original_policy=True)
        finally:
            self._limited = False
