import json


def hold_payload(oid, lots=None, suppliers=None, when='2026-11-20', otype='HOLD'):
    return {'order_id': oid, 'type': otype, 'material': '果胶', 'occurred_at': when,
            'reason': '质检停用', 'scope': {'lots': lots or [], 'suppliers': suppliers or []}}


def test_hold_registration_is_idempotent_over_api(client):
    one = client.post('/api/holds', json=hold_payload('QC-1', lots=['PJ-02']))
    two = client.post('/api/holds', json=hold_payload('QC-1', lots=['PJ-02']))
    assert (one.status_code, two.status_code, two.json['created']) == (201, 200, False)
    listing = client.get('/api/holds').json
    assert len(listing['orders']) == 1
    assert listing['active_holds'][0]['order_id'] == 'QC-1'


def test_invalid_hold_order_rejected_without_side_effect(client):
    reply = client.post('/api/holds', json={'order_id': 'bad'})
    assert reply.status_code == 422 and reply.json['code'] == 'HOLD_ORDER_INVALID'
    assert client.get('/api/holds').json['orders'] == []


def test_hold_excludes_lot_from_new_trial_via_api(client):
    baseline = client.post('/api/blend', json={'sample': 'dirty'}).json
    assert 'PJ-03' not in baseline['allocation']
    client.post('/api/holds', json=hold_payload('QC-1', lots=['PJ-03']))
    stock = client.post('/api/stock', json={'sample': 'dirty'}).json
    assert all(row['lot'] != 'PJ-03' for row in stock['rows'])


def test_certificate_page_carries_current_status_and_reason(client):
    batch = client.post('/api/batches', json={'sample': 'dirty'}).json['batch_id']
    client.post('/api/holds', json=hold_payload('QC-1', lots=['PJ-01']))
    pack = client.get(f'/api/certificate/{batch}').json
    assert pack['can_trial']                      # 留档结论保持不变，仍可复核
    issuance = client.post(f'/api/issuance/{batch}', json={}).json
    assert issuance['status'] == 'WITHHELD' and not issuance['can_issue']
    line = next(row for row in issuance['lines'] if row['lot'] == 'PJ-01')
    assert line['verdict'] == 'HELD_LOT' and line['reason']
    # 原配料与余量仍可复核
    assert issuance['review']['allocation'] == {'PJ-01': 5000, 'PJ-02': 5000}


def test_release_order_restores_issuance_eligibility(client):
    batch = client.post('/api/batches', json={'sample': 'dirty'}).json['batch_id']
    client.post('/api/holds', json=hold_payload('QC-1', lots=['PJ-01'], when='2026-11-20'))
    assert client.post(f'/api/issuance/{batch}', json={}).json['status'] == 'WITHHELD'
    client.post('/api/holds', json=hold_payload('QC-2', when='2026-11-22', otype='RELEASE'))
    verdict = client.post(f'/api/issuance/{batch}', json={}).json
    assert verdict['status'] == 'ISSUABLE' and verdict['blocked_count'] == 0


def test_late_release_keeps_newer_hold_through_api(client):
    batch = client.post('/api/batches', json={'sample': 'dirty'}).json['batch_id']
    client.post('/api/holds', json=hold_payload('QC-1', lots=['PJ-01'], when='2026-11-20'))
    client.post('/api/holds', json=hold_payload('QC-2', when='2026-11-23', otype='RELEASE'))
    client.post('/api/holds', json=hold_payload('QC-3', lots=['PJ-01'], when='2026-11-25'))
    # 迟到的解封（发生在最新停用之前）登记成功但不改变停用状态
    client.post('/api/holds', json=hold_payload('QC-LATE', when='2026-11-24', otype='RELEASE'))
    assert client.post(f'/api/issuance/{batch}', json={}).json['status'] == 'WITHHELD'


def test_actual_issuance_with_supplier_only_is_traceable(client):
    batch = client.post('/api/batches', json={'sample': 'dirty'}).json['batch_id']
    client.post('/api/holds', json=hold_payload('QC-1', suppliers=['供应商甲']))
    reply = client.post(f'/api/issuance/{batch}',
                        json={'issuances': [{'supplier': '供应商甲', 'grams': 2500}]})
    assert reply.json['lines'][0]['verdict'] == 'SUPPLIER_SUSPECT'
    assert not reply.json['can_issue']


def test_bad_issuance_payload_returns_named_error(client):
    batch = client.post('/api/batches', json={'sample': 'dirty'}).json['batch_id']
    reply = client.post(f'/api/issuance/{batch}', json={'issuances': [{'grams': 1}]})
    assert reply.status_code == 422 and reply.json['code'] == 'ISSUANCE_BAD_LINE'


def test_issuance_unknown_batch_keeps_404(client):
    reply = client.post('/api/issuance/nope', json={})
    assert reply.status_code == 404 and reply.json['code'] == 'BATCH_NOT_FOUND'


def test_holds_page_renders(client):
    client.post('/api/holds', json=hold_payload('QC-1', lots=['PJ-02']))
    page = client.get('/trial/holds')
    assert page.status_code == 200 and '来料停用台账'.encode() in page.data
    cert_page = client.get('/trial/certificate')
    assert cert_page.status_code == 200


def test_hold_ledger_persists_across_app_instances(tmp_path, client):
    client.post('/api/holds', json=hold_payload('QC-1', lots=['PJ-02']))
    from app.main import create_app
    second = create_app(tmp_path / 'archive').test_client()
    assert second.get('/api/holds').json['active_holds'][0]['order_id'] == 'QC-1'
