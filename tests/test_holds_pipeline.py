from app.input import load
from app.modules.holds.ledger import HOLD, HoldLedger
from app.pipeline import process


def hold(lots):
    return HoldLedger([{'order_id': 'QC-1', 'type': HOLD, 'material': '果胶',
                        'occurred_at': '2026-11-20', 'reason': '质检停用',
                        'scope': {'lots': lots, 'suppliers': []}}])


def test_new_trial_excludes_held_lot_from_solver():
    material = load('dirty')
    baseline = process(material)
    assert baseline['blend']['allocation'] == {'PJ-01': 5000, 'PJ-02': 5000}

    # 停用 PJ-03（留档未选用但可参与寻优的批号）：被排除且不影响原可行解
    gated = process(material, holds=hold(['PJ-03']))
    assert [row['lot'] for row in gated['holds']['excluded']] == ['PJ-03']
    assert 'PJ-03' not in gated['blend']['allocation']
    assert gated['blend']['allocation'] == {'PJ-01': 5000, 'PJ-02': 5000}


def test_held_lot_changes_solver_choice_without_blocking_unrelated_lots():
    material = load('dirty')
    gated = process(material, holds=hold(['PJ-01']))
    assert [row['lot'] for row in gated['holds']['excluded']] == ['PJ-01']
    # 停用批号被精确剔除；无关批号仍保留在可用清单中（质量不可行是约束本身所致，非全停误伤）
    remaining = [lot['lot'] for lot in gated['dry']['lots']]
    assert 'PJ-01' not in remaining and 'PJ-02' in remaining
    assert gated['blend']['allocation'] == {}


def test_held_lots_dropped_from_stock_balance():
    material = load('dirty')
    gated = process(material, holds=hold(['PJ-01']))
    assert all(row['lot'] != 'PJ-01' for row in gated['stock']['rows'])
    assert gated['stock']['balanced']


def test_without_ledger_pipeline_unchanged():
    material = load('dirty')
    result = process(material)
    assert result['holds'] == {'excluded': [], 'active': []}
