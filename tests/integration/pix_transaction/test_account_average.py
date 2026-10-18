from datetime import timedelta

import pytest

from tests.utils import DbUtils, DictMock, PixAccount, PixDestination, RequestGenerator
from tests.utils.assertions import assert_decision

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)
SECOND = timedelta(seconds=1)
REAL = 100
AVERAGE_REASON = "AMOUNT_ABOVE_ACCOUNT_AVERAGE"


class TestAccountAverage:
    """R5: Pix acima de dez vezes o maior entre a média histórica e R$ 500."""

    @pytest.mark.parametrize(
        "history,amount,expected",
        [
            ([400 * REAL], 9000 * REAL, "two_factor_required"),
            ([500 * REAL], 9000 * REAL, "two_factor_required"),
            ([50001], 500010, "approved"),
            ([50001], 500011, "two_factor_required"),
            ([600 * REAL], 6000 * REAL - 1, "approved"),
            ([600 * REAL], 6000 * REAL, "approved"),
            ([600 * REAL], 6000 * REAL + 1, "two_factor_required"),
            ([50000, 50001], 500005, "approved"),
            ([50000, 50001], 500006, "two_factor_required"),
        ],
        ids=["average-below-floor", "average-exact-floor", "above-floor-exact-ten-times",
             "above-floor-above-ten-times", "below-ten-times", "exact-ten-times", "above-ten-times",
             "fractional-average-equal", "fractional-average-above"],
    )
    def test_reference_uses_the_floor_and_the_average_is_not_rounded(self, history, amount, expected):
        account = PixAccount()
        for index, previous_amount in enumerate(history):
            account.send(previous_amount, -(len(history) - index) * DAY, "approved")

        status, response = account.pix(amount)

        assert status == 201, response
        assert_decision(response, expected, AVERAGE_REASON if expected == "two_factor_required" else "POLICY_PASSED")

    def test_without_approved_history_the_rule_does_not_intervene(self):
        _, response = PixAccount().pix(4000 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_only_two_factor_history_does_not_create_an_average(self):
        account = PixAccount()
        account.send(6000 * REAL, -3 * HOUR, "two_factor_required")

        _, response = account.pix(4000 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_the_current_pix_is_excluded_and_the_reason_explains_the_average(self):
        account = PixAccount()
        account.send(1000 * REAL, -3 * DAY, "approved")
        account.send(2000 * REAL, -2 * DAY, "approved")

        _, response = account.pix(15000 * REAL + 1)

        reason = assert_decision(response, "two_factor_required", AVERAGE_REASON)
        assert reason["observed_amount"] == 1500001
        assert reason["historical_total_amount"] == 300000
        assert reason["historical_transaction_count"] == 2
        assert reason["average_multiplier"] == 10
        assert reason["reference_floor_amount"] == 50000

    def test_all_observed_approved_history_counts_even_outside_24_hours(self):
        account = PixAccount()
        account.send(3000 * REAL, -100 * DAY, "approved")
        account.send(600 * REAL, -2 * DAY, "approved")

        _, response = account.pix(9000 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_rejected_and_two_factor_requests_do_not_inflate_the_average(self):
        account = PixAccount()
        account.send(600 * REAL, -2 * DAY, "approved")
        account.send(20001 * REAL, -3 * HOUR, "rejected")
        account.send(6000 * REAL, -2 * HOUR, "two_factor_required", device_id="new-average-device")

        _, response = account.pix(7000 * REAL)

        reason = assert_decision(response, "two_factor_required", AVERAGE_REASON)
        assert reason["historical_total_amount"] == 600 * REAL
        assert reason["historical_transaction_count"] == 1

    def test_incoming_pix_do_not_inflate_the_payers_average(self):
        account = PixAccount()
        account.send(600 * REAL, -2 * DAY, "approved")
        account.fund(4000 * REAL, -HOUR)

        _, response = account.pix(7000 * REAL)

        assert_decision(response, "two_factor_required", AVERAGE_REASON)

    def test_the_average_is_per_account_even_when_the_holder_is_the_same(self):
        account = PixAccount()
        account.send(600 * REAL, -2 * DAY, "approved")
        other_account = PixAccount(document=account.document)
        other_account.send(4000 * REAL, -HOUR, "approved")

        _, response = account.pix(7000 * REAL)

        assert_decision(response, "two_factor_required", AVERAGE_REASON)

    def test_a_previous_approval_at_the_same_transaction_date_counts(self):
        account = PixAccount()
        account.send(600 * REAL, -2 * DAY, "approved")
        account.send(600 * REAL, timedelta(0), "approved")

        _, response = account.pix(7000 * REAL)

        reason = assert_decision(response, "two_factor_required", AVERAGE_REASON)
        assert reason["historical_transaction_count"] == 2

    def test_replays_do_not_duplicate_the_average_and_the_decision_is_stored(self):
        account = PixAccount()
        original = account.payload(1800 * REAL, -3 * DAY)
        assert RequestGenerator.POST_pix_transaction(original)[0] == 201
        assert RequestGenerator.POST_pix_transaction(original)[0] == 200
        account.send(600 * REAL, -2 * DAY, "approved")
        payload = account.payload(12000 * REAL + 1)

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201, response
        reason = assert_decision(response, "two_factor_required", AVERAGE_REASON)
        assert reason["historical_total_amount"] == 2400 * REAL
        assert reason["historical_transaction_count"] == 2
        assert RequestGenerator.GET_pix_transaction(payload["id"]) == (200, response)
        assert RequestGenerator.POST_pix_transaction(payload) == (200, response)
        assert DbUtils.links_of(payload["id"]) == []

        _, later = account.pix(15000 * REAL, 3 * MINUTE)
        later_reason = assert_decision(later, "two_factor_required", AVERAGE_REASON)
        assert later_reason["historical_total_amount"] == 2400 * REAL
        assert later_reason["historical_transaction_count"] == 2


class TestAccountAveragePrecedence:
    def test_the_new_account_rejection_precedes_the_average(self):
        account = PixAccount(age=3 * DAY)
        account.send(600 * REAL, -DAY, "approved")

        _, response = account.pix(7000 * REAL)

        assert_decision(response, "rejected", "NEW_ACCOUNT_LIMIT_EXCEEDED")

    def test_the_daily_rejection_precedes_the_average(self):
        account = PixAccount()
        account.send(1000 * REAL, -2 * DAY, "approved")

        _, response = account.pix(20001 * REAL)

        assert_decision(response, "rejected", "DAILY_LIMIT_EXCEEDED")

    def test_a_marked_destination_rejection_precedes_the_average(self):
        account, destination = PixAccount(), PixDestination()
        account.send(600 * REAL, -2 * DAY, "approved")
        DictMock.mark(destination, mule=1)

        _, response = account.pix(7000 * REAL, destination=destination)

        assert_decision(response, "rejected", "MULE_DESTINATION")

    def test_the_existing_new_device_reason_is_preserved(self):
        account = PixAccount()
        account.send(600 * REAL, -2 * DAY, "approved")

        _, response = account.pix(7000 * REAL, device_id="new-average-device")

        assert_decision(response, "two_factor_required", "NEW_DEVICE_HIGH_AMOUNT")

    def test_the_existing_frequency_reason_is_preserved(self):
        account = PixAccount()
        account.send(600 * REAL, -2 * DAY, "approved")
        account.send(600 * REAL, -80 * SECOND, "approved")
        account.send(600 * REAL, -40 * SECOND, "approved")

        _, response = account.pix(7000 * REAL)

        assert_decision(response, "two_factor_required", "HIGH_FREQUENCY")
