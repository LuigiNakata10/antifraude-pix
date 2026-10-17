from rules.context import PixContext
from rules.decision import Decision, Status
from rules.parameters import (
    DAILY_LIMIT,
    DEVICE_WAIT,
    FREQUENCY_THRESHOLD,
    HIGH_AMOUNT,
    NEW_ACCOUNT_AGE,
    NEW_ACCOUNT_LIMIT,
)
from rules.reasons import ReasonCode


def decide(context: PixContext) -> Decision:
    """A política antifraude: uma função pura, do contexto para uma decisão.

    Sem banco, sem I/O, sem relógio: o mesmo contexto dá sempre a mesma
    decisão. Devolve o PRIMEIRO resultado aplicável, na ordem
    R1, R2, L1, L2, L3, R4, R3, ou POLICY_PASSED quando nenhuma condição de
    intervenção foi acionada.

    A ordem é uma convenção de explicação: R1 antes de R2 por ser a restrição
    específica da conta nova, e rejeição antes de 2FA. Um único motivo sai na
    decisão, mesmo que outras regras também fossem acionadas.
    """
    request = context.request
    history = context.history
    projected_amount = history.approved_amount_24h + request.amount

    account_is_new = request.transaction_date < request.source_opening_date + NEW_ACCOUNT_AGE
    if account_is_new and projected_amount > NEW_ACCOUNT_LIMIT:
        return Decision(
            Status.REJECTED,
            ReasonCode.NEW_ACCOUNT_LIMIT_EXCEEDED,
            "Limite de conta nova excedido: o acumulado de 24 horas, com este Pix, passa do teto.",
            observed_amount=projected_amount,
            limit_amount=NEW_ACCOUNT_LIMIT,
        )

    if projected_amount > DAILY_LIMIT:
        return Decision(
            Status.REJECTED,
            ReasonCode.DAILY_LIMIT_EXCEEDED,
            "Teto diário excedido: o acumulado de 24 horas, com este Pix, passa do limite.",
            observed_amount=projected_amount,
            limit_amount=DAILY_LIMIT,
        )

    # L1, L2 e L3 (módulo de conta laranja) entram aqui, antes dos pedidos de 2FA:
    # rejeição prevalece sobre 2FA.

    first_approval = history.first_device_approved_at
    device_is_known = first_approval is not None and request.transaction_date >= first_approval + DEVICE_WAIT
    if not device_is_known and request.amount >= HIGH_AMOUNT:
        return Decision(
            Status.TWO_FACTOR_REQUIRED,
            ReasonCode.NEW_DEVICE_HIGH_AMOUNT,
            "Confirmação adicional: valor elevado em um aparelho ainda não conhecido para esta conta.",
            observed_amount=request.amount,
            limit_amount=HIGH_AMOUNT,
        )

    projected_attempts = history.attempts_2m + 1
    if projected_attempts >= FREQUENCY_THRESHOLD:
        return Decision(
            Status.TWO_FACTOR_REQUIRED,
            ReasonCode.HIGH_FREQUENCY,
            "Confirmação adicional: várias solicitações da conta em um intervalo curto.",
            observed_count=projected_attempts,
            limit_count=FREQUENCY_THRESHOLD,
        )

    return Decision(
        Status.APPROVED,
        ReasonCode.POLICY_PASSED,
        "Nenhuma condição de intervenção da política foi acionada.",
    )
