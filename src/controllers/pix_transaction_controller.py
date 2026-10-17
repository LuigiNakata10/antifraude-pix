import re
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from connectors import DictQuery
from constants import INSTITUTION_ISPB
from controllers.base_controller import BaseController
from controllers.dict_controller import DictController
from dtos import PixAnalysisDTO
from errors import (
    AccountOpenedAfterTransaction,
    InvalidTransactionDate,
    NotFoundPixAnalysis,
    OutOfOrderTransaction,
    TransactionIdConflict,
)
from models import PayerAccount, PixAnalysis
from repositories import PayerAccountRepository, PixAnalysisRepository
from rules import PixRequest, decide
from rules.laranja import dict_signals
from utils.payload_normalizer import normalize_payload


class PixTransactionController(BaseController):
    """Orquestra a análise de um Pix: a ordem dos passos, a trava e o commit.

    O controller não decide o Pix (quem decide é a política pura de
    src/rules/) e não escreve consulta (quem consulta são os repositories).
    O que é dele: a ORDEM, a trava da conta pagadora e o `commit`, que é a
    última linha antes do return.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.analysis_repository = PixAnalysisRepository(self.context)
        self.payer_account_repository = PayerAccountRepository(self.context)
        self.dict_controller = DictController()

    def create(self, payload: dict) -> tuple:
        """Analisa um Pix e grava a decisão. Devolve (resposta, é_novo).

        A ordem é regra, e cada passo tem um porquê:

          1. normalizar e conferir a coerência do pedido, ainda sem banco: o que
             é erro de entrada nunca consome limite nem conta em frequência;
          2. procurar o `id`: um Pix já analisado não é analisado de novo;
          3. consultar o DICT, FORA da transação, para a trava da conta nunca
             ficar presa esperando a rede. Indisponível vira "desconhecido";
          4. travar a conta pagadora (e criá-la se for a primeira vez);
          5. procurar o `id` DE NOVO: um reenvio pode ter concluído enquanto
             este pedido esperava a trava;
          6. recusar o pedido retroativo, que obrigaria a reavaliar decisões
             já tomadas, e montar o contexto, lendo o histórico só depois da trava;
          7. decidir, pela política pura;
          8. gravar a análise e commitar. Qualquer falha antes disso desfaz
             tudo: falha técnica nunca vira decisão.

        Dois pedidos com o mesmo `id` em contas diferentes não dividem trava:
        quem decide é o UNIQUE de `transaction_id`. O perdedor leva o
        IntegrityError, desfaz tudo, relê a análise do vencedor e a trata
        como um reenvio (200 se equivalente, 409 se não).
        """
        received_at = datetime.now(timezone.utc)
        request = self.normalize(payload)

        existing = self.analysis_repository.get_by_transaction_id(request.transaction_id)
        if existing is not None:
            return self.replay(existing, payload), False

        payer_dict, destination_dict = self.consult_dict(request, payload)

        self.start_write_transaction()
        try:
            with self.lock_timeout_guard():
                payer_account = self.payer_account_repository.get_or_create_locked(
                    request.payer_branch, request.payer_account_number
                )

                existing = self.analysis_repository.get_by_transaction_id(request.transaction_id)
                if existing is not None:
                    self.session.rollback()
                    return self.replay(existing, payload), False

                self.ensure_in_order(payer_account, request)

                context = self.analysis_repository.build_context(payer_account, request, payer_dict, destination_dict)
                decision = decide(context)
                analysis = self.analysis_repository.create(
                    payer_account, request, payload, decision, received_at, payer_dict, destination_dict
                )
                self.session.flush()
        except IntegrityError as error:
            if not self.is_unique_violation(error):
                raise

            self.session.rollback()
            existing = self.analysis_repository.get_by_transaction_id(request.transaction_id)
            if existing is None:
                raise

            return self.replay(existing, payload), False

        response = PixAnalysisDTO.obj_to_dict(analysis)
        self.logger.info(f"ANALISE {request.transaction_id} {decision.status} {decision.reason_code.value}")
        self.session.commit()

        return response, True

    def consult_dict(self, request: PixRequest, payload: dict) -> tuple:
        """Pergunta ao DICT (ou ao cache) sobre o pagador e o destino e devolve (E1/E4 do pagador, E1/E4 do destino)."""
        destination = payload["destination_account"]
        payer_query = DictQuery(INSTITUTION_ISPB, request.payer_branch, request.payer_account_number, request.payer_document)
        destination_query = DictQuery(
            destination["participant"], destination["branch"], destination["account_number"], request.destination_document
        )

        payer, destination = self.dict_controller.lookup(payer_query, destination_query)

        return dict_signals(payer.status, payer.response), dict_signals(destination.status, destination.response)

    def ensure_in_order(self, payer_account: PayerAccount, request: PixRequest) -> None:
        """Recusa o Pix anterior ao último já analisado da mesma conta (422).

        Data igual à última é aceita. A checagem precisa vir DEPOIS da trava,
        porque lê o histórico da conta.
        """
        latest = self.analysis_repository.get_latest_transaction_date(payer_account)
        if latest is not None and request.transaction_date < latest:
            raise OutOfOrderTransaction(
                request.transaction_date.isoformat(), latest.astimezone(timezone.utc).isoformat()
            )

    def get_by_transaction_id(self, transaction_id: str) -> dict:
        """Devolve a análise gravada, sem rodar as regras de novo.

        Não atualiza a idade do aparelho nem depende da versão atual da política.
        """
        analysis = self.analysis_repository.get_by_transaction_id(transaction_id)
        if analysis is None:
            raise NotFoundPixAnalysis(transaction_id)

        return PixAnalysisDTO.obj_to_dict(analysis)

    def replay(self, existing: PixAnalysis, payload: dict) -> dict:
        """O mesmo `id` de novo: a análise original se o conteúdo for equivalente, senão 409.

        A comparação é entre estruturas normalizadas, não entre textos JSON.
        Não reavalia nem grava nada: um reenvio não conta como nova tentativa.
        """
        if normalize_payload(existing.request_payload) != normalize_payload(payload):
            raise TransactionIdConflict(existing.transaction_id)

        return PixAnalysisDTO.obj_to_dict(existing)

    def normalize(self, payload: dict) -> PixRequest:
        """Valida o que o schema não sabe e devolve o pedido normalizado.

        O schema cobra FORMATO; aqui se cobra o que faz sentido. Datas que não
        existem no calendário e conta aberta depois do Pix são 422: a API
        entendeu o pedido, mas o valor não pode existir. Normaliza as datas
        para UTC e os documentos para só dígitos.
        """
        source = payload["source_account"]
        destination = payload["destination_account"]

        transaction_date = parse_date("transaction_date", payload["transaction_date"])
        source_opening_date = parse_date("source_account.opening_date", source["opening_date"])
        destination_opening_date = parse_date("destination_account.opening_date", destination["opening_date"])

        if source_opening_date > transaction_date:
            raise AccountOpenedAfterTransaction("source")
        if destination_opening_date > transaction_date:
            raise AccountOpenedAfterTransaction("destination")

        return PixRequest(
            transaction_id=payload["id"],
            amount=payload["amount"],
            transaction_date=transaction_date,
            payer_branch=source["branch"],
            payer_account_number=source["account_number"],
            payer_document=only_digits(source["owner"]["document_number"]),
            source_opening_date=source_opening_date,
            device_id=payload["source"]["device_id"],
            destination_key=f"{destination['participant']}:{destination['branch']}:{destination['account_number']}",
            destination_document=only_digits(destination["owner"]["document_number"]),
            destination_opening_date=destination_opening_date,
        )


def parse_date(field: str, value: str) -> datetime:
    """Lê a data ISO 8601 já com fuso e a converte para UTC.

    O `pattern` do schema garante a forma; o calendário só se confere aqui
    (30 de fevereiro, 25 horas e fuso de +99:00 passam no schema).
    """
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except ValueError:
        raise InvalidTransactionDate(field, value) from None


def only_digits(document_number: str) -> str:
    return re.sub(r"\D", "", document_number)
