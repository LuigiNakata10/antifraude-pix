from datetime import timedelta

from tests.utils import DbUtils, DictMock, PixAccount, PixDestination, RandomGenerator, RequestGenerator
from tests.utils.assertions import assert_decision

REAL = 100  # R$ 1,00 em centavos
MINUTE = timedelta(minutes=1)
DAY = timedelta(days=1)


class TestMuleAccountRules:
    """Módulo de conta laranja: primeiro o motor classifica a conta, depois decide o ato.

    Cenários P01 a P13 da proposta, um teste por cenário. Todos pressupõem que
    R1 a R4 não se aplicam, salvo quando dito. O DICT é o mock, roteirizado por
    teste com contas novas.
    """

    def test_p01_regular_payment_to_a_recipient_marked_later_is_approved(self):
        """A mãe que já mandava a mesada antes de o filho ser marcado: relação anterior, nada muda."""
        mother, son = PixAccount(), PixDestination()
        mother.send(100 * REAL, -10 * DAY, "approved", destination=son)
        DictMock.mark(son, mule=1)

        _, response = mother.pix(100 * REAL, destination=son)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_p02_a_new_victim_paying_a_marked_account_is_rejected(self):
        victim, mule = PixAccount(), PixDestination()
        DictMock.mark(mule, mule=1)

        _, response = victim.pix(100 * REAL, destination=mule)

        reason = assert_decision(response, "rejected", "MULE_DESTINATION")
        assert reason["account"] == "destination"
        assert reason["account_state"] == "confirmada"
        assert reason["evidences"] == ["E1"]
        assert reason["act"] == "outro"
        assert "document" not in str(reason).lower()

    def test_p03_a_marked_account_can_still_pay_a_utility_bill(self):
        """Gasto típico: até R$ 1.000 para um CNPJ com conta de 90 dias ou mais."""
        marked, utility = PixAccount(), PixDestination(age=400 * DAY, document=RandomGenerator.generate_cnpj())
        DictMock.mark(marked, mule=1)

        _, response = marked.pix(180 * REAL, destination=utility)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_p04_a_marked_account_forwarding_what_it_just_received_is_rejected(self):
        """O dinheiro entrou antes de o DICT marcar a conta; agora ela tenta repassá-lo.

        O DICT estava fora do ar quando o dinheiro entrou: nada foi guardado no
        cache. Se tivesse respondido (sem marcação), o pagador seria lido do cache
        de 24 h e a marcação nova só valeria quando ele expirasse.
        """
        sender, marked = PixAccount(), PixAccount()
        DictMock.unavailable(marked)
        sender.make_device_known()
        sender.send(5000 * REAL, -30 * MINUTE, "approved", destination=marked.as_destination())
        DictMock.mark(marked, mule=1)

        _, response = marked.pix(4000 * REAL)

        reason = assert_decision(response, "rejected", "MULE_PAYER")
        assert reason["account"] == "payer"
        assert reason["account_state"] == "confirmada"
        assert reason["evidences"] == ["E1"]

    def test_p05_a_marked_account_paying_a_new_person_is_rejected(self):
        """Mesmo sem entradas recentes: confirmada só faz gasto típico."""
        marked = PixAccount()
        DictMock.mark(marked, mule=1)

        _, response = marked.pix(1500 * REAL)

        reason = assert_decision(response, "rejected", "MULE_PAYER")
        assert reason["act"] == "outro"

    def test_p10_with_the_dict_down_the_decision_comes_from_the_base_rules(self):
        """A conta SÓ era marcada no DICT, e ele está fora do ar: E1 é desconhecida e não conta."""
        payer, recipient = PixAccount(), PixDestination()
        DictMock.respond(payer, body={"x": 1}, delay_ms=500)
        DictMock.unavailable(recipient)
        payload = payer.payload(4000 * REAL, destination=recipient)

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert_decision(response, "approved", "POLICY_PASSED")
        row = DbUtils.analysis_row(payload["id"])
        assert row["analysis_details"]["dict_status"] == {"payer": "indisponivel", "destination": "indisponivel"}
        assert row["payer_dict_e1"] is None
        assert row["destination_dict_e1"] is None
