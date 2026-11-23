from app.input import load
from app.modules.holds.ledger import (CLEAR, HELD_LOT, HOLD, SUPPLIER_SUSPECT, UNTRACEABLE,
                                      HoldLedger)
from app.modules.holds.service import evaluate


def archived_dirty():
    from app.pipeline import process
    return {'batch_id': 'fixture-batch', 'stages': process(load('dirty'))}


def hold(order_id, lots=(), suppliers=(), when='2026-11-20'):
    return {'order_id': order_id, 'type': HOLD, 'material': '果胶', 'occurred_at': when,
            'reason': '质检停用', 'scope': {'lots': list(lots), 'suppliers': list(suppliers)}}


def test_clean_trial_issues_with_reason():
    pack = evaluate(archived_dirty())
    assert pack['can_issue'] and pack['status'] == 'ISSUABLE'
    assert {row['verdict'] for row in pack['lines']} == {CLEAR}
    assert all(row['reason'] for row in pack['lines'])


def test_held_allocation_withholds_certificate():
    record = archived_dirty()
    ledger = HoldLedger([hold('QC-1', lots=['PJ-01'])])
    pack = evaluate(record, ledger)
    assert not pack['can_issue'] and pack['blocked_count'] == 1
    line = next(row for row in pack['lines'] if row['lot'] == 'PJ-01')
    assert line['verdict'] == HELD_LOT and '停用' in line['reason']


def test_actual_issuance_rejudges_untraceable_supplier_line():
    record = archived_dirty()
    # 实际领料单只剩供应商：命中停用范围 -> 嫌疑追查，不能签发
    ledger = HoldLedger([hold('QC-1', suppliers=['供应商甲'])])
    actual = [{'lot': None, 'supplier': '供应商甲', 'grams': 2500}]
    pack = evaluate(record, ledger, actual)
    assert not pack['can_issue']
    assert pack['lines'][0]['verdict'] == SUPPLIER_SUSPECT

    # 批号查不清、供应商也不在任何停用范围：不自动放行，转人工追溯
    pack_unknown = evaluate(record, HoldLedger(), actual)
    assert pack_unknown['lines'][0]['verdict'] == UNTRACEABLE
    assert not pack_unknown['can_issue']


def test_original_allocation_and_stock_remain_reviewable():
    record = archived_dirty()
    ledger = HoldLedger([hold('QC-1', lots=['PJ-01'])])
    pack = evaluate(record, ledger)
    # 留档原件未被改写，原配料与余量仍可复核
    assert pack['review']['allocation'] == record['stages']['blend']['allocation']
    assert pack['review']['stock_rows'] == record['stages']['stock']['rows']
    assert record['stages']['blend']['allocation'] == {'PJ-01': 5000, 'PJ-02': 5000}


def test_infeasible_trial_cannot_issue_even_without_holds():
    record = archived_dirty()
    record['stages']['blend']['status'] = 'QUALITY_INFEASIBLE'
    pack = evaluate(record, HoldLedger())
    assert not pack['can_issue'] and not pack['base_trial_feasible']


def test_actual_issuance_validation():
    import pytest
    record = archived_dirty()
    with pytest.raises(ValueError):
        evaluate(record, HoldLedger(), [{'grams': 2500}])               # 批号供应商都缺
    with pytest.raises(ValueError):
        evaluate(record, HoldLedger(), [{'lot': 'PJ-01', 'grams': -1}])
