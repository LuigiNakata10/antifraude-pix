from dataclasses import dataclass, field
from typing import Optional

from rules.parameters import POLICY_VERSION
from rules.reasons import ReasonCode


class Status:
    """Os três resultados do contrato do desafio."""

    APPROVED = "approved"
    TWO_FACTOR_REQUIRED = "two_factor_required"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Decision:
    """O que a política devolve: um status e um único motivo.

    Os valores são sempre em centavos. `observed_amount` é o valor que a regra
    mediu (nas regras de teto, o acumulado projetado, já com o Pix atual) e
    `limit_amount` é o limiar dela. A regra de frequência explica uma
    CONTAGEM, não um valor, e usa `observed_count` e `limit_count`. Cada regra
    preenche só os campos dela; os outros ficam vazios.
    """

    status: str
    reason_code: ReasonCode
    description: str
    observed_amount: Optional[int] = None
    limit_amount: Optional[int] = None
    observed_count: Optional[int] = None
    limit_count: Optional[int] = None
    # Campos próprios do motivo: evidências do módulo de laranja ou soma,
    # quantidade e parâmetros da média (R5). Nunca documento nem identidade.
    reason_extra: dict = field(default_factory=dict)
    # Auditoria interna: estados, evidências, ato e `dict_status`. NUNCA volta na resposta.
    analysis_details: dict = field(default_factory=dict)

    def to_metadata(self) -> dict:
        """O `metadata` da resposta: a versão da política e só o motivo determinante."""
        reason = {"code": self.reason_code.value, "description": self.description}
        for name in ("observed_amount", "limit_amount", "observed_count", "limit_count"):
            value = getattr(self, name)
            if value is not None:
                reason[name] = value
        reason.update(self.reason_extra)

        return {"policy_version": POLICY_VERSION, "reason": reason}
