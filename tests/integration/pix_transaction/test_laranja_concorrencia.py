from tests.utils import DbUtils, DictMock, PixAccount, PixDestination, RequestGenerator
from tests.utils.concurrency import post_all
from tests.utils.mule_scenarios import hub_receiving_from_new_senders

REAL = 100


class TestMuleAccountConcurrency:
    """O cálculo de repasse depende do que a conta já enviou: a trava por conta faz cada pedido enxergar os anteriores."""

    def test_simultaneous_forwards_see_what_the_previous_ones_sent(self):
        """Conta suspeita que recebeu R$ 6.000 e tenta repassar 4 vezes R$ 1.000 ao mesmo tempo.

        Em fila, o 3º Pix leva o enviado a R$ 3.000 (50% do recebido) e vira repasse, e o
        4º também (o 3º foi rejeitado, então o enviado continua em R$ 2.000). Sem a trava,
        os quatro leriam 'enviado = 0' e passariam como 17% do recebido.
        """
        hub = PixAccount()
        hub_receiving_from_new_senders(hub, senders=6, first_time=4, each=1000 * REAL)
        payloads = [hub.payload(1000 * REAL, destination=PixDestination()) for _ in range(4)]

        results = post_all(payloads)

        assert [status for status, _ in results] == [201, 201, 201, 201]
        assert sorted(body["status"] for _, body in results) == ["approved", "approved", "rejected", "rejected"]
        for _, body in results:
            if body["status"] == "rejected":
                assert body["metadata"]["reason"]["code"] == "SUSPECTED_MULE_FORWARDING"
        acts = sorted(DbUtils.analysis_row(payload["id"])["analysis_details"]["act"] for payload in payloads)
        assert acts == ["outro", "outro", "repasse_aparente", "repasse_aparente"]

    def test_simultaneous_payments_to_a_marked_account_are_all_rejected_and_recorded_once(self):
        """Vítimas diferentes pagando a mesma conta marcada ao mesmo tempo: todas barradas, cada uma gravada uma vez."""
        mule = PixDestination()
        DictMock.mark(mule, mule=1)
        victims = [PixAccount() for _ in range(4)]

        payloads = [victim.payload(100 * REAL, destination=mule) for victim in victims]
        results = post_all(payloads)

        assert [body["status"] for _, body in results] == ["rejected"] * 4
        assert {body["metadata"]["reason"]["code"] for _, body in results} == {"MULE_DESTINATION"}
        assert len({body["key"] for _, body in results}) == 4
        for payload, (_, body) in zip(payloads, results):
            assert RequestGenerator.GET_pix_transaction(payload["id"]) == (200, body)
            assert RequestGenerator.POST_pix_transaction(payload) == (200, body)
