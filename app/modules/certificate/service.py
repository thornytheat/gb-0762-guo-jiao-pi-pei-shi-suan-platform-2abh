from app.modules.batches.seal import canonical, sha
from app.modules.holds.ledger import HoldLedger
from app.modules.holds.service import evaluate


def issue(record):
    stages = record['stages']
    stock = stages['stock']
    blend = stages['blend']
    return {'batch_id': record['batch_id'], 'integrity_sha256': sha(canonical(record)),
            'can_trial': blend['status'] == 'FEASIBLE' and stock['balanced'] and stock['shortage_g'] == 0,
            'stock_lines': len(stock['rows']), 'isolation_lines': len(stages['assay']['isolated']), 'record': record}


def issue_with_holds(record, ledger=None, issuances=None):
    """签发页证据：保留原 can_trial，再附当前停用状态、原因与逐行追溯结论。"""
    pack = issue(record)
    pack['issuance'] = evaluate(record, ledger or HoldLedger(), issuances)
    pack['can_issue'] = pack['issuance']['can_issue']
    return pack
