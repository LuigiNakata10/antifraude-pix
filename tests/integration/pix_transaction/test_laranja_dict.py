from datetime import timedelta
from uuid import uuid4

import pytest

from tests.utils import DbUtils, DictMock, PixAccount, PixDestination, RandomGenerator, RequestGenerator
from tests.utils.assertions import assert_decision
from tests.utils.dict_mock import statistics

REAL = 100
DAY = timedelta(days=1)


def send(account: PixAccount, amount: int, when: timedelta = timedelta(0), **kwargs):
    """Envia um Pix com id conhecido (para conferir a auditoria depois) e devolve (resposta, id)."""
    transaction_id = f"pix-{uuid4().hex[:12]}"
    status, response = RequestGenerator.POST_pix_transaction(
        account.payload(amount, when, transaction_id=transaction_id, **kwargs)
    )
    assert status == 201, response

    return response, transaction_id


class TestDictSignals:
    """E1 e E4 saem do que o DICT diz de cada conta, e o motor registra o que viu."""

    @pytest.mark.parametrize(
        "counters, is_marked",
        [
            ({"mule": 1}, True),
            ({"scammer": 1}, True),
            ({"reporters": 2}, True),
            ({"reporters": 1}, False),
            ({"mule": 0, "mule_m12": 3}, False),
        ],
        ids=["mule", "scammer", "two-institutions", "one-institution", "mark-outside-90-days"],
    )
    def test_e1_is_a_mark_in_the_last_90_days_or_two_institutions(self, counters, is_marked):
        victim, recipient = PixAccount(), PixDestination()
        DictMock.mark(recipient, **counters)

        response, transaction_id = send(victim, 100 * REAL, destination=recipient)

        if is_marked:
            reason = assert_decision(response, "rejected", "MULE_DESTINATION")
            assert reason["evidence_values"]["E1"]["window_days"] == 90
            assert reason["evidence_values"]["E1"]["minimum_reporters"] == 2
            assert reason["evidence_values"]["E1"]["distinct_reporters"] == counters.get("reporters", 0)
            assert recipient.document not in str(reason)
        else:
            assert_decision(response, "approved", "POLICY_PASSED")
        assert DbUtils.analysis_row(transaction_id)["destination_dict_e1"] is is_marked

    @pytest.mark.parametrize("open_reports, has_e4", [(0, False), (1, False), (2, True), (5, True)])
    def test_e4_is_two_or_more_open_infraction_reports(self, open_reports, has_e4):
        """Com E2, o segundo relato aberto muda uma saída de aprovação para rejeição."""
        marked = PixAccount()
        recipient = PixAccount(document=RandomGenerator.generate_cnpj())
        DictMock.mark(marked, mule=1)
        DictMock.mark(recipient, open_reports=open_reports)
        marked.send(900 * REAL, -timedelta(hours=2), "approved", destination=recipient.as_destination())

        response, transaction_id = send(recipient, 1500 * REAL)

        assert_decision(response, "rejected" if has_e4 else "approved", "MULE_PAYER" if has_e4 else "POLICY_PASSED")
        assert DbUtils.analysis_row(transaction_id)["payer_dict_e4"] is has_e4

    def test_the_payer_signals_are_recorded_too(self):
        payer = PixAccount()
        DictMock.mark(payer, mule=1, open_reports=2)

        response, transaction_id = send(payer, 100 * REAL, destination=PixDestination(age=400 * DAY))

        assert_decision(response, "rejected", "MULE_PAYER")
        row = DbUtils.analysis_row(transaction_id)
        assert row["payer_dict_e1"] is True
        assert row["payer_dict_e4"] is True
        assert row["analysis_details"]["dict_status"] == {"payer": "consultado", "destination": "consultado"}
        assert row["analysis_details"]["payer"]["state"] == "suspeita_elevada"
        assert row["analysis_details"]["payer"]["evidences"] == ["E1", "E4"]


