import re
from datetime import timedelta

from tests.utils import DbUtils, DictMock, PixAccount, RandomGenerator
from tests.utils.mule_scenarios import hub_receiving_from_new_senders

REAL = 100
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def digits(document: str) -> str:
    return re.sub(r"\D", "", document)


def old_company() -> PixAccount:
    """Uma conta de CNPJ aberta há mais de 90 dias: gasto típico até R$ 1.000 para ela."""
    return PixAccount(age=400 * DAY, document=RandomGenerator.generate_cnpj())


def marked_account_pays(receiver: PixAccount, amount: int, when: timedelta, device_id: str = None) -> PixAccount:
    """Uma conta marcada no DICT paga `receiver` (um gasto típico, que a laranja pode fazer)."""
    marked = PixAccount(device_id=device_id)
    DictMock.mark(marked, mule=1)
    marked.send(amount, when, "approved", destination=receiver.as_destination())

    return marked


def state_of(account: PixAccount, amount: int = 100 * REAL, when: timedelta = timedelta(0)) -> dict:
    """O retrato do pagador no momento de um Pix dele: estado e evidências."""
    destination = old_company().as_destination()
    _, transaction_id = account.record(amount, when, destination=destination)

    return DbUtils.analysis_row(transaction_id)["analysis_details"]["payer"]


