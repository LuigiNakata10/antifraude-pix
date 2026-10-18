from datetime import timedelta
from uuid import uuid4

import pytest

from tests.utils import DictMock, PixAccount, PixDestination, RandomGenerator
from tests.utils.assertions import assert_decision
from tests.utils.mule_scenarios import hub_receiving_from_new_senders

REAL = 100
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def company():
    return PixDestination(age=400 * DAY, document=RandomGenerator.generate_cnpj())


def reported_company():
    """E4 isolada não rejeita o ato escolhido. Somada a E2, L2 passa a rejeitá-lo."""
    receiver = PixAccount(age=400 * DAY, document=RandomGenerator.generate_cnpj())
    DictMock.mark(receiver, open_reports=2)
    return receiver


def marked_account_pays(receiver, amount, when, device_id=None):
    marked = PixAccount(device_id=device_id)
    DictMock.mark(marked, mule=1)
    marked.send(amount, when, "approved", destination=receiver.as_destination())
    return marked


def assert_reviewed_payment(account, expected):
    """Acima de R$ 1.000 para CNPJ antigo: outro ato, sem repasse ou gasto típico."""
    status, response = account.pix(1500 * REAL, destination=company())

    assert status == 201, response
    return assert_decision(response, expected, "POLICY_PASSED" if expected == "approved" else "MULE_PAYER")


class TestGraphDecisions:
    def test_the_upstream_payer_can_pay_while_the_receiver_of_marked_money_is_restricted(self):
        marked = PixAccount()
        victim, receiver = reported_company(), reported_company()
        DictMock.unavailable(marked)
        victim.send(100 * REAL, -3 * HOUR, "approved", destination=marked.as_destination())
        DictMock.mark(marked, mule=1)
        marked.send(900 * REAL, -HOUR, "approved", destination=receiver.as_destination())

        assert_reviewed_payment(victim, "approved")
        assert_reviewed_payment(receiver, "rejected")

    @pytest.mark.parametrize("counterparties,expected", [(9, "rejected"), (10, "approved")])
    def test_an_established_shop_with_enough_counterparties_is_not_restricted_by_e2(self, counterparties, expected):
        bakery = reported_company()
        for _ in range(counterparties - 1):
            bakery.fund(1 * REAL, -4 * HOUR)
        marked_account_pays(bakery, 900 * REAL, -3 * HOUR)

        assert_reviewed_payment(bakery, expected)

    @pytest.mark.parametrize(
        "marked_amount,clean_amount,expected",
        [(90000, 90000, "approved"), (90100, 89900, "rejected"), (100, 100000, "approved")],
        ids=["exactly-half", "above-half", "one-real-poisoning"],
    )
    def test_e2_restricts_only_when_marked_money_is_the_majority(self, marked_amount, clean_amount, expected):
        receiver = reported_company()
        receiver.fund(clean_amount, -3 * HOUR)
        marked_account_pays(receiver, marked_amount, -2 * HOUR)

        assert_reviewed_payment(receiver, expected)

    def test_expired_marked_receipts_stop_restricting_the_account(self):
        old, recent = reported_company(), reported_company()
        marked_account_pays(old, 900 * REAL, -31 * DAY)
        marked_account_pays(recent, 900 * REAL, -29 * DAY)

        assert_reviewed_payment(old, "approved")
        assert_reviewed_payment(recent, "rejected")

    def test_suspicion_does_not_spread_to_a_second_hop(self):
        first_hop, second_hop = reported_company(), reported_company()
        marked_account_pays(first_hop, 900 * REAL, -3 * HOUR)
        first_hop.send(900 * REAL, -HOUR, "approved", destination=second_hop.as_destination())

        assert_reviewed_payment(first_hop, "rejected")
        assert_reviewed_payment(second_hop, "approved")

    @pytest.mark.parametrize(
        "marked,age,expected",
        [(True, 3 * HOUR, "rejected"), (False, 3 * HOUR, "approved"), (True, 31 * DAY, "approved")],
        ids=["marked-device", "unmarked-device", "expired-device"],
    )
    def test_prior_shared_device_uses_restrict_only_with_a_current_marked_link(self, marked, age, expected):
        device = "dvc-graph-" + uuid4().hex
        first, receiver = PixAccount(device_id=device), reported_company()
        if marked:
            DictMock.mark(first, mule=1)
        first.send(100 * REAL, -age, "approved", destination=company())
        receiver.send(100 * REAL, -2 * HOUR, "approved", device_id=device, destination=company())

        assert_reviewed_payment(receiver, expected)

    @pytest.mark.parametrize(
        "holders,first_timers,expected",
        [(4, 4, "approved"), (5, 3, "rejected"), (5, 2, "approved")],
        ids=["few-holders", "concentrated-new-holders", "few-new-holders"],
    )
    def test_concentrated_receipts_restrict_a_forward_only_with_enough_new_holders(self, holders, first_timers, expected):
        payer = PixAccount()
        hub_receiving_from_new_senders(payer, senders=holders, first_time=first_timers, each=300 * REAL)

        _, response = payer.pix(1000 * REAL)

        assert_decision(response, expected, "POLICY_PASSED" if expected == "approved" else "SUSPECTED_MULE_FORWARDING")
