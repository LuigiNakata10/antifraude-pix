from datetime import timedelta

from tests.utils import PixAccount, PixDestination
from tests.utils.assertions import assert_decision

REAL = 100  # R$ 1,00 em centavos: os cenários da política são escritos em reais.
SECOND = timedelta(seconds=1)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


class TestNewAccountLimit:
    """R1: conta com menos de 7 dias completos não passa de R$ 1.000 em 24 h, contando o Pix atual."""

    def test_c01_below_the_initial_limit_is_approved(self):
        account = PixAccount(age=3 * DAY)

        _, response = account.pix(500 * REAL)

        reason = assert_decision(response, "approved", "POLICY_PASSED")
        assert set(reason) == {"code", "description"}

    def test_c02_exactly_the_limit_is_approved(self):
        """R$ 700 aprovados + R$ 300 = R$ 1.000 exatos: o teto é 'acima de', então passa."""
        account = PixAccount(age=3 * DAY)
        account.send(700 * REAL, -2 * HOUR, "approved")

        _, response = account.pix(300 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_c03_one_real_above_the_limit_is_rejected(self):
        account = PixAccount(age=3 * DAY)
        account.send(700 * REAL, -2 * HOUR, "approved")

        _, response = account.pix(301 * REAL)

        reason = assert_decision(response, "rejected", "NEW_ACCOUNT_LIMIT_EXCEEDED")
        assert reason["observed_amount"] == 1001 * REAL
        assert reason["limit_amount"] == 1000 * REAL

    def test_c04_account_with_exactly_seven_days_is_no_longer_new(self):
        """Com exatamente 7 dias a conta deixa de ser nova: R$ 1.500 só encontra o teto geral."""
        account = PixAccount(age=7 * DAY)
        account.make_device_known()

        _, response = account.pix(1500 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_account_one_second_short_of_seven_days_is_still_new(self):
        account = PixAccount(age=7 * DAY - SECOND)
        account.make_device_known()

        _, response = account.pix(1500 * REAL)

        assert_decision(response, "rejected", "NEW_ACCOUNT_LIMIT_EXCEEDED")

    def test_c20_new_account_over_both_limits_reports_only_r1(self):
        account = PixAccount(age=3 * DAY)

        _, response = account.pix(11000 * REAL)

        assert_decision(response, "rejected", "NEW_ACCOUNT_LIMIT_EXCEEDED")


class TestDailyLimit:
    """R2: nenhuma conta passa de R$ 10.000 aprovados em 24 h, contando o Pix atual."""

    def test_c05_exactly_the_limit_is_approved(self):
        account = PixAccount()
        account.make_device_known()
        account.send(7000 * REAL, -2 * HOUR, "approved")

        _, response = account.pix(3000 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_c06_one_real_above_the_limit_is_rejected(self):
        account = PixAccount()
        account.make_device_known()
        account.send(7000 * REAL, -2 * HOUR, "approved")

        _, response = account.pix(3001 * REAL)

        reason = assert_decision(response, "rejected", "DAILY_LIMIT_EXCEEDED")
        assert reason["observed_amount"] == 10001 * REAL
        assert reason["limit_amount"] == 10000 * REAL

    def test_approval_exactly_24_hours_ago_is_out_of_the_window(self):
        """A janela é (t - 24h, t]: o aprovado em t - 24h exatos não conta."""
        account = PixAccount()
        account.make_device_known(hours_ago=50)
        account.send(9000 * REAL, -24 * HOUR, "approved")

        _, response = account.pix(1500 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_approval_one_second_inside_the_window_counts(self):
        account = PixAccount()
        account.make_device_known(hours_ago=50)
        account.send(9000 * REAL, -24 * HOUR + SECOND, "approved")

        _, response = account.pix(1500 * REAL)

        assert_decision(response, "rejected", "DAILY_LIMIT_EXCEEDED")

    def test_rejected_pix_does_not_consume_the_limit(self):
        account = PixAccount()
        account.make_device_known()
        account.send(9000 * REAL, -20 * MINUTE, "approved")
        account.send(2000 * REAL, -15 * MINUTE, "rejected")

        _, response = account.pix(1000 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_two_factor_pix_does_not_consume_the_limit(self):
        """Um Pix que pediu 2FA não foi aprovado: R$ 6.000 + R$ 9.000 não somam R$ 15.000."""
        account = PixAccount()
        account.send(6000 * REAL, -3 * HOUR, "two_factor_required")

        _, response = account.pix(9000 * REAL)

        assert_decision(response, "two_factor_required", "NEW_DEVICE_HIGH_AMOUNT")


class TestFrequency:
    """R3: a partir do terceiro pedido distinto em 2 minutos, qualquer valor, pede 2FA."""

    def test_c07_third_attempt_in_the_window_asks_for_two_factor(self):
        account = PixAccount()
        account.make_device_known()
        account.send(200 * REAL, -80 * SECOND, "approved")
        account.send(150 * REAL, -40 * SECOND, "approved")

        _, response = account.pix(300 * REAL)

        reason = assert_decision(response, "two_factor_required", "HIGH_FREQUENCY")
        assert reason["observed_count"] == 3
        assert reason["limit_count"] == 3

    def test_c08_rejected_attempts_also_count(self):
        account = PixAccount()
        account.make_device_known()
        account.send(9000 * REAL, -100 * SECOND, "approved")
        account.send(2000 * REAL, -50 * SECOND, "rejected")

        _, response = account.pix(1 * REAL)

        assert_decision(response, "two_factor_required", "HIGH_FREQUENCY")

    def test_second_attempt_in_the_window_is_approved(self):
        account = PixAccount()
        account.make_device_known()
        account.send(200 * REAL, -40 * SECOND, "approved")

        _, response = account.pix(150 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_attempt_exactly_two_minutes_ago_is_out_of_the_window(self):
        account = PixAccount()
        account.make_device_known()
        account.send(100 * REAL, -120 * SECOND, "approved")
        account.send(100 * REAL, -60 * SECOND, "approved")

        _, response = account.pix(100 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_attempt_one_second_inside_the_window_counts(self):
        account = PixAccount()
        account.make_device_known()
        account.send(100 * REAL, -119 * SECOND, "approved")
        account.send(100 * REAL, -60 * SECOND, "approved")

        _, response = account.pix(100 * REAL)

        assert_decision(response, "two_factor_required", "HIGH_FREQUENCY")


class TestNewDeviceHighAmount:
    """R4: aparelho sem 24 h de aprovação e Pix de R$ 5.000 ou mais pedem 2FA."""

    def test_c10_first_high_pix_of_an_account_without_approvals_asks_for_two_factor(self):
        account = PixAccount()

        _, response = account.pix(6000 * REAL)

        reason = assert_decision(response, "two_factor_required", "NEW_DEVICE_HIGH_AMOUNT")
        assert reason["observed_amount"] == 6000 * REAL
        assert reason["limit_amount"] == 5000 * REAL

    def test_c11_absence_of_history_alone_does_not_intervene(self):
        account = PixAccount()

        _, response = account.pix(500 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_c12_just_below_the_threshold_is_approved(self):
        account = PixAccount()

        _, response = account.pix(4999 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_c13_exactly_the_threshold_asks_for_two_factor_even_for_a_known_recipient(self):
        account = PixAccount()
        recipient = PixDestination()
        account.send(100 * REAL, -30 * HOUR, "approved", device_id="another-device", destination=recipient)

        _, response = account.pix(5000 * REAL, destination=recipient)

        assert_decision(response, "two_factor_required", "NEW_DEVICE_HIGH_AMOUNT")

    def test_c14_known_device_with_a_new_recipient_is_approved(self):
        account = PixAccount()
        account.make_device_known()

        _, response = account.pix(6000 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_c15_a_recent_recipient_account_does_not_add_intervention(self):
        account = PixAccount()
        account.make_device_known()

        _, response = account.pix(6000 * REAL, destination=PixDestination(age=2 * DAY))

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_c18_a_small_approval_does_not_dispense_the_two_factor_right_away(self):
        account = PixAccount()
        account.send(100 * REAL, -10 * MINUTE, "approved")

        _, response = account.pix(6000 * REAL)

        assert_decision(response, "two_factor_required", "NEW_DEVICE_HIGH_AMOUNT")

    def test_c19_after_the_initial_wait_a_recent_approval_does_not_restart_it(self):
        account = PixAccount()
        account.send(100 * REAL, -26 * HOUR, "approved")
        account.send(50 * REAL, -1 * HOUR, "approved")

        _, response = account.pix(6000 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_first_approval_exactly_24_hours_ago_makes_the_device_known(self):
        account = PixAccount()
        account.send(100 * REAL, -24 * HOUR, "approved")

        _, response = account.pix(6000 * REAL)

        assert_decision(response, "approved", "POLICY_PASSED")

    def test_first_approval_one_second_short_of_24_hours_does_not(self):
        account = PixAccount()
        account.send(100 * REAL, -24 * HOUR + SECOND, "approved")

        _, response = account.pix(6000 * REAL)

        assert_decision(response, "two_factor_required", "NEW_DEVICE_HIGH_AMOUNT")

    def test_two_factor_pix_does_not_start_the_device_wait(self):
        """Pedir 2FA não é aprovar: sem aprovação, o aparelho continua novo."""
        account = PixAccount()
        account.send(6000 * REAL, -3 * HOUR, "two_factor_required")

        _, response = account.pix(6000 * REAL)

        assert_decision(response, "two_factor_required", "NEW_DEVICE_HIGH_AMOUNT")


class TestRulePrecedence:
    """Ordem R1, R2, R4, R3: rejeição antes de 2FA, e um único motivo."""

    def test_c16_new_account_limit_prevails_over_new_device(self):
        account = PixAccount(age=3 * DAY)

        _, response = account.pix(5000 * REAL)

        assert_decision(response, "rejected", "NEW_ACCOUNT_LIMIT_EXCEEDED")

    def test_c17_daily_limit_prevails_over_frequency(self):
        account = PixAccount()
        account.make_device_known()
        account.send(4500 * REAL, -100 * SECOND, "approved")
        account.send(4500 * REAL, -50 * SECOND, "approved")

        _, response = account.pix(1500 * REAL)

        assert_decision(response, "rejected", "DAILY_LIMIT_EXCEEDED")

    def test_c21_new_device_prevails_over_frequency(self):
        account = PixAccount()
        account.send(100 * REAL, -100 * SECOND, "approved")
        account.send(100 * REAL, -50 * SECOND, "approved")

        _, response = account.pix(5000 * REAL)

        assert_decision(response, "two_factor_required", "NEW_DEVICE_HIGH_AMOUNT")