class TestGraphEvidence:
    """E2: o dinheiro e o aparelho de uma conta marcada no DICT, e as travas de boa-fé."""

    def test_who_receives_from_a_marked_account_inherits_the_suspicion(self):
        receiver = old_company()
        marked_account_pays(receiver, 900 * REAL, -1 * HOUR)

        assert state_of(receiver) == {"state": "suspeita", "evidences": ["E2"]}

    def test_direction_who_paid_the_marked_account_is_not_affected(self):
        """Quem enviou para a marcada está ANTES dela no dinheiro: quase sempre é vítima, e não ganha E2."""
        marked, victim, receiver = PixAccount(), PixAccount(), old_company()
        DictMock.unavailable(marked)
        victim.send(100 * REAL, -3 * HOUR, "approved", destination=marked.as_destination())
        DictMock.mark(marked, mule=1)
        marked.send(900 * REAL, -1 * HOUR, "approved", destination=receiver.as_destination())

        assert state_of(victim) == {"state": "nao", "evidences": []}
        assert state_of(receiver)["evidences"] == ["E2"]

    def test_reputation_an_established_account_with_many_counterparties_is_not_affected(self):
        """A padaria antiga, com 10 contrapartes, não ganha E2 nem com 100% marcado vindo de uma conta."""
        bakery = old_company()
        marked_account_pays(bakery, 900 * REAL, -3 * HOUR)
        for _ in range(9):
            bakery.fund(1 * REAL, -4 * HOUR)

        assert state_of(bakery) == {"state": "nao", "evidences": []}

    def test_reputation_still_applies_with_fewer_than_10_counterparties(self):
        bakery = old_company()
        marked_account_pays(bakery, 900 * REAL, -3 * HOUR)
        for _ in range(8):
            bakery.fund(1 * REAL, -4 * HOUR)

        assert state_of(bakery)["evidences"] == ["E2"]

    def test_proportion_exactly_half_is_not_enough(self):
        """Só conta se MAIS de 50% do recebido em 30 dias veio de conta marcada."""
        receiver = old_company()
        marked_account_pays(receiver, 900 * REAL, -3 * HOUR)
        receiver.fund(900 * REAL, -2 * HOUR)

        assert state_of(receiver) == {"state": "nao", "evidences": []}

    def test_proportion_just_above_half_counts(self):
        receiver = old_company()
        marked_account_pays(receiver, 90100, -3 * HOUR)
        receiver.fund(89900, -2 * HOUR)

        assert state_of(receiver)["evidences"] == ["E2"]

    def test_one_real_sent_on_purpose_does_not_lock_the_account(self):
        """Um golpista pode mandar R$ 1 de uma conta marcada para prejudicar alguém: 0,1% do recebido não conta."""
        victim = old_company()
        victim.fund(1000 * REAL, -3 * HOUR)
        marked_account_pays(victim, 1 * REAL, -2 * HOUR)

        assert state_of(victim) == {"state": "nao", "evidences": []}

    def test_expiration_money_from_a_marked_account_more_than_30_days_ago_is_forgotten(self):
        old, recent = old_company(), old_company()
        marked_account_pays(old, 900 * REAL, -31 * DAY)
        marked_account_pays(recent, 900 * REAL, -29 * DAY)

        assert state_of(old) == {"state": "nao", "evidences": []}
        assert state_of(recent)["evidences"] == ["E2"]

    def test_only_a_marked_account_propagates_suspicion_one_hop_only(self):
        """A conta suspeita (E2) não está marcada no DICT: quem recebe dela não herda nada."""
        second_hop = old_company()
        first_hop = old_company()
        marked_account_pays(first_hop, 900 * REAL, -3 * HOUR)
        first_hop.send(900 * REAL, -1 * HOUR, "approved", destination=second_hop.as_destination())

        assert state_of(first_hop)["evidences"] == ["E2"]
        assert state_of(second_hop) == {"state": "nao", "evidences": []}

    def test_a_device_shared_with_a_marked_account_is_a_sign(self):
        shared = "dvc-shared-marked"
        marked_account_pays(old_company(), 100 * REAL, -3 * HOUR, device_id=shared)
        account = PixAccount(device_id=shared)

        account.send(100 * REAL, -2 * HOUR, "approved")
        assert state_of(account) == {"state": "suspeita", "evidences": ["E2"]}

    def test_a_device_shared_with_an_account_that_is_not_marked_is_not_a_sign(self):
        """L3 não ganha E2 por dividir o aparelho com uma conta que NÃO está marcada: a suspeita não anda em cadeia."""
        shared = "dvc-shared-clean"
        PixAccount(device_id=shared).send(100 * REAL, -3 * HOUR, "approved")
        account = PixAccount(device_id=shared)

        assert state_of(account) == {"state": "nao", "evidences": []}

    def test_device_sharing_expires_after_30_days(self):
        shared = "dvc-shared-old"
        marked_account_pays(old_company(), 100 * REAL, -31 * DAY, device_id=shared)
        account = PixAccount(device_id=shared)

        assert state_of(account) == {"state": "nao", "evidences": []}

    def test_e3_needs_five_holders_and_three_first_timers(self):
        four_holders, five_holders, two_first_timers = PixAccount(), PixAccount(), PixAccount()
        hub_receiving_from_new_senders(four_holders, senders=4, first_time=4, each=100 * REAL)
        hub_receiving_from_new_senders(five_holders, senders=5, first_time=3, each=100 * REAL)
        hub_receiving_from_new_senders(two_first_timers, senders=5, first_time=2, each=100 * REAL)

        assert state_of(four_holders)["state"] == "nao"
        assert state_of(five_holders) == {"state": "suspeita", "evidences": ["E3"]}
        assert state_of(two_first_timers)["state"] == "nao"

    def test_e3_for_a_company_needs_30_holders(self):
        """Uma empresa recebe de muita gente por natureza: 5 titulares não bastam para um CNPJ."""
        company = old_company()
        hub_receiving_from_new_senders(company, senders=6, first_time=6, each=100 * REAL)

        assert state_of(company)["state"] == "nao"

    def test_e5_a_new_account_receiving_a_lot_from_several_holders(self):
        """Conta com menos de 7 dias que recebe mais de R$ 5.000 em 24 h de 3 ou mais titulares."""
        young, steady = PixAccount(age=3 * DAY), PixAccount(age=3 * DAY)
        for index in range(3):
            young.fund(1700 * REAL, -(6 + index) * HOUR)
        for index in range(3):
            steady.fund(1666 * REAL, -(6 + index) * HOUR)

        assert state_of(young) == {"state": "suspeita", "evidences": ["E5"]}
        assert state_of(steady)["state"] == "nao"

    def test_e5_does_not_apply_after_seven_days(self):
        week_old = PixAccount(age=7 * DAY)
        for index in range(3):
            week_old.fund(2000 * REAL, -(6 + index) * HOUR)

        assert state_of(week_old)["state"] == "nao"

    def test_the_graph_edges_are_recorded_with_every_analysis(self):
        sender, receiver = PixAccount(), PixAccount()
        _, transaction_id = sender.record(100 * REAL, destination=receiver.as_destination())

        edges = DbUtils.links_of(transaction_id)

        assert {(edge["link_type"], edge["from_key"], edge["to_key"]) for edge in edges} == {
            ("pix", sender.key, receiver.key),
            ("device", sender.key, f"device:{sender.device_id}"),
            ("document", sender.key, f"document:{digits(sender.document)}"),
            ("document", receiver.key, f"document:{digits(receiver.document)}"),
        }
        assert [edge["amount"] for edge in edges if edge["link_type"] == "pix"] == [100 * REAL]
