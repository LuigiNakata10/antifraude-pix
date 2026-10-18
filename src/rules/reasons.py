from enum import Enum


class ReasonCode(str, Enum):
    """O único motivo determinante de uma decisão, em código.

    Os mesmos valores estão no CHECK de `pix_analysis.reason_code`
    (database/database.sql): o banco recusa um código que não esteja aqui.
    Novos códigos exigem a migração correspondente em bancos existentes.
    """

    NEW_ACCOUNT_LIMIT_EXCEEDED = "NEW_ACCOUNT_LIMIT_EXCEEDED"  # R1
    DAILY_LIMIT_EXCEEDED = "DAILY_LIMIT_EXCEEDED"  # R2
    MULE_DESTINATION = "MULE_DESTINATION"  # L1
    MULE_PAYER = "MULE_PAYER"  # L2
    SUSPECTED_MULE_FORWARDING = "SUSPECTED_MULE_FORWARDING"  # L3
    NEW_DEVICE_HIGH_AMOUNT = "NEW_DEVICE_HIGH_AMOUNT"  # R4
    HIGH_FREQUENCY = "HIGH_FREQUENCY"  # R3
    AMOUNT_ABOVE_ACCOUNT_AVERAGE = "AMOUNT_ABOVE_ACCOUNT_AVERAGE"  # R5
    POLICY_PASSED = "POLICY_PASSED"  # nenhuma condição de intervenção foi acionada
