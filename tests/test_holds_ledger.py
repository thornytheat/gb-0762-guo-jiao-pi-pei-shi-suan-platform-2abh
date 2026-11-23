import pytest

from app.modules.holds.ledger import (CLEAR, HELD_LOT, HOLD, LOT_NOT_ACCEPTED, RELEASE,
                                      SUPPLIER_SUSPECT, UNTRACEABLE, HoldLedger)

PECTIN = '果胶'


def hold(order_id, lots=(), suppliers=(), when='2026-11-20', reason='质检停用', seq=0):
    return {'order_id': order_id, 'type': HOLD, 'material': PECTIN, 'occurred_at': when,
            'reason': reason, 'scope': {'lots': list(lots), 'suppliers': list(suppliers)}, 'seq': seq}


def release(order_id, when, reason='解封', seq=0):
    return {'order_id': order_id, 'type': RELEASE, 'material': PECTIN, 'occurred_at': when,
            'reason': reason, 'scope': {'lots': [], 'suppliers': []}, 'seq': seq}


def test_lot_level_hold_blocks_only_matching_lot():
    ledger = HoldLedger([hold('QC-1', lots=['PJ-02'])])
    assert ledger.verdict(PECTIN, lot='PJ-02', accepted_lots=['PJ-01', 'PJ-02']) == HELD_LOT
    # 无关试配的批号不受影响，避免全停误伤
    assert ledger.verdict(PECTIN, lot='PJ-01', accepted_lots=['PJ-01', 'PJ-02']) == CLEAR
    assert ledger.block_lots(PECTIN, ['PJ-01', 'PJ-02', 'PJ-03']) == frozenset({'PJ-02'})


def test_later_release_reopens_lot():
    ledger = HoldLedger([hold('QC-1', lots=['PJ-02'], when='2026-11-18'),
                         release('QC-2', '2026-11-21')])
    assert ledger.holds() == []
    assert ledger.verdict(PECTIN, lot='PJ-02', accepted_lots=['PJ-02']) == CLEAR


def test_late_release_cannot_override_newer_hold():
    # 解封单发生时间早于更新的停用单：即使后登记（迟到）也不能盖过停用
    ledger = HoldLedger([hold('QC-1', lots=['PJ-02'], when='2026-11-18'),
                         hold('QC-2', lots=['PJ-02'], when='2026-11-22'),
                         release('QC-LATE', '2026-11-19')])
    active = ledger.holds()
    assert [row['order_id'] for row in active] == ['QC-2']
    assert active[0]['stale_overridden'] == 1
    assert ledger.verdict(PECTIN, lot='PJ-02', accepted_lots=['PJ-02']) == HELD_LOT


def test_same_timestamp_uses_sequence_tiebreak():
    # 同刻：seq 大者生效
    ledger = HoldLedger([hold('QC-1', lots=['PJ-02'], when='2026-11-22', seq=1),
                         release('QC-2', '2026-11-22', seq=2)])
    assert ledger.holds() == []
    ledger = HoldLedger([release('QC-2', '2026-11-22', seq=1),
                         hold('QC-1', lots=['PJ-02'], when='2026-11-22', seq=2)])
    assert ledger.verdict(PECTIN, lot='PJ-02', accepted_lots=['PJ-02']) == HELD_LOT


def test_registration_order_does_not_revive_superseded_order():
    # 登记顺序与发生时间不一致时，仍以发生时间+seq 裁决；迟到单不改变当前状态
    ledger = HoldLedger([release('QC-2', '2026-11-22', seq=1),
                         hold('QC-1', lots=['PJ-02'], when='2026-11-22', seq=2)])
    late = release('QC-3', '2026-11-20')
    ledger.register(late)
    assert ledger.verdict(PECTIN, lot='PJ-02', accepted_lots=['PJ-02']) == HELD_LOT


def test_untraceable_lot_never_auto_released():
    # 旧领料单只剩供应商：供应商命中停用范围 -> 嫌疑；否则人工追溯，两者都不放行
    ledger = HoldLedger([hold('QC-1', suppliers=['供应商甲'])])
    assert ledger.verdict(PECTIN, supplier='供应商甲') == SUPPLIER_SUSPECT
    assert ledger.verdict(PECTIN, supplier='供应商乙') == UNTRACEABLE
    assert ledger.verdict(PECTIN) == UNTRACEABLE


def test_supplier_wide_hold_does_not_block_unrelated_known_lots():
    # 供应商级停用只在批号查不清时影响判定；能对上号且批号不在停用清单的照常放行
    ledger = HoldLedger([hold('QC-1', suppliers=['供应商甲'])])
    assert ledger.verdict(PECTIN, lot='PJ-09', supplier='供应商甲',
                          accepted_lots=['PJ-09']) == CLEAR
    assert ledger.block_lots(PECTIN, ['PJ-09']) == frozenset()


def test_lot_outside_accepted_list_is_rejected():
    ledger = HoldLedger()
    assert ledger.verdict(PECTIN, lot='PJ-404', accepted_lots=['PJ-01']) == LOT_NOT_ACCEPTED


def test_retry_registration_is_idempotent():
    ledger = HoldLedger()
    order = hold('QC-1', lots=['PJ-02'])
    first, fresh_one = ledger.register(order)
    second, fresh_two = ledger.register(order)
    assert (fresh_one, fresh_two) == (True, False)
    assert first == second
    assert len(ledger.orders()) == 1


def test_scope_validation():
    with pytest.raises(ValueError):
        HoldLedger([hold('QC-1')])                      # 停用单必须给出批号或供应商
    bad = [{'order_id': 'X', 'type': 'PAUSE', 'material': PECTIN, 'occurred_at': '2026-11-20',
            'reason': 'x', 'scope': {'lots': ['PJ-02']}}]
    with pytest.raises(ValueError):
        HoldLedger(bad)
    bad_date = dict(hold('QC-2', lots=['PJ-01']), occurred_at='20/11/2026')
    with pytest.raises(ValueError):
        HoldLedger([bad_date])


def test_round_trip_data():
    ledger = HoldLedger([hold('QC-1', lots=['PJ-02']), release('QC-2', '2026-11-23')])
    rebuilt = HoldLedger.from_data(ledger.to_data())
    assert rebuilt.orders() == ledger.orders()
