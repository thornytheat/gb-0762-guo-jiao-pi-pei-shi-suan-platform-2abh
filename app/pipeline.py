from .errors import TrialError
from .modules.assay.service import receive
from .modules.dry.service import convert
from .modules.formula.contract import normalize
from .modules.formula.service import inspect
from .modules.blend.service import select
from .modules.stock.balance import reconcile
from .modules.holds.gate import mark_held_lots
from .modules.holds.ledger import HoldLedger


def process(material, stage='archive', holds=None):
    if len(material['assays']) > 250_000:
        raise TrialError('ASSAYS_TOO_LARGE', 413)
    assays = receive(material['assays'])
    result = {'assay': assays}
    if stage == 'assay':
        return result
    ledger = holds if isinstance(holds, HoldLedger) else HoldLedger((holds or {}).get('orders', ()))
    plan = normalize(material.get('plan'))
    # 新试算排除停用原料：只剔除批号精确命中当前停用单的采信批。
    visible_lots, excluded = mark_held_lots(assays['lots'], ledger)
    result['holds'] = {'excluded': excluded, 'active': ledger.holds()}
    result['dry'] = convert(visible_lots, plan['as_of'])
    lots = result['dry']['lots']
    result['plan'] = plan
    if stage == 'dry':
        return result
    if stage in ('formula', 'archive'):
        result['formula'] = inspect(plan, lots, material.get('proposal', {}))
    if stage == 'formula':
        return result
    result['blend'] = select(plan, lots)
    if stage == 'blend':
        return result
    result['stock'] = reconcile(plan, lots, result['blend'])
    return result
