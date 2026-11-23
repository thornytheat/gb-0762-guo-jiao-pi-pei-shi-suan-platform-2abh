"""把停用台账接进试算流水线：新试算排除停用原料。"""

from .ledger import MATERIAL_DEFAULT


def mark_held_lots(lots, ledger, material=MATERIAL_DEFAULT):
    """在干物折算前标记停用批号，返回 (lots, 排除清单)。

    只排除批号与当前停用单精确对得上的记录；批号查不清的旧料不在这里处理，
    留到签发环节按实际领用追溯。
    """
    blocked = ledger.block_lots(material, [lot['lot'] for lot in lots])
    active = {hold['material']: hold for hold in ledger.holds()}
    visible, excluded = [], []
    for lot in lots:
        if lot['lot'] in blocked:
            hold = active.get(material, {})
            excluded.append({'lot': lot['lot'], 'line': lot['line'], 'code': 'QC_HELD',
                             'order_id': hold.get('order_id'), 'reason': hold.get('reason')})
            continue
        visible.append(lot)
    return visible, excluded
