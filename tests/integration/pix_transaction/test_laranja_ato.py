from datetime import timedelta

import pytest

from tests.utils import DictMock, PixAccount, PixDestination, RandomGenerator
from tests.utils.assertions import assert_decision

REAL = 100
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def suspect_payer():
    """E4 sozinha permite outros atos, mas rejeita repasse aparente por L3."""
    payer = PixAccount()
    DictMock.mark(payer, open_reports=2)
    return payer


class TestPaymentContext:
    @pytest.mark.parametrize("amount,expected", [(100000, "approved"), (100001, "rejected")])
    def test_a_marked_payer_can_pay_a_known_recipient_only_up_to_the_typical_limit(self, amount, expected):
        payer, friend = PixAccount(), PixDestination()
        DictMock.unavailable(payer)
        payer.send(100 * REAL, -3 * HOUR, "approved", destination=friend)
        DictMock.mark(payer, mule=1)

        _, response = payer.pix(amount, destination=friend)

        assert_decision(response, expected, "POLICY_PASSED" if expected == "approved" else "MULE_PAYER")

    @pytest.mark.parametrize("age_days,expected", [(90, "approved"), (89, "rejected")])
    def test_a_marked_payer_can_pay_a_small_bill_only_to_an_established_company(self, age_days, expected):
        payer = PixAccount()
        DictMock.mark(payer, mule=1)
        company = PixDestination(age=age_days * DAY, document=RandomGenerator.generate_cnpj())

        _, response = payer.pix(500 * REAL, destination=company)

        assert_decision(response, expected, "POLICY_PASSED" if expected == "approved" else "MULE_PAYER")

    def test_a_marked_payer_cannot_treat_a_small_payment_to_a_stranger_as_a_typical_spend(self):
        payer = PixAccount()
        DictMock.mark(payer, mule=1)

        _, response = payer.pix(50 * REAL, destination=PixDestination(age=3650 * DAY))

        assert_decision(response, "rejected", "MULE_PAYER")

    @pytest.mark.parametrize("amount,expected", [(99999, "approved"), (100000, "rejected")])
    def test_a_suspect_payer_is_stopped_at_half_of_the_approved_incoming_amount(self, amount, expected):
        payer = suspect_payer()
        payer.fund(1000 * REAL, -30 * MINUTE)
        payer.fund(1000 * REAL, -20 * MINUTE)

        _, response = payer.pix(amount)

        assert_decision(response, expected, "POLICY_PASSED" if expected == "approved" else "SUSPECTED_MULE_FORWARDING")

    def test_splitting_a_forward_does_not_avoid_the_half_threshold(self):
        payer = suspect_payer()
        payer.fund(2000 * REAL, -30 * MINUTE)
        payer.send(600 * REAL, -10 * MINUTE, "approved")

        _, response = payer.pix(400 * REAL)

        assert_decision(response, "rejected", "SUSPECTED_MULE_FORWARDING")

    def test_a_suspect_payer_is_not_blocked_as_forwarding_below_the_minimum_incoming_amount(self):
        payer = suspect_payer()
        payer.fund(999 * REAL, -30 * MINUTE)

        _, response = payer.pix(900 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_old_receipts_do_not_block_a_current_payment_as_forwarding(self):
        payer = suspect_payer()
        payer.fund(3000 * REAL, -61 * MINUTE)

        _, response = payer.pix(2000 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    @pytest.mark.parametrize("incoming_status", ["rejected", "two_factor_required"])
    def test_an_unapproved_incoming_request_cannot_make_the_receiver_look_like_a_forwarder(self, incoming_status):
        payer = suspect_payer()
        sender = PixAccount(age=3 * DAY if incoming_status == "rejected" else 365 * DAY)
        amount = 1800 * REAL if incoming_status == "rejected" else 6000 * REAL
        sender.send(amount, -30 * MINUTE, incoming_status, destination=payer.as_destination())

        _, response = payer.pix(3000 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    @pytest.mark.parametrize("age_days,expected", [(89, "rejected"), (90, "approved")])
    def test_a_suspect_payer_can_forward_to_an_established_company_under_the_current_exception(self, age_days, expected):
        payer = suspect_payer()
        payer.fund(2000 * REAL, -30 * MINUTE)
        company = PixDestination(age=age_days * DAY, document=RandomGenerator.generate_cnpj())

        _, response = payer.pix(1500 * REAL, destination=company)

        assert_decision(response, expected, "POLICY_PASSED" if expected == "approved" else "SUSPECTED_MULE_FORWARDING")

    def test_a_clean_account_is_not_rejected_for_forwarding_alone(self):
        payer = PixAccount()
        payer.fund(2000 * REAL, -30 * MINUTE)

        _, response = payer.pix(1500 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")
