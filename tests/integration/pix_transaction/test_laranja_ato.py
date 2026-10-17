from datetime import timedelta

import pytest

from tests.utils import DbUtils, PixAccount, PixDestination, RandomGenerator
from tests.utils.assertions import assert_decision

REAL = 100
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def act_of(payer: PixAccount, amount: int, destination: PixDestination, when: timedelta = timedelta(0)) -> str:
    _, transaction_id = payer.record(amount, when, destination=destination)

    return DbUtils.analysis_row(transaction_id)["analysis_details"]["act"]


class TestAct:
    """O ato do pagador: gasto típico, repasse ou outro."""

    def test_a_small_payment_to_a_known_recipient_is_a_typical_spend(self):
        payer, friend = PixAccount(), PixDestination()
        payer.send(100 * REAL, -3 * HOUR, "approved", destination=friend)

        assert act_of(payer, 1000 * REAL, friend) == "gasto_tipico"

    def test_one_cent_above_the_typical_spend_limit_is_something_else(self):
        payer, friend = PixAccount(), PixDestination()
        payer.send(100 * REAL, -3 * HOUR, "approved", destination=friend)

        assert act_of(payer, 1000 * REAL + 1, friend) == "outro"

    @pytest.mark.parametrize("age_days, expected", [(90, "gasto_tipico"), (89, "outro")])
    def test_a_company_needs_to_be_90_days_old_to_be_a_typical_destination(self, age_days, expected):
        company = PixDestination(age=age_days * DAY, document=RandomGenerator.generate_cnpj())

        assert act_of(PixAccount(), 500 * REAL, company) == expected

    def test_a_person_never_counts_as_a_typical_destination_without_a_prior_relationship(self):
        stranger = PixDestination(age=3650 * DAY)

        assert act_of(PixAccount(), 50 * REAL, stranger) == "outro"

    @pytest.mark.parametrize("amount, expected", [(980 * REAL, "outro"), (1000 * REAL, "repasse")])
    def test_forwarding_starts_at_half_of_what_was_received_in_the_last_hour(self, amount, expected):
        """Recebeu R$ 2.000 na última hora: R$ 980 são 49%, R$ 1.000 são 50% (o limite entra)."""
        payer = PixAccount()
        payer.fund(1000 * REAL, -30 * MINUTE)
        payer.fund(1000 * REAL, -20 * MINUTE)

        assert act_of(payer, amount, PixDestination()) == expected

    def test_what_the_account_already_sent_in_the_hour_counts_towards_the_half(self):
        payer = PixAccount()
        payer.fund(2000 * REAL, -30 * MINUTE)
        payer.send(600 * REAL, -10 * MINUTE, "approved", destination=PixDestination())

        assert act_of(payer, 400 * REAL, PixDestination()) == "repasse"

    def test_below_one_thousand_received_it_is_not_forwarding(self):
        payer = PixAccount()
        payer.fund(999 * REAL, -30 * MINUTE)

        assert act_of(payer, 900 * REAL, PixDestination()) == "outro"

    def test_what_was_received_more_than_an_hour_ago_does_not_count(self):
        payer = PixAccount()
        payer.fund(3000 * REAL, -61 * MINUTE)

        assert act_of(payer, 2000 * REAL, PixDestination()) == "outro"

    def test_a_rejected_or_two_factor_pix_is_not_money_received(self):
        """'Recebido' é o que o motor aprovou, não o que alguém tentou mandar."""
        payer = PixAccount()
        sender = PixAccount()
        sender.send(6000 * REAL, -30 * MINUTE, "two_factor_required", destination=payer.as_destination())

        assert act_of(payer, 3000 * REAL, PixDestination()) == "outro"

    def test_forwarding_to_a_company_with_a_young_account_is_still_forwarding(self):
        payer = PixAccount()
        payer.fund(2000 * REAL, -30 * MINUTE)
        shell_company = PixDestination(age=10 * DAY, document=RandomGenerator.generate_cnpj())

        assert act_of(payer, 1500 * REAL, shell_company) == "repasse"

    def test_forwarding_to_an_established_company_is_not_forwarding(self):
        payer = PixAccount()
        payer.fund(2000 * REAL, -30 * MINUTE)
        supplier = PixDestination(age=400 * DAY, document=RandomGenerator.generate_cnpj())

        assert act_of(payer, 1500 * REAL, supplier) == "outro"

    def test_a_typical_spend_prevails_over_forwarding(self):
        payer, friend = PixAccount(), PixDestination()
        payer.send(100 * REAL, -3 * HOUR, "approved", destination=friend)
        payer.fund(1000 * REAL, -30 * MINUTE)

        assert act_of(payer, 900 * REAL, friend) == "gasto_tipico"

    def test_a_clean_account_forwarding_is_decided_by_the_base_rules(self):
        """Repasse sem nenhuma evidência da conta não é rejeitado: o módulo só combina estado e ato."""
        payer = PixAccount()
        payer.fund(2000 * REAL, -30 * MINUTE)

        _, response = payer.pix(1500 * REAL, destination=PixDestination())

        assert_decision(response, "approved", "POLICY_PASSED")
