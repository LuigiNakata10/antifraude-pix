from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import func

from database import Context
from models import PayerAccount, PixAnalysis
from rules import AccountHistory, Decision, PixContext, PixRequest
from rules.parameters import DAILY_WINDOW, FREQUENCY_WINDOW, POLICY_VERSION


class PixAnalysisRepository:
    """A camada que fala com a tabela `pix_analysis`. Só aqui existe query dela.

    Nenhuma regra de negócio mora aqui: esta classe busca e guarda. Quem decide
    o que fazer com o que ela devolve é o controller, e quem decide o Pix é a
    política pura de src/rules/.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_transaction_id(self, transaction_id: str) -> PixAnalysis:
        return self.session.query(PixAnalysis).filter(PixAnalysis.transaction_id == transaction_id).first()

    def get_latest_transaction_date(self, payer_account: PayerAccount) -> Optional[datetime]:
        """A maior `transaction_date` já analisada para a conta, com qualquer status."""
        return (
            self.session.query(func.max(PixAnalysis.transaction_date))
            .filter(PixAnalysis.payer_account_id == payer_account.id)
            .scalar()
        )

    def build_context(self, payer_account: PayerAccount, request: PixRequest, dict_available: bool) -> PixContext:
        """Monta o contexto único: tudo de que as regras precisam, em valores prontos.

        É o ÚNICO lugar que lê o histórico para a decisão, e só depois da trava
        da conta. As janelas são `(t - janela, t]`, com `t` a `transaction_date`
        do pedido: uma linha exatamente em `t - janela` não conta, e uma já
        gravada com data igual a `t` conta. O pedido atual ainda não está no
        banco: a regra o soma uma única vez.
        """
        t = request.transaction_date

        approved_amount = (
            self.session.query(func.sum(PixAnalysis.amount))
            .filter(
                PixAnalysis.payer_account_id == payer_account.id,
                PixAnalysis.status == "approved",
                PixAnalysis.transaction_date > t - DAILY_WINDOW,
                PixAnalysis.transaction_date <= t,
            )
            .scalar()
        )

        attempts = (
            self.session.query(func.count(PixAnalysis.id))
            .filter(
                PixAnalysis.payer_account_id == payer_account.id,
                PixAnalysis.transaction_date > t - FREQUENCY_WINDOW,
                PixAnalysis.transaction_date <= t,
            )
            .scalar()
        )

        first_device_approval = (
            self.session.query(func.min(PixAnalysis.transaction_date))
            .filter(
                PixAnalysis.payer_account_id == payer_account.id,
                PixAnalysis.device_id == request.device_id,
                PixAnalysis.status == "approved",
                PixAnalysis.transaction_date <= t,
            )
            .scalar()
        )

        return PixContext(
            request=request,
            history=AccountHistory(
                approved_amount_24h=int(approved_amount or 0),
                attempts_2m=int(attempts),
                first_device_approved_at=first_device_approval,
            ),
            dict_available=dict_available,
        )

    def create(
        self,
        payer_account: PayerAccount,
        request: PixRequest,
        payload: dict,
        decision: Decision,
        received_at: datetime,
        analysis_details: dict,
    ) -> PixAnalysis:
        """Grava a análise, uma única vez, já com a decisão.

        `pix_analysis` é append-only: nada é atualizado depois. O corpo vai em
        `request_payload` exatamente como veio; a normalização só acontece na
        hora de comparar um reenvio.
        """
        analysis = PixAnalysis()
        analysis.transaction_id = request.transaction_id
        analysis.analysis_key = str(uuid4())
        analysis.payer_account_id = payer_account.id
        analysis.amount = request.amount
        analysis.transaction_date = request.transaction_date
        analysis.source_opening_date = request.source_opening_date
        analysis.payer_document = request.payer_document
        analysis.device_id = request.device_id
        analysis.destination_key = request.destination_key
        analysis.destination_document = request.destination_document
        analysis.destination_opening_date = request.destination_opening_date
        analysis.received_at = received_at
        analysis.analyzed_at = datetime.now(timezone.utc)
        analysis.status = decision.status
        analysis.reason_code = decision.reason_code.value
        analysis.policy_version = POLICY_VERSION
        analysis.analysis_metadata = decision.to_metadata()
        analysis.analysis_details = analysis_details
        analysis.request_payload = payload

        self.session.add(analysis)

        return analysis
