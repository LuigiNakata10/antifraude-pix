from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import PixTransactionController
from utils.schema_handler import SchemaHandler


class PixTransactionResource:
    """A porta de entrada HTTP da análise de Pix.

    Faz três coisas, nesta ordem: confere o corpo (o decorator do schema),
    chama o controller e devolve o que ele respondeu, com o status certo.
    Nenhuma regra e nenhuma linha de SQL moram aqui. O resource não guarda
    nada em `self`: ele é compartilhado por todas as requisições.
    """

    @SchemaHandler.validate("post_pix_transaction.json", integer_fields=("amount",))
    def on_post(self, payload: dict) -> JSONResponse:
        analysis, is_new = PixTransactionController().create(payload)
        status_code = http_status.HTTP_201_CREATED if is_new else http_status.HTTP_200_OK

        return JSONResponse(content=jsonable_encoder(analysis), status_code=status_code)

    def on_get_by_id(self, transaction_id: str) -> JSONResponse:
        analysis = PixTransactionController().get_by_transaction_id(transaction_id)

        return JSONResponse(content=jsonable_encoder(analysis), status_code=http_status.HTTP_200_OK)
