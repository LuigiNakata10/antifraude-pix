import dataclasses

from rules import laranja
from rules.context import PixContext
from rules.decision import Decision, Status
from rules.parameters import (
    ACCOUNT_AVERAGE_MULTIPLIER,
    DAILY_LIMIT,
    DEVICE_WAIT,
    FREQUENCY_THRESHOLD,
    HIGH_AMOUNT,
    MINIMUM_ACCOUNT_AVERAGE,
    NEW_ACCOUNT_AGE,
    NEW_ACCOUNT_LIMIT,
)
from rules.reasons import ReasonCode


def decide(context: PixContext) -> Decision:
    """A política antifraude: uma função pura, do contexto para uma decisão.

    Sem banco, sem I/O, sem relógio: o mesmo contexto dá sempre a mesma
    decisão. Devolve o PRIMEIRO resultado aplicável, na ordem
    R1, R2, L1, L2, L3, R4, R3, R5, ou POLICY_PASSED quando nenhuma condição de
    intervenção foi acionada.

    A ordem é uma convenção de explicação: R1 antes de R2 por ser a restrição
    específica da conta nova, e rejeição antes de 2FA. Um único motivo sai na
    decisão, mesmo que outras regras também fossem acionadas. O retrato do
    módulo de conta laranja (estados, evidências, ato) acompanha QUALQUER
    decisão em `analysis_details`, para auditoria.
    """
    mule = laranja.evaluate(context)

    return dataclasses.replace(_first_applicable(context, mule), analysis_details=mule.to_details())


def _first_applicable(context: PixContext, mule: laranja.MuleResult) -> Decision:
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

    # Módulo de conta laranja (L1, L2, L3), antes dos pedidos de 2FA: rejeição
    # prevalece sobre 2FA.
    mule_decision = laranja.mule_decision(mule)
    if mule_decision is not None:
        return mule_decision

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

    # média = soma / quantidade. Multiplicação cruzada evita arredondar
    # frações de centavo e mantém as duas comparações estritas e exatas.
    approved_count = history.approved_count_total
    approved_total = history.approved_amount_total
    if (
        approved_count > 0
        and approved_total > MINIMUM_ACCOUNT_AVERAGE * approved_count
        and request.amount * approved_count > ACCOUNT_AVERAGE_MULTIPLIER * approved_total
    ):
        return Decision(
            Status.TWO_FACTOR_REQUIRED,
            ReasonCode.AMOUNT_ABOVE_ACCOUNT_AVERAGE,
            "Confirmação adicional: o Pix supera dez vezes a média histórica aprovada da conta, que é maior que R$ 500.",
            observed_amount=request.amount,
            reason_extra={
                "historical_total_amount": approved_total,
                "historical_transaction_count": approved_count,
                "average_multiplier": ACCOUNT_AVERAGE_MULTIPLIER,
                "minimum_average_amount": MINIMUM_ACCOUNT_AVERAGE,
            },
        )

    return Decision(
        Status.APPROVED,
        ReasonCode.POLICY_PASSED,
        "Nenhuma condição de intervenção da política foi acionada.",
    )
