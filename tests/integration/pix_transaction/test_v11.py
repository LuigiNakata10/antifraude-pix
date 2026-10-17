from datetime import timedelta
from urllib.parse import quote
from uuid import uuid4

import pytest

from tests.utils import DbUtils, DictMock, PixAccount, PixDestination, RandomGenerator, RequestGenerator
from tests.utils.assertions import assert_decision
from tests.utils.mule_scenarios import hub_receiving_from_new_senders

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)
REAL = 100


def company():
    return PixDestination(document=RandomGenerator.generate_cnpj(), age=400 * DAY)


@pytest.mark.parametrize('field', ['id', 'channel', 'device_id'])
@pytest.mark.parametrize('character', ['\x00', '\ud800'])
def test_invalid_text_is_400_and_does_not_count(field, character):
    payer = PixAccount()
    body = payer.payload(100)
    if field == 'id':
        body['id'] += character
    else:
        body['source'][field] += character
    status, _ = RequestGenerator.POST_pix_transaction(body)
    assert status == 400
    for _ in range(2):
        payer.send(100, timedelta(0), 'approved')


def test_get_invalid_text_is_400():
    status, _ = RequestGenerator.GET_pix_transaction(quote('invalid-\x00-id', safe=''))
    assert status == 400


def test_p14_E3_and_E5_do_not_elevate_suspicion():
    young = PixAccount(age=3 * DAY)
    hub_receiving_from_new_senders(young, senders=5, first_time=5, each=1300 * REAL)
    response, transaction_id = young.record(60 * REAL, destination=company())
    assert_decision(response, 'approved', 'POLICY_PASSED')
    assert DbUtils.analysis_row(transaction_id)['analysis_details']['payer'] == {
        'state': 'suspeita', 'evidences': ['E3', 'E5']}


def test_p16_forwarding_prevails_over_known_destination():
    payer, friend = PixAccount(), PixDestination()
    payer.send(100, -2 * DAY, 'approved', destination=friend)
    hub_receiving_from_new_senders(payer, senders=5, first_time=5, each=200 * REAL)
    _, response = payer.pix(600 * REAL, destination=friend)
    assert_decision(response, 'rejected', 'SUSPECTED_MULE_FORWARDING')
    assert response['metadata']['reason']['act'] == 'repasse_aparente'
    assert response['metadata']['reason']['incoming_amount_1h'] == 100000
    assert response['metadata']['reason']['projected_outgoing_amount_1h'] == 60000


def test_p17_small_incoming_does_not_create_forwarding():
    payer = PixAccount()
    hub_receiving_from_new_senders(payer, senders=5, first_time=5, each=120 * REAL)
    response, transaction_id = payer.record(400 * REAL)
    assert_decision(response, 'approved', 'POLICY_PASSED')
    assert DbUtils.analysis_row(transaction_id)['analysis_details']['act'] == 'outro'


def test_p18_unknown_local_start_cannot_establish_prior_relationship():
    receiver = PixAccount(document=RandomGenerator.generate_cnpj())
    mother = PixAccount()
    mother.send(100, -60 * DAY, 'approved', destination=receiver.as_destination())
    marked = PixAccount()
    DictMock.mark(marked, mule=1)
    marked.send(900 * REAL, -2 * HOUR, 'approved', destination=receiver.as_destination())
    DictMock.mark(receiver, open_reports=2)
    _, response = mother.pix(100 * REAL, destination=receiver.as_destination())
    assert_decision(response, 'rejected', 'MULE_DESTINATION')


def test_shared_device_needs_previous_approvals_from_both_accounts():
    device = 'v11-' + uuid4().hex
    marked, payer = PixAccount(device_id=device), PixAccount(device_id=device)
    DictMock.mark(marked, mule=1)
    DictMock.mark(payer, open_reports=2)
    marked.send(100, -3 * HOUR, 'approved', destination=company())
    payer.send(1500 * REAL, -10 * MINUTE, 'approved')
    _, response = payer.pix(1500 * REAL)
    assert_decision(response, 'rejected', 'MULE_PAYER')


@pytest.mark.parametrize('counters', [{'mule': 1}, {'reporters': 2}])
def test_E1_reason_has_counts_and_window(counters):
    target = PixDestination()
    DictMock.mark(target, **counters)
    _, response = PixAccount().pix(100, destination=target)
    reason = assert_decision(response, 'rejected', 'MULE_DESTINATION')
    assert reason['evidence_values']['E1']['window_days'] == 90
    assert reason['evidence_values']['E1']['minimum_reporters'] == 2
    assert reason['evidence_values']['E1']['distinct_reporters'] == counters.get('reporters', 0)
    assert target.document not in str(reason)


