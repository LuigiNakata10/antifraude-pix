from datetime import datetime
from typing import Optional

from sqlalchemy import distinct, func, select, union
from sqlalchemy.orm import aliased

from database import Context
from models import AccountLink, PixAnalysis
from rules import AccountFlows, PixRequest
from rules.parameters import E2_WINDOW, E3_WINDOW, E5_WINDOW, REPASSE_WINDOW


class AccountLinkRepository:
    """A camada que fala com a tabela `account_link`, as arestas do grafo de contas.

    Não há banco de grafos: cada evidência é uma consulta indexada sobre as
    arestas, ligadas ao `pix_analysis` que as gerou (para saber se o Pix foi
    aprovado e se o pagador tinha E1 naquele momento).

    Os tipos de aresta:
      * `pix`: do pagador para o destino, com valor: segue o dinheiro e separa
        vítima de cúmplice pela direção;
      * `device`: a conta e o aparelho usado: a mesma quadrilha em várias contas;
      * `document`: a conta e o titular: o mesmo titular em contas diferentes.
    IP não vira aresta (wi-fi público ligaria pessoas sem relação).

    Uma linha por evento, nunca um agregado atualizado. Nada aqui inclui o Pix
    atual, que ainda não foi gravado.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create_edges(self, analysis: PixAnalysis, request: PixRequest) -> None:
        """Grava as arestas de um Pix, no mesmo commit da análise (a análise já precisa ter id)."""
        edges = [
            ("pix", request.payer_key, request.destination_key, request.amount),
            ("device", request.payer_key, f"device:{request.device_id}", None),
            ("document", request.payer_key, f"document:{request.payer_document}", None),
            ("document", request.destination_key, f"document:{request.destination_document}", None),
        ]
        for link_type, from_key, to_key, amount in edges:
            link = AccountLink()
            link.pix_analysis_id = analysis.id
            link.from_key = from_key
            link.to_key = to_key
            link.link_type = link_type
            link.amount = amount
            link.seen_at = request.transaction_date
            self.session.add(link)

    def flows(self, key: str, t: datetime, current_device_id: Optional[str]) -> AccountFlows:
        """Os indicadores do grafo para a conta `key`, com as janelas `(t - janela, t]`."""
        return AccountFlows(
            received_30d=self._money(key, "in", t - E2_WINDOW, t),
            received_30d_from_e1=self._money(key, "in", t - E2_WINDOW, t, only_from_marked=True),
            shares_device_with_e1=self._shares_device_with_marked(key, t, current_device_id),
            counterparties=self._counterparties(key, t),
            holders_1h=self._holders(key, t - E3_WINDOW, t),
            first_time_holders_1h=self._holders(key, t - E3_WINDOW, t, first_time_only=True),
            received_24h=self._money(key, "in", t - E5_WINDOW, t),
            holders_24h=self._holders(key, t - E5_WINDOW, t),
            received_1h=self._money(key, "in", t - REPASSE_WINDOW, t),
            sent_1h=self._money(key, "out", t - REPASSE_WINDOW, t),
        )

    def _approved_pix_edges(self, window_start: Optional[datetime], t: datetime):
        """A base das consultas de dinheiro: arestas `pix` de análises `approved` em `(início, t]`."""
        query = (
            self.session.query(AccountLink)
            .join(PixAnalysis, PixAnalysis.id == AccountLink.pix_analysis_id)
            .filter(AccountLink.link_type == "pix", PixAnalysis.status == "approved", AccountLink.seen_at <= t)
        )
        if window_start is not None:
            query = query.filter(AccountLink.seen_at > window_start)

        return query

    def _money(self, key: str, direction: str, start: datetime, t: datetime, only_from_marked: bool = False) -> int:
        column = AccountLink.to_key if direction == "in" else AccountLink.from_key
        query = self._approved_pix_edges(start, t).filter(column == key)
        if only_from_marked:
            query = query.filter(PixAnalysis.payer_dict_e1.is_(True))

        return int(query.with_entities(func.coalesce(func.sum(AccountLink.amount), 0)).scalar())

    def _holders(self, key: str, start: datetime, t: datetime, first_time_only: bool = False) -> int:
        """Titulares distintos que enviaram à conta na janela; opcionalmente só os de primeira vez.

        De primeira vez: sem nenhum Pix aprovado para a conta ANTES do início da janela.
        """
        query = self._approved_pix_edges(start, t).filter(AccountLink.to_key == key)
        if first_time_only:
            earlier_link = aliased(AccountLink)
            earlier = aliased(PixAnalysis)
            sent_before = (
                self.session.query(earlier_link.id)
                .join(earlier, earlier.id == earlier_link.pix_analysis_id)
                .filter(
                    earlier_link.link_type == "pix",
                    earlier_link.to_key == key,
                    earlier.status == "approved",
                    earlier.payer_document == PixAnalysis.payer_document,
                    earlier_link.seen_at <= start,
                )
                .correlate(PixAnalysis)
                .exists()
            )
            query = query.filter(~sent_before)

        return int(query.with_entities(func.count(distinct(PixAnalysis.payer_document))).scalar())

    def _counterparties(self, key: str, t: datetime) -> int:
        """Titulares distintos com Pix aprovado com a conta, em qualquer direção, em todo o histórico."""
        received_from = (
            select(PixAnalysis.payer_document.label("document"))
            .join(AccountLink, AccountLink.pix_analysis_id == PixAnalysis.id)
            .where(AccountLink.link_type == "pix", AccountLink.to_key == key, PixAnalysis.status == "approved", AccountLink.seen_at <= t)
        )
        sent_to = (
            select(PixAnalysis.destination_document.label("document"))
            .join(AccountLink, AccountLink.pix_analysis_id == PixAnalysis.id)
            .where(AccountLink.link_type == "pix", AccountLink.from_key == key, PixAnalysis.status == "approved", AccountLink.seen_at <= t)
        )

        return int(self.session.execute(select(func.count()).select_from(union(received_from, sent_to).subquery())).scalar())

    def _shares_device_with_marked(self, key: str, t: datetime, current_device_id: Optional[str]) -> bool:
        """A conta usou, em 30 dias, um aparelho que uma conta com E1 também usou (um salto, só E1 propaga)."""
        start = t - E2_WINDOW
        devices = {
            row[0]
            for row in self.session.query(AccountLink.to_key)
            .filter(
                AccountLink.link_type == "device",
                AccountLink.from_key == key,
                AccountLink.seen_at > start,
                AccountLink.seen_at <= t,
            )
            .all()
        }
        if current_device_id is not None:
            devices.add(f"device:{current_device_id}")
        if not devices:
            return False

        return (
            self.session.query(AccountLink.id)
            .join(PixAnalysis, PixAnalysis.id == AccountLink.pix_analysis_id)
            .filter(
                AccountLink.link_type == "device",
                AccountLink.to_key.in_(devices),
                AccountLink.from_key != key,
                AccountLink.seen_at > start,
                AccountLink.seen_at <= t,
                PixAnalysis.payer_dict_e1.is_(True),
            )
            .first()
            is not None
        )
