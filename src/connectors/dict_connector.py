from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

import requests

from connectors.rest_connector import RestConnector
from constants import DICT_API_INTERNAL_TOKEN, DICT_API_TIMEOUT, DICT_API_URL


# Os contadores que o motor lê da resposta. Faltou um deles, ou não é inteiro: a
# resposta não é a esperada e é tratada como se o DICT não tivesse respondido.
REQUIRED_COUNTERS = (
    ("OwnerStatistics", "FraudMarkers", "MuleAccounts", "d90"),
    ("OwnerStatistics", "FraudMarkers", "ScammerAccounts", "d90"),
    ("OwnerStatistics", "FraudMarkers", "DistinctFraudReporters", "d90"),
    ("OwnerStatistics", "InfractionReports", "OpenReports"),
)


@dataclass(frozen=True)
class DictResult:
    """O que o DICT respondeu, ou o fato de que não respondeu.

    `available` é falso para timeout, erro de rede, 429, qualquer status que
    não seja 200 e qualquer corpo que não seja o esperado. Nesse caso `response`
    é vazio: indisponível vira "desconhecido" para as evidências E1 e E4, nunca
    uma decisão.
    """

    available: bool
    response: Optional[dict] = None


@dataclass(frozen=True)
class DictQuery:
    """A conta que se quer consultar, como o DICT a identifica."""

    participant: str
    branch: str
    account_number: str
    document_number: str

    @property
    def key(self) -> str:
        """A chave "ispb:agência:conta" da conta, a mesma do grafo e do cache."""
        return f"{self.participant}:{self.branch}:{self.account_number}"


class DictConnector(RestConnector):
    """Fala com o DICT (simulado por um mock): estatísticas antifraude de uma conta.

    Só traduz a conversa HTTP num `DictResult`. O que a resposta significa
    (E1, E4, estado da conta) é regra, e mora em src/rules/.

    O mock segue, de forma simplificada, a estrutura da seção Antifraude da API
    pública do DICT. O prazo é de 200 ms (DICT_API_TIMEOUT): a decisão do Pix
    sai em poucos segundos, e esperar mais que isso por uma consulta de apoio
    custa mais do que decidir sem ela.
    """

    def __init__(self) -> None:
        super().__init__(
            class_name=__name__,
            base_url=DICT_API_URL,
            timeout=DICT_API_TIMEOUT,
            internal_token=DICT_API_INTERNAL_TOKEN,
        )

    def get_statistics(self, query: DictQuery) -> DictResult:
        """Consulta as estatísticas antifraude de uma conta e do seu titular.

        A chamada acontece FORA da transação do banco, para a trava da conta
        pagadora nunca ficar presa esperando a rede.
        """
        endpoint = "/dict/v1/statistics?" + urlencode(
            {
                "participant": query.participant,
                "branch": query.branch,
                "account": query.account_number,
                "document": query.document_number,
            }
        )

        try:
            response = self.send(endpoint=endpoint, method="GET")
        except requests.RequestException as error:
            self.logger.warning(f"DICT indisponivel ({type(error).__name__})")
            return DictResult(available=False)

        if response.status != 200 or not _has_expected_shape(response.json):
            self.logger.warning(f"DICT respondeu {response.status} fora do formato esperado")
            return DictResult(available=False)

        return DictResult(available=True, response=response.json)


def _has_expected_shape(body) -> bool:
    for path in REQUIRED_COUNTERS:
        node = body
        for name in path:
            if not isinstance(node, dict) or name not in node:
                return False
            node = node[name]
        if isinstance(node, bool) or not isinstance(node, int) or node < 0:
            return False

    since = body.get("EvidenceSince", {})
    if not isinstance(since, dict):
        return False
    try:
        for name in ("E1", "E4"):
            if since.get(name) is not None and datetime.fromisoformat(since[name].replace("Z", "+00:00")).tzinfo is None:
                return False
    except (ValueError, AttributeError, TypeError):
        return False

    return True
