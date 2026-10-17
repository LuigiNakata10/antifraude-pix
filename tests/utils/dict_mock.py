import itertools
from os import environ

import requests


MOCKSERVER_URL = f"http://localhost:{environ.get('MOCKSERVER_PORT', '1080')}"
STATISTICS_PATH = "/dict/v1/statistics"

# Cada expectation nova ganha uma prioridade MAIOR que a anterior: roteirizar a
# mesma conta duas vezes no mesmo teste (marcada, depois fora do ar) sempre vale
# a última. A expectation padrão do mock, que não marca ninguém, tem prioridade 0.
_priority = itertools.count(10)


def statistics(mule=0, scammer=0, reporters=0, open_reports=0, mule_m12=None) -> dict:
    """O corpo de resposta do DICT simulado, com os contadores pedidos (janela d90)."""
    return {
        "OwnerStatistics": {
            "FraudMarkers": {
                "MuleAccounts": {"d90": mule, "m12": mule if mule_m12 is None else mule_m12, "m60": mule},
                "ScammerAccounts": {"d90": scammer, "m12": scammer, "m60": scammer},
                "DistinctFraudReporters": {"d90": reporters, "m12": reporters, "m60": reporters},
            },
            "InfractionReports": {"OpenReports": open_reports, "OpenReportsDistinctReporters": open_reports},
        }
    }


def _account_matcher(account) -> dict:
    return {
        "method": "GET",
        "path": STATISTICS_PATH,
        "queryStringParameters": {
            "participant": [account.participant],
            "branch": [account.branch],
            "account": [account.account_number],
        },
    }


class DictMock:
    """Roteiriza o DICT simulado (um Mockserver) por conta, pela API REST dele.

    O motor não sabe que fala com um mock: o teste só diz o que o 'DICT'
    responde para uma conta específica (cada teste usa contas novas).
    """

    @staticmethod
    def respond(account, body=None, status: int = 200, delay_ms: int = None, raw_body: str = None) -> None:
        response = {"statusCode": status}
        if raw_body is not None:
            response["body"] = raw_body
        elif body is not None:
            response["body"] = body
            response["headers"] = {"Content-Type": ["application/json"]}
        if delay_ms is not None:
            response["delay"] = {"timeUnit": "MILLISECONDS", "value": delay_ms}

        result = requests.put(
            f"{MOCKSERVER_URL}/mockserver/expectation",
            json={"httpRequest": _account_matcher(account), "httpResponse": response, "priority": next(_priority)},
        )
        assert result.status_code == 201, result.text

    @staticmethod
    def mark(account, **counters) -> None:
        """O DICT passa a responder estes contadores para a conta (ex.: mule=1, open_reports=2)."""
        DictMock.respond(account, body=statistics(**counters))

    @staticmethod
    def unavailable(account) -> None:
        """O DICT demora 500 ms para esta conta: bem acima dos 200 ms que o motor espera."""
        DictMock.respond(account, body=statistics(), delay_ms=500)

    @staticmethod
    def too_many_requests(account) -> None:
        DictMock.respond(account, status=429)
