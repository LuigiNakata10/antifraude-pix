from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Optional

from rules.context import AccountFlows, DictSignals, LocalEvidence, PixContext
from rules.decision import Decision, Status
from rules.parameters import (
    E1_REPORTERS_THRESHOLD,
    E2_REPUTATION_AGE,
    E2_REPUTATION_COUNTERPARTIES,
    E2_SHARE_PERCENT,
    E3_FIRST_TIME_HOLDERS,
    E3_FIRST_TIME_HOLDERS_COMPANY,
    E3_HOLDERS,
    E3_HOLDERS_COMPANY,
    E4_OPEN_REPORTS_THRESHOLD,
    E5_ACCOUNT_AGE,
    E5_AMOUNT,
    E5_HOLDERS,
    ESTABLISHED_CNPJ_AGE,
    REPASSE_MIN_RECEIVED,
    REPASSE_SHARE_PERCENT,
    TYPICAL_SPEND_LIMIT,
)
from rules.reasons import ReasonCode


# O estado da conta: descreve a CONTA, não a transação, e sozinho não decide nada.
NAO = "nao"
SUSPEITA = "suspeita"
SUSPEITA_ELEVADA = "suspeita_elevada"

# O ato do pagador.
GASTO_TIPICO = "gasto_tipico"
REPASSE = "repasse_aparente"
OUTRO = "outro"


@dataclass(frozen=True)
class AccountEvaluation:
    """O estado de uma conta, as evidências que o formaram e quando a mais antiga começou."""

    state: str
    evidences: tuple
    evidence_start: Optional[datetime]
    observed: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MuleResult:
    """O que o módulo conclui do contexto, sem tocar no banco."""

    payer: AccountEvaluation
    destination: AccountEvaluation
    act: str
    prior_relationship: bool
    payer_dict_status: str
    destination_dict_status: str
    incoming_amount_1h: int = 0
    projected_outgoing_amount_1h: int = 0

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
            "evidence_values": {"payer": self.payer.observed, "destination": self.destination.observed},
        }


def dict_signals(status: str, response: Optional[dict], at: Optional[datetime] = None) -> DictSignals:
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

    # Extensão própria do mock: a data de início não é deduzida da primeira consulta.
    since = response.get("EvidenceSince", {})
    try:
        starts = {name: datetime.fromisoformat(value.replace("Z", "+00:00"))
                  for name, value in since.items() if name in ("E1", "E4") and value is not None}
        if any(value.tzinfo is None or (at is not None and value > at) for value in starts.values()):
            raise ValueError("Início de evidência sem fuso ou posterior à transação")
    except (ValueError, AttributeError, TypeError):
        return DictSignals(status="indisponivel", e1=None, e4=None)
    observed = {
        "E1": {"mule_markers": markers["MuleAccounts"]["d90"],
               "scammer_markers": markers["ScammerAccounts"]["d90"],
               "distinct_reporters": markers["DistinctFraudReporters"]["d90"],
               "minimum_reporters": E1_REPORTERS_THRESHOLD, "window_days": 90},
        "E4": {"open_reports": owner["InfractionReports"]["OpenReports"], "minimum_reports": E4_OPEN_REPORTS_THRESHOLD},
    }
    return DictSignals(status=status, e1=e1, e4=e4, e1_since=starts.get("E1"),
                       e4_since=starts.get("E4"), observed=observed)


def local_evidence(flows: AccountFlows, opening_date: datetime, document_number: str, t: datetime) -> LocalEvidence:
    """E2, E3 e E5 de uma conta, a partir dos indicadores do grafo.

    E2: mais de 50% do que recebeu em 30 dias veio de conta com E1, ou usou o
    aparelho de uma, mas só se a conta tem menos de 90 dias ou menos de 10
    contrapartes (a trava de reputação).
    E3: muitos titulares enviando na última hora, ao menos três estreantes.
    E5: conta com menos de 7 dias recebendo volume alto de vários titulares.
    """
    age = t - opening_date

    low_reputation = age < E2_REPUTATION_AGE or flows.counterparties < E2_REPUTATION_COUNTERPARTIES
    money_from_marked = (
        flows.received_30d > 0 and flows.received_30d_from_e1 * 100 > flows.received_30d * E2_SHARE_PERCENT
    )
    e2 = low_reputation and (money_from_marked or flows.shares_device_with_e1)

    is_company = len(document_number) == 14
    holders_needed = E3_HOLDERS_COMPANY if is_company else E3_HOLDERS
    first_time_needed = E3_FIRST_TIME_HOLDERS_COMPANY if is_company else E3_FIRST_TIME_HOLDERS
    e3 = flows.holders_1h >= holders_needed and flows.first_time_holders_1h >= first_time_needed

    e5 = age < E5_ACCOUNT_AGE and flows.received_24h > E5_AMOUNT and flows.holders_24h >= E5_HOLDERS

    return LocalEvidence(e2=e2, e3=e3, e5=e5)


def classify_account(
    dict_signals_: DictSignals,
    local: LocalEvidence,
) -> AccountEvaluation:
    """Eleva somente por E1 ou E2+E4; ausência de datas não vira data inventada."""
    positive = {"E1": dict_signals_.e1, "E2": local.e2, "E3": local.e3,
                "E4": dict_signals_.e4, "E5": local.e5}
    evidences = tuple(code for code, present in positive.items() if present)
    elevated = "E1" in evidences or {"E2", "E4"} <= set(evidences)
    state = SUSPEITA_ELEVADA if elevated else SUSPEITA if evidences else NAO
    # Sem história externa de E2, não conseguimos datar a combinação E2+E4.
    evidence_start = dict_signals_.e1_since if "E1" in evidences else None
    if {"E2", "E4"} <= set(evidences):
        evidence_start = None
    return AccountEvaluation(state, evidences, evidence_start, dict_signals_.observed)


