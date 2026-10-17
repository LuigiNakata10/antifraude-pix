from datetime import datetime
from typing import Optional

from database import Context
from models import DictLookup


class DictLookupRepository:
    """A camada que fala com a tabela `dict_lookup`, o cache append-only do DICT.

    Cada consulta que RESPONDEU é uma linha nova; nada é atualizado. Quem lê usa
    a mais recente dentro da validade. Consulta que falhou nunca entra aqui.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_latest_since(self, account_key: str, cutoff: datetime) -> Optional[DictLookup]:
        """A resposta mais recente da conta guardada depois de `cutoff`, se houver."""
        return (
            self.session.query(DictLookup)
            .filter(DictLookup.account_key == account_key, DictLookup.fetched_at > cutoff)
            .order_by(DictLookup.fetched_at.desc(), DictLookup.id.desc())
            .first()
        )

    def create(self, account_key: str, response: dict) -> DictLookup:
        lookup = DictLookup()
        lookup.account_key = account_key
        lookup.response = response
        self.session.add(lookup)

        return lookup
