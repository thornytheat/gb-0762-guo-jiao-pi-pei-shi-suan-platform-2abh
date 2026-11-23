from flask import Blueprint, current_app, jsonify, request

from .errors import TrialError
from .input import from_request
from .modules.batches.service import preserve
from .modules.batches.storage import history, read
from .modules.certificate.service import issue_with_holds
from .modules.holds import store as hold_store
from .modules.holds.service import evaluate
from .pipeline import process

api = Blueprint('trial_api', __name__, url_prefix='/api')


def _ledger():
    return hold_store.load(current_app.config['HOLD_ROOT'])


def preview(stage):
    return process(from_request(), stage, holds=_ledger())[stage]


@api.post('/assay')
def assay():
    return preview('assay')


@api.post('/dry')
def dry():
    return preview('dry')


@api.post('/formula')
def formula():
    return preview('formula')


@api.post('/blend')
def blend():
    return preview('blend')


@api.post('/stock')
def stock():
    return preview('stock')


@api.post('/batches')
def batches():
    record, fresh = preserve(current_app.config['ARCHIVE'], from_request(),
                             hold_root=current_app.config['HOLD_ROOT'])
    return {'batch_id': record['batch_id'], 'created': fresh, 'record': record}, 201 if fresh else 200


@api.get('/batches')
def list_batches():
    return {'batches': history(current_app.config['ARCHIVE'])}


@api.get('/batches/<identifier>')
def batch(identifier):
    return read(current_app.config['ARCHIVE'], identifier)


@api.get('/certificate/<identifier>')
def certificate(identifier):
    return issue_with_holds(batch(identifier), _ledger())


@api.get('/export/<identifier>')
def export(identifier):
    response = jsonify(certificate(identifier))
    response.headers['Content-Disposition'] = f'attachment; filename="pectin-{identifier[:12]}.json"'
    return response


# ---- 来料停用台账 ----------------------------------------------------------

@api.get('/holds')
def list_holds():
    ledger = _ledger()
    return {'orders': ledger.orders(), 'active_holds': ledger.holds()}


@api.post('/holds')
def register_hold():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {'code': 'JSON_REQUIRED'}, 400
    try:
        record, fresh = hold_store.record(current_app.config['HOLD_ROOT'], body)
    except ValueError:
        return {'code': 'HOLD_ORDER_INVALID'}, 422
    return {'order': record, 'created': fresh, 'active_holds': _ledger().holds()}, 201 if fresh else 200


@api.post('/issuance/<identifier>')
def issuance(identifier):
    """留档试配随实际领用重新判断签发资格，原配料与余量仍可复核。"""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict) or set(body) - {'issuances'}:
        return {'code': 'ISSUANCE_BAD_PAYLOAD'}, 400
    try:
        return evaluate(read(current_app.config['ARCHIVE'], identifier), _ledger(), body.get('issuances'))
    except TrialError:
        raise
    except ValueError:
        return {'code': 'ISSUANCE_BAD_LINE'}, 422
