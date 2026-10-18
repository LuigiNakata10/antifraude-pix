import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text

from tests.utils import DbUtils, DictMock, PixAccount, PixDestination, RequestGenerator
from tests.utils.assertions import assert_decision
from tests.utils.dict_mock import statistics

DAY = timedelta(days=1)
MINUTE = timedelta(minutes=1)
REAL = 100


def seed_dict_cache(account, body, age):
    """Controla só o relógio do cache sem esperar minutos. Histórico financeiro continua vindo da API."""
    engine = create_engine(DbUtils.database_url())
    fetched_at = datetime.now(timezone.utc) - age
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO dict_lookup (account_key, response, fetched_at) "
                     "VALUES (:key, CAST(:response AS jsonb), :fetched_at)"),
                {"key": account.key, "response": json.dumps(body),
                 "fetched_at": fetched_at},
            )
    finally:
        engine.dispose()
    return fetched_at


class TestAverageReferenceFloor:
    def test_a_small_payment_cannot_disable_the_average_rule(self):
        account = PixAccount()
        account.send(600 * REAL, -2 * DAY, "approved")
        account.send(1 * REAL, -10 * MINUTE, "approved")

        _, response = account.pix(15000 * REAL)

        reason = assert_decision(response, "two_factor_required", "AMOUNT_ABOVE_ACCOUNT_AVERAGE")
        assert reason["historical_total_amount"] == 601 * REAL
        assert reason["historical_transaction_count"] == 2
        assert reason["reference_floor_amount"] == 500 * REAL

    @pytest.mark.parametrize("amount,expected", [(500000, "approved"), (500001, "two_factor_required")])
    def test_low_average_uses_a_five_thousand_two_factor_threshold(self, amount, expected):
        account = PixAccount()
        account.send(50 * REAL, -2 * DAY, "approved")

        _, response = account.pix(amount)

        assert_decision(response, expected, "POLICY_PASSED" if expected == "approved" else "AMOUNT_ABOVE_ACCOUNT_AVERAGE")


class TestInvalidInputs:
    def test_self_payment_is_422_and_does_not_consume_attempts_or_history(self):
        account = PixAccount()
        payload = account.payload(100 * REAL, destination=account.as_destination())

        for _ in range(3):
            status, response = RequestGenerator.POST_pix_transaction(payload)
            assert status == 422, response
            assert response["code"] == "QIT003008"
        assert RequestGenerator.GET_pix_transaction(payload["id"])[0] == 404
        account.send(100 * REAL, timedelta(0), "approved")
        account.send(100 * REAL, timedelta(0), "approved")

    def test_two_distinct_accounts_of_the_same_holder_are_allowed(self):
        payer = PixAccount()
        destination = PixAccount(document=payer.document).as_destination()

        status, response = payer.pix(100 * REAL, destination=destination)

        assert status == 201
        assert_decision(response, "approved", "POLICY_PASSED")

    @pytest.mark.parametrize("date", [
        "0001-01-01T00:00:00+01:00",
        "0001-01-15T00:00:00+00:00",
        "9999-12-31T23:59:59-01:00",
    ])
    def test_date_outside_supported_arithmetic_is_422(self, date):
        payload = PixAccount().payload(100 * REAL)
        payload["transaction_date"] = date
        payload["source_account"]["opening_date"] = date
        payload["destination_account"]["opening_date"] = date

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 422, response
        assert response["code"] == "QIT003001"
        assert RequestGenerator.GET_pix_transaction(payload["id"])[0] == 404

    @pytest.mark.parametrize("date", ["0001-01-31T00:00:00+00:00", "9999-12-29T10:00:00+00:00"])
    def test_representable_dates_with_safe_windows_do_not_overflow(self, date):
        payload = PixAccount().payload(100 * REAL)
        payload["transaction_date"] = date
        payload["source_account"]["opening_date"] = date
        payload["destination_account"]["opening_date"] = date

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201, response
        assert_decision(response, "approved", "POLICY_PASSED")

    def test_device_wait_near_the_end_of_datetime_range_does_not_overflow(self):
        account, destination = PixAccount(), PixDestination()
        first = account.payload(600 * REAL, destination=destination)
        first["transaction_date"] = "9999-12-31T00:00:00+00:00"
        first["source_account"]["opening_date"] = "9999-12-01T00:00:00+00:00"
        first["destination_account"]["opening_date"] = "9999-12-01T00:00:00+00:00"
        assert RequestGenerator.POST_pix_transaction(first)[0] == 201
        second = account.payload(6000 * REAL, destination=destination)
        second["transaction_date"] = "9999-12-31T01:00:00+00:00"
        second["source_account"] = first["source_account"]
        second["destination_account"] = first["destination_account"]

        status, response = RequestGenerator.POST_pix_transaction(second)

        assert status == 201, response
        assert_decision(response, "two_factor_required", "NEW_DEVICE_HIGH_AMOUNT")


class TestShorterPayerCache:
    @pytest.mark.parametrize("cached_mark,live_mark,expected", [(0, 1, "rejected"), (1, 0, "approved")])
    def test_payer_cache_older_than_five_minutes_is_refreshed(self, cached_mark, live_mark, expected):
        payer = PixAccount()
        seed_dict_cache(payer, statistics(mule=cached_mark), 6 * MINUTE)
        DictMock.mark(payer, mule=live_mark)

        response, transaction_id = payer.record(1500 * REAL)

        assert_decision(response, expected, "MULE_PAYER" if expected == "rejected" else "POLICY_PASSED")
        row = DbUtils.analysis_row(transaction_id)
        assert row["analysis_details"]["dict_status"]["payer"] == "consultado"
        assert row["payer_dict_e1"] == bool(live_mark)
        assert DbUtils.dict_lookup_count(payer.key) == 2

    def test_valid_cache_is_reused_without_refresh_on_read(self):
        payer = PixAccount()
        fetched_at = seed_dict_cache(payer, statistics(), 4 * MINUTE)
        DictMock.mark(payer, mule=1)

        response, transaction_id = payer.record(1500 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")
        assert DbUtils.analysis_row(transaction_id)["analysis_details"]["dict_status"]["payer"] == "cache"
        assert DbUtils.dict_lookup_count(payer.key) == 1
        engine = create_engine(DbUtils.database_url())
        try:
            with engine.connect() as connection:
                stored_at = connection.execute(
                    text("SELECT fetched_at FROM dict_lookup WHERE account_key = :key"), {"key": payer.key}
                ).scalar_one()
            assert stored_at == fetched_at
        finally:
            engine.dispose()

    def test_expired_cache_is_not_reused_when_the_source_fails(self):
        payer = PixAccount()
        seed_dict_cache(payer, statistics(mule=1), 6 * MINUTE)
        DictMock.unavailable(payer)

        response, transaction_id = payer.record(1500 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")
        row = DbUtils.analysis_row(transaction_id)
        assert row["payer_dict_e1"] is None
        assert row["analysis_details"]["dict_status"]["payer"] == "indisponivel"