@pytest.mark.parametrize('status,expected_edges', [('approved', 4), ('two_factor_required', 0), ('rejected', 0)])
def test_only_approved_analyses_create_graph_edges(status, expected_edges):
    payer = PixAccount(age=3 * DAY if status == 'rejected' else 365 * DAY)
    amount = {'approved': 100, 'two_factor_required': 600000, 'rejected': 100001}[status]
    response, transaction_id = payer.record(amount)
    assert response['status'] == status
    assert len(DbUtils.links_of(transaction_id)) == expected_edges


def test_p15_E2_plus_E4_elevates_and_rejects_other_act():
    receiver = PixAccount(document=RandomGenerator.generate_cnpj())
    marked = PixAccount()
    DictMock.mark(marked, mule=1)
    DictMock.mark(receiver, open_reports=2)
    marked.send(900 * REAL, -2 * HOUR, 'approved', destination=receiver.as_destination())
    response, transaction_id = receiver.record(1500 * REAL)
    assert_decision(response, 'rejected', 'MULE_PAYER')
    assert DbUtils.analysis_row(transaction_id)['analysis_details']['payer'] == {
        'state': 'suspeita_elevada', 'evidences': ['E2', 'E4']}


@pytest.mark.parametrize('holders,first,expected', [(5, 3, 'nao'), (30, 3, 'suspeita')])
def test_p19_CNPJ_requires_30_holders_but_only_three_new(holders, first, expected):
    payer = PixAccount(document=RandomGenerator.generate_cnpj())
    hub_receiving_from_new_senders(payer, senders=holders, first_time=first, each=10 * REAL)
    _, transaction_id = payer.record(100)
    assert DbUtils.analysis_row(transaction_id)['analysis_details']['payer']['state'] == expected


def test_p20_paying_a_marked_account_does_not_propagate_E2_upstream():
    payer, recipient = PixAccount(), PixDestination()
    payer.send(100, -2 * DAY, 'approved', destination=recipient)
    DictMock.mark(recipient, mule=1)
    response, transaction_id = payer.record(1500 * REAL)
    assert_decision(response, 'approved', 'POLICY_PASSED')
    assert DbUtils.analysis_row(transaction_id)['analysis_details']['payer'] == {'state': 'nao', 'evidences': []}


@pytest.mark.parametrize('field', ['opening_date', 'document'])
def test_payer_identity_cannot_change_to_bypass_rules(field):
    payer = PixAccount(age=3 * DAY)
    payer.send(1000 * REAL, -10 * MINUTE, 'approved')
    body = payer.payload(1000 * REAL)
    if field == 'opening_date':
        body['source_account']['opening_date'] = PixAccount().opening_date
    else:
        body['source_account']['owner']['document_number'] = RandomGenerator.generate_cpf()
    status, response = RequestGenerator.POST_pix_transaction(body)
    assert status == 422
    assert response['code'] == 'QIT003007'
    assert RequestGenerator.GET_pix_transaction(body['id'])[0] == 404


def test_reputation_uses_only_counterparties_from_30_days():
    receiver = PixAccount(document=RandomGenerator.generate_cnpj())
    for _ in range(9):
        receiver.fund(100, -31 * DAY)
    marked = PixAccount()
    DictMock.mark(marked, mule=1)
    marked.send(900 * REAL, -2 * HOUR, 'approved', destination=receiver.as_destination())
    _, transaction_id = receiver.record(100)
    assert DbUtils.analysis_row(transaction_id)['analysis_details']['payer'] == {
        'state': 'suspeita', 'evidences': ['E2']}


def test_rejected_use_of_marked_device_does_not_propagate_E2():
    device = 'rejected-' + uuid4().hex
    marked, payer = PixAccount(device_id=device), PixAccount(device_id=device)
    DictMock.mark(marked, mule=1)
    marked.send(1000001, -3 * HOUR, 'rejected')
    payer.send(100, -2 * HOUR, 'approved')
    _, transaction_id = payer.record(100)
    assert DbUtils.analysis_row(transaction_id)['analysis_details']['payer'] == {'state': 'nao', 'evidences': []}
