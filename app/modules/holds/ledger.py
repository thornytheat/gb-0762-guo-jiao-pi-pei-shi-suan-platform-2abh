"""来料停用台账。

停用单与解封单按发生时间逐条回放，同一物料的当前状态由最近一张有效单据决定；
迟到的解封记录不能盖过更新的停用单。旧领料单只有供应商、批号查不清时不直接
放行，转人工追查。登记按单据号幂等，重试不重复登记。
"""

from collections import OrderedDict

HOLD = 'HOLD'
RELEASE = 'RELEASE'
MATERIAL_DEFAULT = '果胶'
ORDER_TYPES = frozenset((HOLD, RELEASE))
# 可试配签发的追溯结论
CLEAR = 'CLEAR'                    # 批号可对上，且当前未停用
HELD_LOT = 'HELD_LOT'              # 批号直接命中当前停用
SUPPLIER_SUSPECT = 'SUPPLIER_SUSPECT'      # 批号查不清，供应商在停用范围
UNTRACEABLE = 'UNTRACEABLE'        # 批号查不清，供应商也无法关联停用范围
LOT_NOT_ACCEPTED = 'LOT_NOT_ACCEPTED'      # 批号不在当前化验采信清单
RELEASE_VERDICTS = frozenset((CLEAR,))


class HoldLedger:
    """内存台账。单据按 occurred_at 稳定排序后回放。"""

    def __init__(self, orders=()):
        self._orders = OrderedDict()      # order_id -> 原始单据
        for order in orders:
            self.register(order)

    # ---- 登记 -------------------------------------------------------------
    def register(self, order):
        """登记一张停用/解封单。重复单据号原样返回，不重复登记。"""
        record = normalize_order(order)
        existing = self._orders.get(record['order_id'])
        if existing is not None:
            return existing, False
        self._orders[record['order_id']] = record
        return record, True

    def orders(self):
        return [order for order in sorted(self._orders.values(),
                                          key=lambda row: (row['occurred_at'], row['seq'], row['order_id']))]

    # ---- 回放 -------------------------------------------------------------
    def _replay(self):
        """返回 {material: {'order': 最新单据, 'stale': 被压下的迟到单数}}。

        按登记顺序回放，只接受时间戳不早于已生效单据的新单；迟到单据（含解封
        单）即使晚登记也不会盖过更新的停用单。同刻单据用 seq 裁决。
        """
        current = {}
        for order in self._orders.values():
            slot = current.setdefault(order['material'], {'order': None, 'stale': 0})
            if slot['order'] is not None and (order['occurred_at'], order['seq']) <= (
                    slot['order']['occurred_at'], slot['order']['seq']):
                slot['stale'] += 1
                continue
            slot['order'] = order
        return current

    def holds(self):
        """当前仍在停用的物料视图。"""
        view = []
        for material, slot in self._replay().items():
            order = slot.get('order')
            if order is not None and order['type'] == HOLD:
                view.append({'material': material, 'scope': order['scope'], 'reason': order['reason'],
                             'order_id': order['order_id'], 'occurred_at': order['occurred_at'],
                             'stale_overridden': slot.get('stale', 0)})
        return sorted(view, key=lambda row: (row['occurred_at'], row['material']))

    def is_held_lot(self, material, lot):
        """批号是否被当前停用单精确命中。"""
        slot = self._replay().get(material)
        if slot is None or slot['order']['type'] != HOLD:
            return False
        return lot in slot['order']['scope'].get('lots', ())

    def supplier_held(self, material, supplier):
        """供应商是否落在当前停用范围。批号级停用不波及供应商追溯。"""
        if not supplier:
            return False
        slot = self._replay().get(material)
        if slot is None or slot['order']['type'] != HOLD:
            return False
        scope = slot['order']['scope']
        suppliers = scope.get('suppliers', ())
        if not suppliers:
            return False
        return supplier in suppliers

    # ---- 追溯判定 ---------------------------------------------------------
    def verdict(self, material, lot=None, supplier=None, accepted_lots=None):
        """判定一条用料记录能否放行。

        批号可对上时只看批号级命中；批号查不清时不做供应商全停，也不直接放行：
        供应商在停用范围内按嫌疑追查，否则留待人工追溯。
        """
        accepted = set(accepted_lots or ())
        if lot:
            if accepted and lot not in accepted:
                return LOT_NOT_ACCEPTED
            return HELD_LOT if self.is_held_lot(material, lot) else CLEAR
        if self.supplier_held(material, supplier):
            return SUPPLIER_SUSPECT
        return UNTRACEABLE

    def block_lots(self, material, lots):
        """新试算需要排除的批号集合：仅精确对得上当前停用单的批号。"""
        return frozenset(lot for lot in lots if self.is_held_lot(material, lot))

    def to_data(self):
        return {'orders': self.orders()}

    @classmethod
    def from_data(cls, data):
        return cls((data or {}).get('orders', ()))


def normalize_order(order):
    if not isinstance(order, dict):
        raise ValueError('HOLD_ORDER_REQUIRED')
    required = ('order_id', 'type', 'material', 'occurred_at', 'reason')
    if any(not str(order.get(key, '')).strip() for key in required):
        raise ValueError('HOLD_ORDER_FIELD_MISSING')
    order_type = order['type']
    if order_type not in ORDER_TYPES:
        raise ValueError('HOLD_ORDER_TYPE_UNKNOWN')
    occurred = str(order['occurred_at']).strip()
    if len(occurred) != 10 or occurred[4] != '-' or occurred[7] != '-':
        raise ValueError('HOLD_ORDER_BAD_DATE')
    year, month, day = (int(part) for part in occurred.split('-'))
    if not (1 <= month <= 12 and 1 <= day <= 31 and year >= 2000):
        raise ValueError('HOLD_ORDER_BAD_DATE')
    scope = order.get('scope') or {}
    if not isinstance(scope, dict):
        raise ValueError('HOLD_ORDER_BAD_SCOPE')
    lots = _scope_list(scope.get('lots'), 'HOLD_ORDER_BAD_SCOPE')
    suppliers = _scope_list(scope.get('suppliers'), 'HOLD_ORDER_BAD_SCOPE')
    if order_type == HOLD and not lots and not suppliers:
        raise ValueError('HOLD_ORDER_SCOPE_EMPTY')
    seq = order.get('seq', 0)
    if type(seq) is not int or seq < 0:
        raise ValueError('HOLD_ORDER_BAD_SEQ')
    return {'order_id': str(order['order_id']).strip(), 'type': order_type,
            'material': str(order['material']).strip(), 'occurred_at': occurred,
            'reason': str(order['reason']).strip(), 'scope': {'lots': lots, 'suppliers': suppliers},
            'seq': seq}


def _scope_list(value, error):
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or any(not str(item).strip() for item in value):
        raise ValueError(error)
    return tuple(str(item).strip() for item in value)
