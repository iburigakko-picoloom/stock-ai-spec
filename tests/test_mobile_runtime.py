from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from mobile.python import runtime


@pytest.fixture()
def device(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'STATE', tmp_path / 'state')
    runtime.initialize()
    return runtime


def run(device, method, path, body=None):
    return asyncio.run(device.request(method, path, json.dumps(body)))


def test_shared_api_runs_without_server_and_preserves_no_order_boundary(device):
    response = run(device, 'GET', '/api/v1/health')
    assert response['status'] == 200
    assert response['body']['orderSubmissionAvailable'] is False
    assert run(device, 'POST', '/api/v1/orders', {})['status'] == 404
    assert run(device, 'GET', 'https://foreign.example/api/v1/health')['status'] == 400


def test_unknown_manual_inputs_survive_restart_and_exact_backup(device):
    value = {'schema_version': 'manual-portfolio-v1', 'holdings_status': 'none',
             'investment_budget_yen': None, 'maximum_drawdown_percent': None,
             'accounts': [], 'holdings': []}
    assert run(device, 'POST', '/api/v1/mobile/portfolio', value)['status'] == 200
    before = run(device, 'GET', '/api/v1/mobile/portfolio')['body']
    backup = device.export_state()
    device.initialize(backup)
    after = run(device, 'GET', '/api/v1/mobile/portfolio')['body']
    assert before == after
    assert after['portfolio']['investment_budget_yen'] is None
    assert 'apiKey' not in backup


def test_invalid_input_does_not_publish_revision(device):
    assert run(device, 'POST', '/api/v1/mobile/portfolio', {'api_key': 'never-store'})['status'] == 422
    assert run(device, 'GET', '/api/v1/mobile/portfolio')['body'] is None


def test_core_views_work_in_embedded_dispatch(device):
    for name in ('status', 'home', 'today', 'settings', 'ranking', 'validation', 'notifications'):
        assert run(device, 'GET', '/api/v1/' + name)['status'] == 200, name
