from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from rules.context import DictSignals, LocalEvidence, PixContext
from rules.decision import Decision, Status
from rules.parameters import (
    E1_REPORTERS_THRESHOLD,
    E2_WINDOW,
    E3_WINDOW,
    E5_WINDOW,
    E4_OPEN_REPORTS_THRESHOLD,
    ESTABLISHED_CNPJ_AGE,
    TYPICAL_SPEND_LIMIT,
)
from rules.reasons import ReasonCode


# O estado da conta: descreve a CONTA, não a transação, e sozinho não decide nada.
NAO = "nao"
SUSPEITA = "suspeita"
CONFIRMADA = "confirmada"

# O ato do pagador.
GASTO_TIPICO = "gasto_tipico"
REPASSE = "repasse"
OUTRO = "outro"


@dataclass(frozen=True)
class AccountEvaluation:
    """O estado de uma conta, as evidências que o formaram e quando a mais antiga começou."""

    state: str
    evidences: tuple
    evidence_start: Optional[datetime]


@dataclass(frozen=True)
class MuleResult:
    """O que o módulo conclui do contexto, sem tocar no banco."""

    payer: AccountEvaluation
    destination: AccountEvaluation
    act: str
    prior_relationship: bool
    payer_dict_status: str
    destination_dict_status: str

    def to_details(self) -> dict:
        """O retrato do momento da decisão, para auditoria (nunca devolvido na resposta)."""
        destination_since = self.destination.evidence_start
        return {
            "dict_status": {"payer": self.payer_dict_status, "destination": self.destination_dict_status},
            "payer": {"state": self.payer.state, "evidences": list(self.payer.evidences)},
            "destination": {
                "state": self.destination.state,
                "evidences": list(self.destination.evidences),
                "evidence_since": destination_since.isoformat() if destination_since else None,
            },
            "act": self.act,
            "prior_relationship": self.prior_relationship,
        }


def dict_signals(status: str, response: Optional[dict]) -> DictSignals:
    """Traduz a resposta do DICT em E1 e E4. Sem resposta, os dois são desconhecidos (`None`).

    E1: conta laranja ou golpista marcada nos últimos 90 dias, ou o titular
    marcado por 2 ou mais instituições. E4: notificações de infração abertas.
    """
    if response is None:
        return DictSignals(status=status, e1=None, e4=None)

    owner = response["OwnerStatistics"]
    markers = owner["FraudMarkers"]
    e1 = (
        markers["MuleAccounts"]["d90"] >= 1
        or markers["ScammerAccounts"]["d90"] >= 1
        or markers["DistinctFraudReporters"]["d90"] >= E1_REPORTERS_THRESHOLD
    )
    e4 = owner["InfractionReports"]["OpenReports"] >= E4_OPEN_REPORTS_THRESHOLD

    return DictSignals(status=status, e1=e1, e4=e4)


def classify_account(
    dict_signals_: DictSignals,
    e1_since: Optional[datetime],
    e4_since: Optional[datetime],
    local: LocalEvidence,
    t: datetime,
) -> AccountEvaluation:
    """O estado da conta a partir das cinco evidências.

    `confirmada` com E1, ou com 2 ou mais evidências entre E2 e E5; `suspeita`
    com exatamente 1 entre E2 e E5; `nao` sem nenhuma. Desconhecido (`None`)
    nunca conta como evidência.

    O início de cada evidência é o que entra na "relação anterior": E1 e E4, a
    primeira vez que o motor viu a marca (ou o próprio Pix atual); E2, E3 e E5,
    o início da janela de cada uma. O da conta é o mais antigo entre os presentes.
    """
    starts = {}
    if dict_signals_.e1:
        starts["E1"] = e1_since or t
    if local.e2:
        starts["E2"] = t - E2_WINDOW
    if local.e3:
        starts["E3"] = t - E3_WINDOW
    if dict_signals_.e4:
        starts["E4"] = e4_since or t
    if local.e5:
        starts["E5"] = t - E5_WINDOW

    evidences = tuple(sorted(starts))
    others = len([code for code in evidences if code != "E1"])
    if "E1" in evidences or others >= 2:
        state = CONFIRMADA
    elif others == 1:
        state = SUSPEITA
    else:
        state = NAO

    return AccountEvaluation(state, evidences, min(starts.values()) if starts else None)


def classify_act(context: PixContext) -> str:
    """O tipo de ato do pagador: gasto típico, repasse ou outro.

    Gasto típico é testado primeiro e prevalece: até R$ 1.000 para um titular
    que o pagador já conhecia (aprovação anterior) ou para um CNPJ com conta de
    90 dias ou mais.
    """
    request = context.request
    known_recipient = context.mule.first_approval_to_destination is not None
    is_cnpj = len(request.destination_document) == 14
    established_cnpj = is_cnpj and request.transaction_date - request.destination_opening_date >= ESTABLISHED_CNPJ_AGE

    if request.amount <= TYPICAL_SPEND_LIMIT and (known_recipient or established_cnpj):
        return GASTO_TIPICO

    return OUTRO


def evaluate(context: PixContext) -> MuleResult:
    """Classifica as duas contas e o ato, e diz se havia relação anterior com o destino."""
    t = context.request.transaction_date
    mule = context.mule

    payer = classify_account(context.payer_dict, None, None, mule.payer_local, t)
    destination = classify_account(
        context.destination_dict, mule.destination_e1_since, mule.destination_e4_since, mule.destination_local, t
    )

    # Relação anterior: o pagador já tinha uma aprovação para este titular ANTES
    # da evidência mais antiga do destino. É a mãe que já mandava a mesada antes
    # de o filho virar laranja; uma "relação" criada depois da suspeita não vale.
    first_approval = mule.first_approval_to_destination
    prior_relationship = bool(
        first_approval is not None and destination.evidence_start is not None and first_approval < destination.evidence_start
    )

    return MuleResult(
        payer=payer,
        destination=destination,
        act=classify_act(context),
        prior_relationship=prior_relationship,
        payer_dict_status=context.payer_dict.status,
        destination_dict_status=context.destination_dict.status,
    )


def mule_decision(result: MuleResult) -> Optional[Decision]:
    """L1, L2 e L3: a primeira rejeição do módulo, ou `None` se nenhuma se aplica.

    Todas rejeitam, e cada uma combina o estado de uma conta com o ato. O
    módulo nunca pede 2FA (contra laranja, quem confirma é o próprio operador)
    e nunca decide sozinho o status final: a política aplica a ordem.
    """
    if result.destination.state == CONFIRMADA and not result.prior_relationship:
        return Decision(
            Status.REJECTED,
            ReasonCode.MULE_DESTINATION,
            "A conta de destino tem sinais confirmados de conta laranja e o pagador não tinha relação anterior com ela.",
            reason_extra=_reason_extra("destination", result.destination, result.act),
        )

    if result.payer.state == CONFIRMADA and result.act != GASTO_TIPICO:
        return Decision(
            Status.REJECTED,
            ReasonCode.MULE_PAYER,
            "A conta pagadora tem sinais confirmados de conta laranja; só gastos típicos são permitidos.",
            reason_extra=_reason_extra("payer", result.payer, result.act),
        )

    return None


def _reason_extra(account: str, evaluation: AccountEvaluation, act: str) -> dict:
    return {
        "account": account,
        "account_state": evaluation.state,
        "evidences": list(evaluation.evidences),
        "act": act,
    }
