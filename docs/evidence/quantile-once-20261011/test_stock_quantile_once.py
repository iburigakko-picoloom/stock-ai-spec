import json

import numpy as np
import pandas as pd
import pytest

from stock_quantile_once_policy import QuantileOncePolicy
from stock_runtime_memory import AdaptiveMemoryPolicy, MemorySafetyStop

META = {'checkpoint_scope': 'outer-model-evaluation', 'fold': 5, 'horizon': 20}


def policy(tmp_path):
    p = QuantileOncePolicy(tmp_path/'audit.jsonl', available=lambda: 8*2**30,
                          counters=lambda: (0, 0))
    p.batch_id = 'h20-catboost-s17'
    return p


def frames():
    return pd.DataFrame(np.zeros((10, 51), dtype='float32'))


def test_single_admission_then_original(tmp_path):
    p = policy(tmp_path)
    f = frames()
    size, original = p.requirement(f, f, 'catboost', 'quantile')
    p.wait(f, f, 'catboost', 'quantile', META)
    logs = [json.loads(s) for s in p.path.read_text().splitlines()]
    assert logs[0]['required_gib'] == 1.5 + 3.5*size/2**30
    assert logs[0]['one_time_override']
    assert p.consumed and not p._limited
    assert p.requirement(f, f, 'catboost', 'quantile')[1] == original
    p.wait(f, f, 'catboost', 'quantile', META)
    assert json.loads(p.path.read_text().splitlines()[-1])['required_gib'] == original


@pytest.mark.parametrize('field,value', [('fold',4),('horizon',5),
                                       ('checkpoint_scope','diagnostics')])
def test_other_metadata_original(tmp_path, field, value):
    p=policy(tmp_path); f=frames(); meta={**META,field:value}
    required=p.requirement(f,f,'catboost','quantile')[1]
    p.wait(f,f,'catboost','quantile',meta)
    assert not p.consumed
    assert json.loads(p.path.read_text().splitlines()[-1])['required_gib']==required


@pytest.mark.parametrize('batch,family,task', [('h20-catboost-s29','catboost','quantile'),
    ('h20-catboost-s43','catboost','quantile'), ('h20-catboost-s17','catboost','ranking'),
    ('h20-catboost-s17','catboost','regression'), ('h20-catboost-s17','catboost','large_loss'),
    ('h20-catboost-s17','xgboost','quantile')])
def test_other_batch_and_task_original(tmp_path,batch,family,task):
    p=policy(tmp_path); p.batch_id=batch; f=frames()
    required=p.requirement(f,f,family,task)[1]
    p.wait(f,f,family,task,META)
    assert not p.consumed
    assert json.loads(p.path.read_text().splitlines()[-1])['required_gib']==required


def test_observed_floor_and_os_reserve_preserved(tmp_path):
    p=policy(tmp_path); f=frames(); size,_=p.requirement(f,f,'catboost','quantile')
    p.observed['catboost','quantile']=(size,2*2**30)
    p.wait(f,f,'catboost','quantile',META)
    assert json.loads(p.path.read_text().splitlines()[0])['required_gib']==3.75
    assert p.reserve_gib==1.25 and p.factors==AdaptiveMemoryPolicy.factors
    assert QuantileOncePolicy.install_emergency_callback is AdaptiveMemoryPolicy.install_emergency_callback


def test_emergency_and_exception_do_not_consume(tmp_path):
    p=policy(tmp_path); p.emergency=True; f=frames()
    with pytest.raises(MemorySafetyStop): p.wait(f,f,'catboost','quantile',META)
    assert not p.consumed and not p._limited
