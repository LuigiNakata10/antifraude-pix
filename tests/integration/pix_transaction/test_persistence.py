from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from tests.utils import DbUtils, PixAccount, RequestGenerator


class TestPixTransactionPersistence:
    """Toda análise fica gravada, nos três status, e o GET devolve o mesmo envelope do POST."""

    @pytest.mark.parametrize(
        "account, amount, expected_status",
        [
            (lambda: PixAccount(), 500 * 100, "approved"),
            (lambda: PixAccount(), 6000 * 100, "two_factor_required"),
            (lambda: PixAccount(age=timedelta(days=3)), 2000 * 100, "rejected"),
        ],
        ids=["approved", "two-factor", "rejected"],
    )
    def test_the_analysis_is_stored_and_the_get_returns_the_same_envelope(self, account, amount, expected_status):
        pix_account = account()
        payload = pix_account.payload(amount)
        status, created = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        assert created["status"] == expected_status
        assert set(created) == {"key", "status", "metadata"}

        status, stored = RequestGenerator.GET_pix_transaction(payload["id"])

        assert status == 200
        assert stored == created

    def test_the_response_never_exposes_internal_ids(self):
        account = PixAccount()

        _, response = account.pix(500 * 100)

        assert set(response) == {"key", "status", "metadata"}
        assert len(response["key"]) == 36
        assert set(response["metadata"]) == {"policy_version", "reason"}


class TestPixTransactionWriteFailure:
    """Falha de gravação não responde sucesso e não deixa nada pela metade.

    Exceção consciente ao black box: o teste conecta direto ao Postgres só
    para instalar um gatilho que faz o INSERT da análise falhar para UM id.
    """

    def test_a_failure_while_writing_leaves_nothing_behind(self):
        transaction_id = f"pix-fail-{uuid4().hex[:10]}"
        account = PixAccount()
        payload = account.payload(500 * 100, transaction_id=transaction_id)
        engine = create_engine(DbUtils.database_url(), isolation_level="AUTOCOMMIT")

        with engine.connect() as connection:
            connection.exec_driver_sql(
                "CREATE OR REPLACE FUNCTION pix_test_fail_insert() RETURNS trigger AS $$ "
                "BEGIN RAISE EXCEPTION 'falha provocada pelo teste'; END; $$ LANGUAGE plpgsql"
            )
            connection.exec_driver_sql(
                "CREATE TRIGGER pix_test_fail BEFORE INSERT ON pix_analysis FOR EACH ROW "
                f"WHEN (NEW.transaction_id = '{transaction_id}') EXECUTE FUNCTION pix_test_fail_insert()"
            )
            try:
                status, response = RequestGenerator.POST_pix_transaction(payload)
                get_status, _ = RequestGenerator.GET_pix_transaction(transaction_id)
            finally:
                connection.exec_driver_sql("DROP TRIGGER IF EXISTS pix_test_fail ON pix_analysis")
                connection.exec_driver_sql("DROP FUNCTION IF EXISTS pix_test_fail_insert()")
        engine.dispose()

        assert status == 500
        assert response["code"] == "QIT000500"
        assert get_status == 404
        status, retried = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        assert retried["status"] == "approved"