def classify_act(context: PixContext) -> str:
    """O tipo de ato do pagador: gasto típico, repasse ou outro.

    Repasse é testado primeiro. Gasto típico: até R$ 1.000 para um titular
    que o pagador já conhecia (aprovação anterior) ou para um CNPJ com conta de
    90 dias ou mais. Repasse: a conta recebeu pelo menos R$ 1.000 na última hora,
    este Pix leva o enviado na hora a 50% ou mais disso, e o destino é pessoa
    física ou CNPJ com conta de menos de 90 dias.
    """
    request = context.request
    known_recipient = context.mule.first_approval_to_destination is not None
    is_cnpj = len(request.destination_document) == 14
    established_cnpj = is_cnpj and request.transaction_date - request.destination_opening_date >= ESTABLISHED_CNPJ_AGE

    flows = context.mule.payer_flows
    forwarded = flows.sent_1h + request.amount
    destination_is_person_or_young_company = len(request.destination_document) == 11 or (is_cnpj and not established_cnpj)
    if (
        flows.received_1h >= REPASSE_MIN_RECEIVED
        and forwarded * 100 >= flows.received_1h * REPASSE_SHARE_PERCENT
        and destination_is_person_or_young_company
    ):
        return REPASSE
    if request.amount <= TYPICAL_SPEND_LIMIT and (known_recipient or established_cnpj):
        return GASTO_TIPICO
    return OUTRO


def evaluate(context: PixContext) -> MuleResult:
    """Classifica as duas contas e o ato, e diz se havia relação anterior com o destino."""
    t = context.request.transaction_date
    mule = context.mule

    request = context.request
    payer_local = local_evidence(mule.payer_flows, request.source_opening_date, request.payer_document, t)
    destination_local = local_evidence(
        mule.destination_flows, request.destination_opening_date, request.destination_document, t
    )

    payer = replace(classify_account(context.payer_dict, payer_local),
                    observed=_observed(context.payer_dict, mule.payer_flows, request.payer_document))
    destination = replace(classify_account(context.destination_dict, destination_local),
                          observed=_observed(context.destination_dict, mule.destination_flows, request.destination_document))

    # Só a data explícita da fonte permite estabelecer uma relação anterior.
    # E2+E4 tem início desconhecido, sem exceção presumida.
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
        incoming_amount_1h=mule.payer_flows.received_1h,
        projected_outgoing_amount_1h=mule.payer_flows.sent_1h + request.amount,
    )


def mule_decision(result: MuleResult) -> Optional[Decision]:
    """L1, L2 e L3: a primeira rejeição do módulo, ou `None` se nenhuma se aplica.

    Todas rejeitam, e cada uma combina o estado de uma conta com o ato. O
    módulo nunca pede 2FA (contra laranja, quem confirma é o próprio operador)
    e nunca decide sozinho o status final: a política aplica a ordem.
    """
    if result.destination.state == SUSPEITA_ELEVADA and not result.prior_relationship:
        return Decision(
            Status.REJECTED,
            ReasonCode.MULE_DESTINATION,
            "A conta de destino tem suspeita elevada de conta laranja e o pagador não tinha relação anterior com ela.",
            reason_extra=_reason_extra("destination", result.destination, result),
        )

    if result.payer.state == SUSPEITA_ELEVADA and result.act != GASTO_TIPICO:
        return Decision(
            Status.REJECTED,
            ReasonCode.MULE_PAYER,
            "A conta pagadora tem suspeita elevada de conta laranja; só gastos típicos são permitidos.",
            reason_extra=_reason_extra("payer", result.payer, result),
        )

    if result.payer.state == SUSPEITA and result.act == REPASSE:
        return Decision(
            Status.REJECTED,
            ReasonCode.SUSPECTED_MULE_FORWARDING,
            "A conta pagadora tem sinais de conta de passagem e este Pix repassa o que ela acabou de receber.",
            reason_extra=_reason_extra("payer", result.payer, result),
        )

    return None


def _observed(signals: DictSignals, flows: AccountFlows, document: str) -> dict:
    is_company = len(document) == 14
    return {**signals.observed,
            "E2": {"incoming_amount_30d": flows.received_30d, "marked_incoming_amount_30d": flows.received_30d_from_e1,
                   "shared_marked_device": flows.shares_device_with_e1, "counterparties_30d": flows.counterparties},
            "E3": {"holders_1h": flows.holders_1h, "new_holders_1h": flows.first_time_holders_1h,
                   "holder_threshold": E3_HOLDERS_COMPANY if is_company else E3_HOLDERS,
                   "new_holder_threshold": E3_FIRST_TIME_HOLDERS_COMPANY if is_company else E3_FIRST_TIME_HOLDERS},
            "E5": {"incoming_amount_24h": flows.received_24h, "holders_24h": flows.holders_24h}}


def _reason_extra(account: str, evaluation: AccountEvaluation, result: MuleResult) -> dict:
    selected = evaluation.evidences
    if evaluation.state == SUSPEITA_ELEVADA:
        selected = ("E1",) if "E1" in selected else ("E2", "E4")
    reason = {
        "account": account,
        "account_state": evaluation.state,
        "evidences": list(selected),
        "evidence_values": {code: evaluation.observed[code] for code in selected if code in evaluation.observed},
        "act": result.act,
    }
    if account == "payer" and result.act == REPASSE:
        reason.update({"incoming_amount_1h": result.incoming_amount_1h,
                       "projected_outgoing_amount_1h": result.projected_outgoing_amount_1h,
                       "minimum_incoming_amount": REPASSE_MIN_RECEIVED, "threshold_percent": REPASSE_SHARE_PERCENT})
    return reason
