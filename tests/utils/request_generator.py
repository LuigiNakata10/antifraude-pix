from os import environ

from tests.utils.requisition import BaseConnectorResponse, ClientRequisition


INTERNAL_TOKEN = environ.get("INTERNAL_TOKEN", "default_token")


class RequestGenerator:
    """Uma função por rota da API: o único lugar dos testes que sabe os endereços.

    Cada função devolve (status, corpo). O token vai por padrão; um teste
    que quer provar o 403 pede `with_token=False`.
    """

    @staticmethod
    def POST_pix_transaction(payload: dict, with_token: bool = True) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            "/pix/transaction",
            payload=payload,
            headers=RequestGenerator._headers(with_token),
        )

        return response.response_status, response.response_json

    @staticmethod
    def GET_pix_transaction(transaction_id: str, with_token: bool = True) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/pix/transaction/{transaction_id}",
            headers=RequestGenerator._headers(with_token),
        )

        return response.response_status, response.response_json

    @staticmethod
    def _headers(with_token: bool) -> dict:
        if with_token:
            return {"INTERNAL-TOKEN": INTERNAL_TOKEN}

        return {}
