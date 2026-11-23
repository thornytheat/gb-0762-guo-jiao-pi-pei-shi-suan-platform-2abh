"""签发资格判定：留档试配随实际领用重新判断，原配料与余量仍可复核。"""

from .ledger import (CLEAR, HELD_LOT, LOT_NOT_ACCEPTED, MATERIAL_DEFAULT, RELEASE_VERDICTS,
                     SUPPLIER_SUSPECT, UNTRACEABLE, HoldLedger)

MATERIAL = MATERIAL_DEFAULT

REASON_TEXT = {
    CLEAR: '批号可对上且当前未停用，可放行',
    HELD_LOT: '批号命中当前停用单，暂缓签发',
    SUPPLIER_SUSPECT: '批号查不清但供应商在停用范围，转质量追查',
    UNTRACEABLE: '批号与停用范围均无法核对，转人工追溯后再判',
    LOT_NOT_ACCEPTED: '批号不在化验采信清单，不能凭此单签发',
}

# 试配留档中库存行 -> 实际领用条目的桥接字段
ISSUANCE_FIELDS = ('lot', 'supplier', 'grams')


def evaluate(record, ledger=None, issuances=None, material=MATERIAL):
    """对一份留档试配给出当前签发资格。

    record 原样保留，原配料和余量仍可复核；判定结果单独返回。实际领用清单
    缺省时按留档库存行中的计划领用逐条判定；提供实际领用后以实际领用为准。
    """
    ledger = ledger or HoldLedger()
    stock_rows = record['stages']['stock']['rows']
    accepted = {row['lot'] for row in stock_rows}
    lines = _lines_from_issuance(issuances, stock_rows)
    findings = []
    for line in lines:
        verdict = ledger.verdict(material, lot=line.get('lot'), supplier=line.get('supplier'),
                                 accepted_lots=accepted)
        findings.append({**line, 'verdict': verdict, 'reason': REASON_TEXT[verdict],
                         'held': verdict not in RELEASE_VERDICTS})
    base_feasible = _base_feasible(record)
    can_issue = base_feasible and all(row['verdict'] in RELEASE_VERDICTS for row in findings)
    return {
        'batch_id': record['batch_id'],
        'material': material,
        'can_issue': can_issue,
        'status': 'ISSUABLE' if can_issue else 'WITHHELD',
        'base_trial_feasible': base_feasible,
        'lines': findings,
        'blocked_count': sum(row['held'] for row in findings),
        'active_holds': ledger.holds(),
        'review': {
            'allocation': record['stages']['blend']['allocation'],
            'stock_rows': stock_rows,
            'note': '原配料与余量来自留档快照，仅用于复核；签发资格按当前停用台账重判。',
        },
    }


def _base_feasible(record):
    stages = record['stages']
    blend, stock = stages['blend'], stages['stock']
    return blend['status'] == 'FEASIBLE' and stock['balanced'] and stock['shortage_g'] == 0


def _lines_from_issuance(issuances, stock_rows):
    if issuances is None:
        return [{'lot': row['lot'], 'supplier': None, 'grams': row['issued_g'], 'source': 'ARCHIVED_PICK'}
                for row in stock_rows if row['issued_g'] > 0]
    lines = []
    for index, item in enumerate(issuances):
        if not isinstance(item, dict) or any(key not in item for key in ('grams',)):
            raise ValueError('ISSUANCE_BAD_LINE')
        lot = item.get('lot') or None
        supplier = item.get('supplier') or None
        if not lot and not supplier:
            raise ValueError('ISSUANCE_TRACE_MISSING')
        grams = item['grams']
        if type(grams) is not int or grams < 0:
            raise ValueError('ISSUANCE_BAD_GRAMS')
        lines.append({'lot': lot, 'supplier': supplier, 'grams': grams,
                      'source': item.get('source') or f'ACTUAL#{index + 1}'})
    return lines
