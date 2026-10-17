import copy
import re
from datetime import timedelta

import pytest

from tests.utils import PixAccount, RequestGenerator


def reordered(value):
    """O mesmo JSON com as chaves em outra ordem, em todos os níveis."""
    if isinstance(value, dict):
        return {key: reordered(value[key]) for key in reversed(list(value))}

    return value


class TestPixTransactionIdempotency:
    """O mesmo `id` não é analisado duas vezes: reenvio equivalente devolve a análise original."""

    def test_c09_identical_resend_returns_the_original_analysis(self):
        account = PixAccount()
        payload = account.payload(500 * 100)
        status, original = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        status, resend = RequestGenerator.POST_pix_transaction(payload)

        assert status == 200
        assert resend == original

    @pytest.mark.parametrize(
        "change",
        [
            lambda p: p.update(reordered(p)),
            lambda p: p.update(transaction_date="2026-10-18T01:15:00Z"),
            lambda p: p.update(transaction_date="2026-10-18T01:15:00+00:00"),
            lambda p: p["source_account"].update(opening_date="2026-03-02T10:00:00+00:00"),
            lambda p: p["source_account"]["owner"].update(document_number=re.sub(r"\D", "", p["source_account"]["owner"]["document_number"])),
            lambda p: p["destination_account"]["owner"].update(
                document_number=re.sub(r"\D", "", p["destination_account"]["owner"]["document_number"])
            ),
        ],
        ids=["key-order", "utc-z", "utc-offset", "opening-date-utc", "payer-document-digits", "destination-document-digits"],
    )
    def test_equivalent_payload_is_a_resend(self, change):
        """Outra ordem de chaves, o mesmo instante em outro fuso ou o documento sem pontuação são o mesmo pedido."""
        account = PixAccount()
        payload = account.payload(500 * 100)
        if payload["source_account"]["opening_date"].startswith("2025"):
            payload["source_account"]["opening_date"] = "2026-03-02T07:00:00-03:00"
        status, original = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        resend = copy.deepcopy(payload)
        change(resend)

        status, response = RequestGenerator.POST_pix_transaction(resend)

        assert status == 200
        assert response == original

    @pytest.mark.parametrize(
        "change",
        [
            lambda p: p.update(amount=p["amount"] + 1),
            lambda p: p.update(transaction_date="2026-10-17T22:15:01-03:00"),
            lambda p: p["source"].update(channel="web"),
            lambda p: p["source"].update(ip="198.51.100.24"),
            lambda p: p["source"].update(device_id="dvc-other"),
            lambda p: p["source"].pop("geolocation"),
            lambda p: p["source"]["geolocation"].update(latitude=-23.57),
            lambda p: p["destination_account"].update(account_number="99999"),
            lambda p: p["destination_account"]["owner"].update(document_number="00000000000"),
            lambda p: p["source_account"].update(branch="0002"),
        ],
        ids=["amount", "date", "channel", "ip", "device", "geolocation-removed", "geolocation-changed", "destination", "document", "branch"],
    )
    def test_any_other_difference_is_a_conflict(self, change):
        """A equivalência cobre o corpo inteiro: canal, IP e coordenadas também diferenciam o pedido."""
        account = PixAccount()
        payload = account.payload(500 * 100)
        status, original = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        changed = copy.deepcopy(payload)
        change(changed)

        status, response = RequestGenerator.POST_pix_transaction(changed)

        assert status == 409
        assert response["code"] == "QIT003004"
        _, stored = RequestGenerator.GET_pix_transaction(payload["id"])
        assert stored == original

    def test_a_conflict_does_not_consume_the_limit(self):
        account = PixAccount(age=timedelta(days=3))
        payload = account.payload(900 * 100)
        assert RequestGenerator.POST_pix_transaction(payload)[0] == 201
        conflicting = copy.deepcopy(payload)
        conflicting["amount"] = 50 * 100
        assert RequestGenerator.POST_pix_transaction(conflicting)[0] == 409

        _, response = account.pix(100 * 100, timedelta(minutes=5))

        assert response["status"] == "approved"

    def test_resends_do_not_count_as_new_attempts(self):
        """Dois reenvios do primeiro pedido não somam tentativas: o segundo pedido distinto é só a segunda."""
        account = PixAccount()
        account.make_device_known()
        first = account.payload(100 * 100, -timedelta(seconds=60))
        assert RequestGenerator.POST_pix_transaction(first)[0] == 201
        assert RequestGenerator.POST_pix_transaction(first)[0] == 200
        assert RequestGenerator.POST_pix_transaction(first)[0] == 200

        status, response = account.pix(100 * 100)

        assert status == 201
        assert response["status"] == "approved"

    def test_resend_of_an_old_pix_is_not_treated_as_out_of_order(self):
        """O reenvio de um Pix anterior ao último da conta devolve a original: o reenvio é conferido antes da ordem."""
        account = PixAccount()
        first = account.payload(100 * 100, -timedelta(minutes=10))
        _, original = RequestGenerator.POST_pix_transaction(first)
        account.send(100 * 100, timedelta(0), "approved")

        status, response = RequestGenerator.POST_pix_transaction(first)

        assert status == 200
        assert response == original