class TestDictUnavailable:
    """Timeout, 429 e resposta fora do formato viram 'desconhecido': o Pix é decidido sem o DICT."""

    @pytest.mark.parametrize(
        "make_unavailable",
        [
            lambda account: DictMock.respond(account, body=statistics(mule=1), delay_ms=500),
            lambda account: DictMock.too_many_requests(account),
            lambda account: DictMock.respond(account, raw_body="isto não é json"),
            lambda account: DictMock.respond(account, body={"OwnerStatistics": {}}),
            lambda account: DictMock.respond(account, status=500, body=statistics(mule=1)),
        ],
        ids=["timeout", "429", "not-json", "unexpected-body", "server-error"],
    )
    def test_the_decision_is_made_without_the_dict(self, make_unavailable):
        """Se o DICT tivesse respondido, o destino marcado levaria L1. Sem ele, valem as regras base."""
        victim, recipient = PixAccount(), PixDestination()
        make_unavailable(recipient)

        response, transaction_id = send(victim, 100 * REAL, destination=recipient)

        assert_decision(response, "approved", "POLICY_PASSED")
        row = DbUtils.analysis_row(transaction_id)
        assert row["analysis_details"]["dict_status"] == {"payer": "consultado", "destination": "indisponivel"}
        assert row["destination_dict_e1"] is None
        assert row["destination_dict_e4"] is None

    def test_a_failed_lookup_is_not_cached(self):
        payer = PixAccount()
        DictMock.unavailable(payer)
        send(payer, 100 * REAL, when=timedelta(minutes=-10))
        DictMock.mark(payer, mule=1)

        response, transaction_id = send(payer, 1500 * REAL)

        assert_decision(response, "rejected", "MULE_PAYER")
        row = DbUtils.analysis_row(transaction_id)
        assert row["analysis_details"]["dict_status"]["payer"] == "consultado"
        assert row["payer_dict_e1"] is True


class TestDictCache:
    """O pagador é lido do cache (5 min); o destino é consultado ao vivo e o cache só o socorre."""

    def test_a_new_mark_on_the_destination_is_seen_right_away(self):
        """Ao vivo: marcação nova no DICT vale já no Pix seguinte, sem esperar o cache expirar."""
        first, second, recipient = PixAccount(), PixAccount(), PixDestination()
        response, _ = send(first, 100 * REAL, destination=recipient)
        assert_decision(response, "approved", "POLICY_PASSED")
        DictMock.mark(recipient, mule=1)

        response, _ = send(second, 100 * REAL, destination=recipient)

        assert_decision(response, "rejected", "MULE_DESTINATION")

    def test_the_cache_stands_in_when_the_dict_fails_for_the_destination(self):
        """O destino foi visto marcado; o DICT cai; o cache de 1 h ainda sustenta a decisão."""
        first, second, recipient = PixAccount(), PixAccount(), PixDestination()
        DictMock.mark(recipient, mule=1)
        response, _ = send(first, 100 * REAL, destination=recipient)
        assert_decision(response, "rejected", "MULE_DESTINATION")
        DictMock.unavailable(recipient)

        response, transaction_id = send(second, 100 * REAL, destination=recipient)

        assert_decision(response, "rejected", "MULE_DESTINATION")
        row = DbUtils.analysis_row(transaction_id)
        assert row["analysis_details"]["dict_status"]["destination"] == "cache"
        assert row["destination_dict_e1"] is True

    def test_the_dict_being_down_never_blocks_the_decision(self):
        """Mock derrubado por expectation (sem parar o container): o Pix sai com as regras base."""
        payer, recipient = PixAccount(), PixDestination()
        DictMock.unavailable(payer)
        DictMock.unavailable(recipient)

        status, response = payer.pix(6000 * REAL, destination=recipient)

        assert status == 201
        assert_decision(response, "two_factor_required", "NEW_DEVICE_HIGH_AMOUNT")
