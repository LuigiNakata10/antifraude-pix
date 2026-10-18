from datetime import timedelta

import pytest

from tests.utils import DbUtils, DictMock, PixAccount, PixDestination, RandomGenerator, RequestGenerator
from tests.utils.assertions import assert_decision
from tests.utils.pix_account import at
from tests.utils.mule_scenarios import hub_receiving_from_new_senders

REAL = 100  # R$ 1,00 em centavos
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


class TestMuleAccountRules:
    """Módulo de conta laranja: primeiro o motor classifica a conta, depois decide o ato.

    Cenários P01 a P13 da proposta, um teste por cenário. Todos pressupõem que
    R1 a R4 não se aplicam, salvo quando dito. O DICT é o mock, roteirizado por
    teste com contas novas.
    """

    @pytest.mark.parametrize(
        "age_days,receipt,payment",
        [(3, 600 * REAL, 900 * REAL), (7, 2000 * REAL, 3000 * REAL)],
        ids=["new-account-modest-receipts", "seven-days-no-longer-new"],
    )
    def test_receipts_without_e5_do_not_cause_a_false_forwarding_rejection(self, age_days, receipt, payment):
        payer = PixAccount(age=age_days * DAY)
        for index in range(3):
            payer.fund(receipt, -(20 + index) * MINUTE)

        _, response = payer.pix(payment)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_p01_regular_payment_to_a_recipient_marked_later_is_approved(self):
        """A mãe que já mandava a mesada antes de o filho ser marcado: relação anterior, nada muda."""
        mother, son = PixAccount(), PixDestination()
        mother.send(100 * REAL, -10 * DAY, "approved", destination=son)
        DictMock.mark(son, mule=1, e1_since=at(-DAY))

        _, response = mother.pix(100 * REAL, destination=son)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_p02_a_new_victim_paying_a_marked_account_is_rejected(self):
        victim, mule = PixAccount(), PixDestination()
        DictMock.mark(mule, mule=1)

        _, response = victim.pix(100 * REAL, destination=mule)

        reason = assert_decision(response, "rejected", "MULE_DESTINATION")
        assert reason["account"] == "destination"
        assert reason["account_state"] == "suspeita_elevada"
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
        de 5 min e a marcação nova só valeria quando ele expirasse.
        """
        sender, marked = PixAccount(), PixAccount()
        DictMock.unavailable(marked)
        sender.make_device_known()
        sender.send(5000 * REAL, -30 * MINUTE, "approved", destination=marked.as_destination())
        DictMock.mark(marked, mule=1)

        _, response = marked.pix(4000 * REAL)

        reason = assert_decision(response, "rejected", "MULE_PAYER")
        assert reason["account"] == "payer"
        assert reason["account_state"] == "suspeita_elevada"
        assert reason["evidences"] == ["E1"]
        assert reason["act"] == "repasse_aparente"

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

    def test_p06_a_hub_that_forwards_most_of_what_it_received_is_rejected(self):
        """Recebeu de 6 titulares em 1 h (4 de primeira vez) e repassa 80% a uma pessoa física: E3 + repasse."""
        hub = PixAccount()
        hub_receiving_from_new_senders(hub, senders=6, first_time=4, each=1000 * REAL)

        response, transaction_id = hub.record(4800 * REAL)

        reason = assert_decision(response, "rejected", "SUSPECTED_MULE_FORWARDING")
        assert reason["account"] == "payer"
        assert reason["account_state"] == "suspeita"
        assert reason["evidences"] == ["E3"]
        assert reason["act"] == "repasse_aparente"
        assert DbUtils.analysis_row(transaction_id)["analysis_details"]["act"] == "repasse_aparente"

    def test_p07_the_same_account_paying_a_small_bill_is_approved(self):
        """Suspeita só pesa no repasse: o mercado de R$ 90 passa."""
        hub = PixAccount()
        hub_receiving_from_new_senders(hub)
        market = PixDestination(age=400 * DAY, document=RandomGenerator.generate_cnpj())

        response, transaction_id = hub.record(90 * REAL, destination=market)

        assert_decision(response, "approved", "POLICY_PASSED")
        details = DbUtils.analysis_row(transaction_id)["analysis_details"]
        assert details["payer"]["state"] == "suspeita"
        assert details["act"] == "gasto_tipico"

    def test_p08_a_shared_expense_paid_to_an_established_company_is_approved(self):
        """Rateio: Ana recebe de 5 amigos e paga o restaurante. O destino é um CNPJ antigo, então não é repasse."""
        ana = PixAccount()
        hub_receiving_from_new_senders(ana, senders=5, first_time=5, each=240 * REAL)
        restaurant = PixDestination(age=400 * DAY, document=RandomGenerator.generate_cnpj())

        response, transaction_id = ana.record(1200 * REAL, destination=restaurant)

        assert_decision(response, "approved", "POLICY_PASSED")
        details = DbUtils.analysis_row(transaction_id)["analysis_details"]
        assert details["payer"]["state"] == "suspeita"
        assert details["act"] == "outro"

    def test_p09_an_established_shop_that_received_from_a_marked_account_is_not_affected(self):
        """Receber de boa-fé não trava ninguém: a padaria antiga tem muitas contrapartes e o dinheiro marcado é pouco."""
        bakery = PixAccount(age=3650 * DAY, document=RandomGenerator.generate_cnpj())
        for _ in range(10):
            bakery.fund(10 * REAL, -2 * HOUR)
        marked = PixAccount()
        DictMock.mark(marked, mule=1)
        marked.send(50 * REAL, -1 * HOUR, "approved", destination=bakery.as_destination())
        supplier = PixDestination(age=400 * DAY, document=RandomGenerator.generate_cnpj())

        response, transaction_id = bakery.record(300 * REAL, destination=supplier)

        assert_decision(response, "approved", "POLICY_PASSED")
        details = DbUtils.analysis_row(transaction_id)["analysis_details"]
        assert details["payer"] == {"state": "nao", "evidences": []}

    def test_p11_once_the_window_has_passed_the_same_account_is_no_longer_suspect(self):
        """Oito dias depois, sem evidência nova: a janela de E3 passou e o estado caiu sozinho."""
        hub = PixAccount()
        hub_receiving_from_new_senders(hub, before=-8 * DAY)

        response, transaction_id = hub.record(4800 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")
        assert DbUtils.analysis_row(transaction_id)["analysis_details"]["payer"]["state"] == "nao"

    def test_p12_a_young_account_with_large_receipts_can_still_make_a_small_payment(self):
        """E5 sozinha não deve elevar a suspeita e recusar uma saída que cabe em R1."""
        young = PixAccount(age=3 * DAY)
        hub_receiving_from_new_senders(young, senders=4, first_time=4, each=1500 * REAL)
        response, transaction_id = young.record(900 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")
        details = DbUtils.analysis_row(transaction_id)["analysis_details"]
        assert details["payer"] == {"state": "suspeita", "evidences": ["E5"]}

    def test_p13_the_same_young_account_forwarding_is_stopped_first_by_the_new_account_limit(self):
        """A ordem: R1 já pega a conta nova acima de R$ 1.000, e é o motivo informado."""
        young = PixAccount(age=3 * DAY)
        hub_receiving_from_new_senders(young, senders=5, first_time=5, each=1300 * REAL)

        _, response = young.pix(5000 * REAL)

        assert_decision(response, "rejected", "NEW_ACCOUNT_LIMIT_EXCEEDED")
