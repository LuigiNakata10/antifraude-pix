from enum import Enum


class ReasonCode(str, Enum):
    """O único motivo determinante de uma decisão, em código.

    Os mesmos oito valores estão no CHECK de `pix_analysis.reason_code`
    (database/database.sql): o banco recusa um código que não esteja aqui.
    Os nomes são uma proposta a confirmar com quem implementa as regras.
    """

    NEW_ACCOUNT_LIMIT_EXCEEDED = "NEW_ACCOUNT_LIMIT_EXCEEDED"  # R1
    DAILY_LIMIT_EXCEEDED = "DAILY_LIMIT_EXCEEDED"  # R2
    MULE_DESTINATION = "MULE_DESTINATION"  # L1
    MULE_PAYER = "MULE_PAYER"  # L2
    SUSPECTED_MULE_FORWARDING = "SUSPECTED_MULE_FORWARDING"  # L3
    NEW_DEVICE_HIGH_AMOUNT = "NEW_DEVICE_HIGH_AMOUNT"  # R4
    HIGH_FREQUENCY = "HIGH_FREQUENCY"  # R3
    POLICY_PASSED = "POLICY_PASSED"  # nenhuma condição de intervenção foi acionada
