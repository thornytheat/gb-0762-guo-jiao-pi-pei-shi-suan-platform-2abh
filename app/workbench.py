import json

from flask import Blueprint, abort, current_app, render_template, request

from .config import REVISION
from .errors import TrialError
from .input import load
from .modules.batches.service import preserve
from .modules.batches.storage import history, read
from .modules.certificate.service import issue_with_holds
from .modules.holds import store as hold_store
from .pipeline import process
from .stages import LABELS, PLAN_FIELDS, STAGES

station = Blueprint('station', __name__)


def materials(mode):
    if mode != 'custom':
        return load(mode)
    try:
        proposal = json.loads(request.form.get('proposal', '{}'))
    except ValueError:
        raise TrialError('BAD_PROPOSAL_JSON') from None
    return {'assays': request.form.get('assays', ''), 'plan': {key: request.form.get(key, '') for key in PLAN_FIELDS},
            'proposal': proposal}


@station.route('/', methods=['GET', 'POST'])
@station.route('/trial/<stage>', methods=['GET', 'POST'])
def review(stage='stock'):
    if stage not in LABELS:
        abort(404)
    mode = request.values.get('sample', 'dirty')
    data, pack, error, record, entries, fresh = {}, None, None, None, [], False
    hold_error, hold_fresh, hold_view = None, False, None
    root = current_app.config['ARCHIVE']
    hold_root = current_app.config['HOLD_ROOT']
    source = {}
    try:
        ledger = hold_store.load(hold_root)
        source = materials(mode)
        if stage == 'holds':
            if request.method == 'POST':
                order = _hold_form(request.form)
                _, hold_fresh = hold_store.record(hold_root, order)
                ledger = hold_store.load(hold_root)
            hold_view = {'orders': ledger.orders(), 'active_holds': ledger.holds()}
        elif stage in ('batches', 'certificate'):
            if stage == 'batches' and request.method == 'POST':
                record, fresh = preserve(root, source, hold_root=hold_root)
            entries = history(root)
            if stage == 'certificate' and (entries or request.args.get('batch')):
                target = read(root, request.args.get('batch') or entries[0]['batch_id'])
                pack = issue_with_holds(target, ledger)
        else:
            data = process(source, stage, holds=ledger)
    except TrialError as exc:
        error = exc.code
    except ValueError:
        hold_error = 'HOLD_ORDER_INVALID'
    form_plan = request.form if mode == 'custom' else source.get('plan', {})
    form_assays = request.form.get('assays', '') if mode == 'custom' else source.get('assays', '')
    form_proposal = request.form.get('proposal', '{}') if mode == 'custom' else json.dumps(source.get('proposal', {}))
    return render_template('station.html', stages=STAGES, labels=LABELS, fields=PLAN_FIELDS,
                           revision=REVISION, stage=stage, mode=mode, data=data, error=error,
                           form_plan=form_plan, form_assays=form_assays, form_proposal=form_proposal,
                           record=record, fresh=fresh, entries=entries, pack=pack,
                           hold_view=hold_view, hold_error=hold_error, hold_fresh=hold_fresh)


def _hold_form(form):
    def split(value):
        return [item.strip() for item in value.replace('，', ',').split(',') if item.strip()]

    return {'order_id': form.get('order_id', ''), 'type': form.get('type', 'HOLD'),
            'material': form.get('material', '果胶') or '果胶',
            'occurred_at': form.get('occurred_at', ''), 'reason': form.get('reason', ''),
            'scope': {'lots': split(form.get('lots', '')), 'suppliers': split(form.get('suppliers', ''))}}
