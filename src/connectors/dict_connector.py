from dataclasses import dataclass
from typing import Optional

from connectors.rest_connector import RestConnector
from constants import DICT_API_INTERNAL_TOKEN, DICT_API_TIMEOUT, DICT_API_URL


@dataclass(frozen=True)
class DictResult:
    """O que o DICT respondeu, ou o fato de que não respondeu.

    `available` é falso para timeout, erro de rede, 429 ou qualquer resposta
    que não seja o JSON esperado. Nesse caso `response` é vazio: indisponível
    vira "desconhecido" para as evidências E1 e E4, nunca uma decisão.
    """

    available: bool
    response: Optional[dict] = None


class DictConnector(RestConnector):
    """Fala com o DICT (simulado por um mock): estatísticas antifraude de uma conta.

    Só traduz a conversa HTTP num `DictResult`. O que a resposta significa
    (E1, E4, estado da conta) é regra, e mora em src/rules/.

    O prazo é de 200 ms (DICT_API_TIMEOUT): a decisão do Pix sai em poucos
    segundos, e esperar mais que isso por uma consulta de apoio custa mais do
    que decidir sem ela.
    """

    def __init__(self) -> None:
        super().__init__(
            class_name=__name__,
            base_url=DICT_API_URL,
            timeout=DICT_API_TIMEOUT,
            internal_token=DICT_API_INTERNAL_TOKEN,
        )

    def get_statistics(self, participant: str, branch: str, account_number: str, document_number: str) -> DictResult:
        """Consulta as estatísticas antifraude de uma conta e do seu titular.

        A chamada acontece FORA da transação do banco, para a trava da conta
        pagadora nunca ficar presa esperando a rede. Implementada na etapa do DICT.
        """
        raise NotImplementedError("a consulta ao DICT entra na etapa do mock")
