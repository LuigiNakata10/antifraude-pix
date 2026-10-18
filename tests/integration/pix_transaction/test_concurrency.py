from datetime import timedelta

from tests.utils import PixAccount
from tests.utils.concurrency import post_all


class TestPixTransactionConcurrency:
    """A trava por conta pagadora faz cada pedido enxergar os que a antecederam."""

    def test_two_simultaneous_pix_do_not_cross_the_daily_limit_together(self):
        """Sem a trava, os dois leriam acumulado zero e aprovariam R$ 24.000."""
        account = PixAccount()
        account.make_device_known(amount=2000 * 100)
        payloads = [account.payload(12000 * 100) for _ in range(2)]

        results = post_all(payloads)

        assert [status for status, _ in results] == [201, 201]
        assert sorted(body["status"] for _, body in results) == ["approved", "rejected"]
        rejected = next(body for _, body in results if body["status"] == "rejected")
        assert rejected["metadata"]["reason"]["code"] == "DAILY_LIMIT_EXCEEDED"

    def test_the_third_simultaneous_attempt_sees_the_two_before_it(self):
        account = PixAccount()
        account.make_device_known()
        payloads = [account.payload(10 * 100) for _ in range(3)]

        results = post_all(payloads)

        assert [status for status, _ in results] == [201, 201, 201]
        assert sorted(body["status"] for _, body in results) == ["approved", "approved", "two_factor_required"]
        asked = next(body for _, body in results if body["status"] == "two_factor_required")
        assert asked["metadata"]["reason"]["code"] == "HIGH_FREQUENCY"

    def test_the_same_id_in_parallel_is_analyzed_once(self):
        account = PixAccount()
        payload = account.payload(500 * 100)

        results = post_all([payload, payload, payload])

        assert sorted(status for status, _ in results) == [200, 200, 201]
        assert len({body["key"] for _, body in results}) == 1

    def test_the_same_id_with_different_content_in_parallel_has_one_winner(self):
        """Contas diferentes não dividem trava: quem decide é o UNIQUE do id, e o perdedor recebe o conflito."""
        first, second = PixAccount(), PixAccount()
        transaction_id = f"pix-race-{first.account_number}"
        payloads = [
            first.payload(500 * 100, transaction_id=transaction_id),
            second.payload(700 * 100, transaction_id=transaction_id),
        ]

        results = post_all(payloads)

        assert sorted(status for status, _ in results) == [201, 409]
        loser = next(body for status, body in results if status == 409)
        assert loser["code"] == "QIT003004"

    def test_simultaneous_pix_on_a_new_account_respect_the_limit(self):
        """Quatro Pix de R$ 400 numa conta nova: só dois cabem nos R$ 1.000, em qualquer ordem."""
        account = PixAccount(age=timedelta(days=3))

        results = post_all([account.payload(400 * 100) for _ in range(4)])

        statuses = sorted(body["status"] for _, body in results)
        assert statuses.count("approved") == 2
        assert statuses.count("rejected") == 2
