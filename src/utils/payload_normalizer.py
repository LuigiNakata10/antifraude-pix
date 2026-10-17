import copy
import re
from datetime import datetime, timezone


DATE_PATHS = (
    ("transaction_date",),
    ("source_account", "opening_date"),
    ("destination_account", "opening_date"),
)

DOCUMENT_PATHS = (
    ("source_account", "owner", "document_number"),
    ("destination_account", "owner", "document_number"),
)


def normalize_payload(payload: dict) -> dict:
    """O corpo de um Pix na forma em que dois pedidos equivalentes ficam iguais.

    Só o que NÃO muda o significado é normalizado: as três datas viram o mesmo
    instante em UTC, e os dois documentos ficam só com dígitos. Todo o resto
    é comparado exatamente como veio: zeros à esquerda de agência e conta,
    valor sem arredondar, canal, IP e geolocalização. A ordem das chaves não
    importa, porque a comparação é entre dicionários.

    Função pura: não toca em banco e não altera o dicionário recebido.
    """
    normalized = copy.deepcopy(payload)

    for path in DATE_PATHS:
        _replace(normalized, path, _to_utc)
    for path in DOCUMENT_PATHS:
        _replace(normalized, path, _only_digits)

    return normalized


def _replace(payload: dict, path: tuple, transform) -> None:
    *parents, last = path
    node = payload
    for parent in parents:
        node = node[parent]
    node[last] = transform(node[last])


def _to_utc(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(timezone.utc).isoformat()


def _only_digits(value: str) -> str:
    return re.sub(r"\D", "", value)
