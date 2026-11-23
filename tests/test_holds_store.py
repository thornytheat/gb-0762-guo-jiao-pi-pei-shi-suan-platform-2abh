import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.errors import TrialError
from app.modules.holds.ledger import HOLD, RELEASE
from app.modules.holds import store


def order(oid, otype=HOLD, when='2026-11-20', lots=None):
    return {'order_id': oid, 'type': otype, 'material': '果胶', 'occurred_at': when,
            'reason': '质检停用', 'scope': {'lots': lots if lots is not None else ['PJ-02'], 'suppliers': []}}


def test_retry_does_not_duplicate_registration(tmp_path):
    one, fresh_one = store.record(tmp_path, order('QC-1'))
    two, fresh_two = store.record(tmp_path, order('QC-1'))
    assert (fresh_one, fresh_two) == (True, False)
    assert one == two
    lines = (tmp_path / store.LEDGER_FILE).read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1 and json.loads(lines[0])['order_id'] == 'QC-1'


def test_load_replays_latest_state(tmp_path):
    store.record(tmp_path, order('QC-1', when='2026-11-18'))
    store.record(tmp_path, order('QC-2', RELEASE, when='2026-11-21', lots=[]))
    ledger = store.load(tmp_path)
    assert ledger.holds() == []


def test_concurrent_retries_persist_single_order(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.record(tmp_path, order('QC-1')), range(16)))
    assert sum(fresh for _, fresh in results) == 1
    assert len((tmp_path / store.LEDGER_FILE).read_text(encoding='utf-8').splitlines()) == 1


def test_corrupt_ledger_raises_named_error(tmp_path):
    path = tmp_path / store.LEDGER_FILE
    path.write_text('{"order_id": "broken"}\n', encoding='utf-8')
    with pytest.raises(TrialError) as exc:
        store.load(tmp_path)
    assert exc.value.code.startswith('HOLD_LEDGER_CORRUPT')


def test_invalid_order_writes_nothing(tmp_path):
    with pytest.raises(ValueError):
        store.record(tmp_path, {'order_id': 'bad'})
    assert not (tmp_path / store.LEDGER_FILE).exists()
