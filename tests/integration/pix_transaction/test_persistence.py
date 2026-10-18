from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from tests.utils import DbUtils, PixAccount, RequestGenerator
from tests.utils.requisition import ClientRequisition
from tests.utils.request_generator import INTERNAL_TOKEN


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
        assert set(created["metadata"]) == {"policy_version", "reason"}

        status, stored = RequestGenerator.GET_pix_transaction(payload["id"])

        assert status == 200
        assert stored == created


class TestPixTransactionWriteFailure:
    """Falha de gravação não responde sucesso e não deixa nada pela metade.

    Exceção consciente ao black box: o teste conecta direto ao Postgres só
    para falhar ao gravar vínculos, DEPOIS do INSERT da análise, para UM id.
    """

    def test_a_failure_while_writing_leaves_nothing_behind(self):
        transaction_id = f"pix-fail-{uuid4().hex[:10]}"
        account = PixAccount()
        payload = account.payload(500 * 100, transaction_id=transaction_id)
        engine = create_engine(DbUtils.database_url(), isolation_level="AUTOCOMMIT")

        with engine.connect() as connection:
            connection.exec_driver_sql(
                "CREATE OR REPLACE FUNCTION pix_test_fail_insert() RETURNS trigger AS $$ "
                "BEGIN IF EXISTS (SELECT 1 FROM pix_analysis WHERE id = NEW.pix_analysis_id "
                f"AND transaction_id = '{transaction_id}') THEN "
                "RAISE EXCEPTION 'falha provocada pelo teste'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
            )
            connection.exec_driver_sql(
                "CREATE TRIGGER pix_test_fail BEFORE INSERT ON account_link FOR EACH ROW "
                "EXECUTE FUNCTION pix_test_fail_insert()"
            )
            try:
                status, response = RequestGenerator.POST_pix_transaction(payload)
                get_status, _ = RequestGenerator.GET_pix_transaction(transaction_id)
            finally:
                connection.exec_driver_sql("DROP TRIGGER IF EXISTS pix_test_fail ON account_link")
                connection.exec_driver_sql("DROP FUNCTION IF EXISTS pix_test_fail_insert()")
        engine.dispose()

        assert status == 500
        assert response["code"] == "QIT000500"
        assert get_status == 404
        status, retried = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        assert retried["status"] == "approved"


class TestPixTransactionLockTimeout:
    """A conta presa por outro pedido além de 5 s devolve 503 e não grava nada.

    Exceção consciente ao black box: o teste conecta direto ao Postgres só para
    SEGURAR a trava da conta pagadora, como faria outra requisição lenta.
    """

    def test_a_busy_account_answers_503_and_the_retry_succeeds(self):
        account = PixAccount()
        account.send(100 * 100, -timedelta(minutes=10), "approved")
        payload = account.payload(100 * 100)
        engine = create_engine(DbUtils.database_url())

        with engine.connect() as connection:
            connection.execute(
                text("SELECT id FROM payer_account WHERE branch = :branch AND account_number = :number FOR UPDATE"),
                {"branch": account.branch, "number": account.account_number},
            )
            try:
                response = ClientRequisition.send(
                    "POST", "/pix/transaction", payload=payload, headers={"INTERNAL-TOKEN": INTERNAL_TOKEN}
                )
                get_status, _ = RequestGenerator.GET_pix_transaction(payload["id"])
            finally:
                connection.rollback()
        engine.dispose()

        assert response.response_status == 503
        assert response.response_json["code"] == "QIT003005"
        assert response.response.headers["Retry-After"] == "1"
        assert get_status == 404
        status, retried = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        assert retried["status"] == "approved"
