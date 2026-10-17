from datetime import timedelta
from uuid import uuid4

import pytest

from tests.utils import PayloadGenerator, PixAccount, RequestGenerator


class TestPixTransactionContract:
    """O contrato do POST e do GET /pix/transaction, só pela porta da frente.

    Nenhum teste aqui depende de regra antifraude: tudo o que se confere é
    o que a API decide ANTES de analisar — quem pode pedir, se o corpo tem
    o formato do desafio e se os dados fazem sentido juntos.
    """

    def test_post_without_token_is_forbidden(self):
        """Sem INTERNAL-TOKEN a API para na porta: 403, e o corpo nem é lido."""
        status, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.create_pix_payload(), with_token=False)

        assert status == 403
        assert response["code"] == "QIT000002"

    def test_get_without_token_is_forbidden(self):
        status, response = RequestGenerator.GET_pix_transaction("pix-qualquer", with_token=False)

        assert status == 403
        assert response["code"] == "QIT000002"

    def test_get_unknown_id_is_not_found(self):
        """Não existe análise para esse id: 404 com o código do domínio, não o da rota."""
        status, response = RequestGenerator.GET_pix_transaction(f"pix-{uuid4().hex}")

        assert status == 404
        assert response["code"] == "QIT003003"

    @pytest.mark.parametrize(
        "path",
        [
            "id",
            "amount",
            "transaction_date",
            "source_account",
            "source_account.branch",
            "source_account.account_number",
            "source_account.opening_date",
            "source_account.owner",
            "source_account.owner.document_number",
            "destination_account",
            "destination_account.participant",
            "destination_account.branch",
            "destination_account.account_number",
            "destination_account.opening_date",
            "destination_account.owner.document_number",
            "source",
            "source.device_id",
            "source.channel",
            "source.ip",
        ],
    )
    def test_missing_required_field_is_bad_request(self, path):
        """Todo campo do desafio é obrigatório, menos a geolocalização."""
        payload = PayloadGenerator.create_pix_payload()
        remove_path(payload, path)

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 400
        assert response["code"] == "QIT000001"

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "source_account",
            "source_account.owner",
            "destination_account",
            "destination_account.owner",
            "source",
            "source.geolocation",
        ],
    )
    def test_extra_field_is_bad_request(self, path):
        """O que não está no contrato não entra, em nenhum nível do corpo."""
        payload = PayloadGenerator.create_pix_payload()
        set_path(payload, f"{path}.unexpected" if path else "unexpected", "x")

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 400
        assert response["code"] == "QIT000001"

    @pytest.mark.parametrize("amount", [0, -1, 1.5, 150000.0, "150000", None, True, 2**63])
    def test_invalid_amount_is_bad_request(self, amount):
        """Valor é inteiro, positivo e em centavos. 150000.0 é recusado como 1.5:
        dinheiro nunca entra como ponto flutuante, nem quando 'cabe' num inteiro.
        """
        payload = PayloadGenerator.create_pix_payload()
        payload["amount"] = amount

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 400
        assert response["code"] == "QIT000001"

    @pytest.mark.parametrize(
        "date",
        [
            "2026-10-17T22:15:00",
            "2026-10-17 22:15:00-03:00",
            "2026-10-17",
            "17/10/2026",
            "2026-10-17T22:15-03:00",
            "",
        ],
    )
    def test_date_out_of_format_is_bad_request(self, date):
        """Data é ISO 8601 COM fuso: sem fuso, a hora não diz de que instante se fala."""
        payload = PayloadGenerator.create_pix_payload(transaction_date=date)

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 400
        assert response["code"] == "QIT000001"

    @pytest.mark.parametrize("participant", ["6070119", "607011900", "6070119a", ""])
    def test_participant_is_not_an_ispb_is_bad_request(self, participant):
        """O ISPB do banco de destino tem 8 dígitos."""
        payload = PayloadGenerator.create_pix_payload()
        payload["destination_account"]["participant"] = participant

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 400
        assert response["code"] == "QIT000001"

    @pytest.mark.parametrize("document", ["123.456.789-0", "123456789-09", "1234567890a", "12.345.678/0001", ""])
    def test_document_out_of_format_is_bad_request(self, document):
        """CPF e CNPJ aceitam só dígitos ou o formato completo com pontuação."""
        payload = PayloadGenerator.create_pix_payload()
        payload["source_account"]["owner"]["document_number"] = document

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 400
        assert response["code"] == "QIT000001"

    @pytest.mark.parametrize(
        "geolocation",
        [
            {"latitude": 90.1, "longitude": 0},
            {"latitude": -90.1, "longitude": 0},
            {"latitude": 0, "longitude": 180.1},
            {"latitude": 0, "longitude": -180.1},
            {"latitude": "-23.56", "longitude": -46.65},
            {"latitude": -23.56},
        ],
    )
    def test_invalid_geolocation_is_bad_request(self, geolocation):
        """A geolocalização é opcional, mas, se vier, tem latitude e longitude possíveis."""
        payload = PayloadGenerator.create_pix_payload(with_geolocation=False)
        payload["source"]["geolocation"] = geolocation

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_geolocation_with_fractions_is_not_rejected_as_money(self):
        """Só o valor do Pix recusa fração: -23.56 é coordenada, não dinheiro.

        A prova é por exclusão: o corpo passa pelo schema e só então a API
        o recusa por outro motivo (a conta de origem aberta depois do Pix).
        """
        payload = PayloadGenerator.create_pix_payload(source_opening_date="2026-10-18T10:00:00-03:00")

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 422
        assert response["code"] == "QIT003002"

    @pytest.mark.parametrize("date", ["2026-02-31T10:00:00-03:00", "2026-10-17T25:00:00-03:00", "2026-10-17T10:00:00+99:00"])
    def test_date_that_does_not_exist_is_unprocessable(self, date):
        """O formato está certo, mas a data não existe no calendário: 422, não 500.

        O schema sabe contar dígitos, não dias de fevereiro.
        """
        payload = PayloadGenerator.create_pix_payload(transaction_date=date)

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 422
        assert response["code"] == "QIT003001"

    @pytest.mark.parametrize("field", ["source_opening_date", "destination_opening_date"])
    def test_account_opened_after_the_transaction_is_unprocessable(self, field):
        """Uma conta não pode ter sido aberta depois do Pix que ela fez ou recebeu."""
        payload = PayloadGenerator.create_pix_payload(**{field: "2026-10-17T22:15:01-03:00"})

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 422
        assert response["code"] == "QIT003002"

    def test_account_opened_at_the_exact_moment_of_the_transaction_is_coherent(self):
        """Abertura IGUAL à data do Pix não é incoerente: só a abertura estritamente posterior é recusada."""
        payload = PayloadGenerator.create_pix_payload(
            transaction_date="2026-10-17T22:15:00-03:00",
            source_opening_date="2026-10-18T01:15:00+00:00",
            destination_opening_date="2026-10-17T22:15:00-03:00",
            amount=100 * 100,
        )

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert set(response) == {"key", "status", "metadata"}

    def test_a_pix_earlier_than_the_last_one_of_the_account_is_unprocessable(self):
        """Pedido retroativo: a análise anterior não é reavaliada, então o pedido é recusado, e não gravado."""
        account = PixAccount()
        account.send(100 * 100, timedelta(0), "approved")
        retroactive = account.payload(100 * 100, -timedelta(seconds=1))

        status, response = RequestGenerator.POST_pix_transaction(retroactive)

        assert status == 422
        assert response["code"] == "QIT003006"
        assert RequestGenerator.GET_pix_transaction(retroactive["id"])[0] == 404

    def test_a_pix_with_the_same_date_as_the_last_one_is_accepted(self):
        account = PixAccount()
        account.send(100 * 100, timedelta(0), "approved")

        status, _ = account.pix(100 * 100, timedelta(0))

        assert status == 201

    def test_a_refused_retroactive_pix_does_not_count_as_an_attempt(self):
        account = PixAccount()
        account.make_device_known()
        account.send(100 * 100, -timedelta(seconds=30), "approved")
        for _ in range(3):
            assert account.pix(100 * 100, -timedelta(seconds=60))[0] == 422

        status, response = account.pix(100 * 100)

        assert status == 201
        assert response["status"] == "approved"


def remove_path(payload: dict, path: str) -> None:
    *parents, last = path.split(".")
    node = payload
    for parent in parents:
        node = node[parent]
    del node[last]


def set_path(payload: dict, path: str, value) -> None:
    *parents, last = path.split(".")
    node = payload
    for parent in parents:
        node = node[parent]
    node[last] = value
