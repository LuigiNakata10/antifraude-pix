import random
from os import environ
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from tests.utils.payload_generator import PayloadGenerator
from tests.utils.random_generator import RandomGenerator
from tests.utils.request_generator import RequestGenerator


# O ISPB do banco que roda o motor: o mesmo valor padrao do compose. Toda conta
# pagadora pertence a ele, e um destino com este ISPB e uma conta nossa.
INSTITUTION_ISPB = environ.get("INSTITUTION_ISPB", "99999999")

# O instante "agora" de todos os cenários: o da transação do exemplo do desafio.
# Os testes não dependem do relógio da máquina; contam o tempo a partir daqui.
BASE = datetime(2026, 10, 17, 22, 15, 0, tzinfo=timezone(timedelta(hours=-3)))


def at(delta: timedelta = timedelta(0)) -> str:
    """O instante BASE + delta, em ISO 8601 com o fuso -03:00."""
    return (BASE + delta).isoformat()


class PixDestination:
    """Uma conta de destino, com o titular, para o mesmo destinatário voltar em vários Pix."""

    def __init__(self, age: timedelta = timedelta(days=365), document: str = None, participant: str = "60701190",
                 branch: str = "3675", account_number: str = None) -> None:
        self.participant = participant
        self.branch = branch
        self.account_number = account_number or str(random.randrange(10**8, 10**9))
        self.document = document or RandomGenerator.generate_cpf()
        self.opening_date = at(-age)

    @property
    def key(self) -> str:
        """A chave "ispb:agência:conta" que o motor usa no grafo e no cache do DICT."""
        return f"{self.participant}:{self.branch}:{self.account_number}"


class PixAccount:
    """Uma conta pagadora nova a cada teste, que conta a própria história pela API.

    O `age` é a idade da conta em relação ao instante BASE. Os Pix de cada
    conta precisam ser enviados em ordem cronológica: a API recusa um pedido
    anterior ao último já analisado da mesma conta.
    """

    def __init__(self, age: timedelta = timedelta(days=365), document: str = None, device_id: str = None) -> None:
        self.participant = INSTITUTION_ISPB
        self.branch = "0001"
        self.account_number = str(random.randrange(10**8, 10**9))
        self.document = document or RandomGenerator.generate_cpf()
        self.opening_date = at(-age)
        self.device_id = device_id or f"dvc-{uuid4().hex[:8]}"

    @property
    def key(self) -> str:
        return f"{self.participant}:{self.branch}:{self.account_number}"

    def as_destination(self) -> PixDestination:
        """Esta mesma conta vista como DESTINO de um Pix de outra conta (é uma conta nossa)."""
        destination = PixDestination(
            participant=self.participant,
            branch=self.branch,
            account_number=self.account_number,
            document=self.document,
        )
        destination.opening_date = self.opening_date

        return destination

    def payload(
        self,
        amount: int,
        when: timedelta = timedelta(0),
        device_id: str = None,
        destination: PixDestination = None,
        transaction_id: str = None,
    ) -> dict:
        if destination is None:
            destination = PixDestination()

        return PayloadGenerator.create_pix_payload(
            transaction_id=transaction_id,
            amount=amount,
            transaction_date=at(when),
            source_opening_date=self.opening_date,
            destination_opening_date=destination.opening_date,
            device_id=device_id or self.device_id,
            source_account_number=self.account_number,
            payer_document=self.document,
            destination_account_number=destination.account_number,
            destination_document=destination.document,
            destination_participant=destination.participant,
            destination_branch=destination.branch,
        )

    def pix(self, amount: int, when: timedelta = timedelta(0), **kwargs):
        """Envia um Pix e devolve (status HTTP, corpo)."""
        return RequestGenerator.POST_pix_transaction(self.payload(amount, when, **kwargs))

    def send(self, amount: int, when: timedelta, expected: str, **kwargs) -> dict:
        """Envia um Pix de histórico e confere que ele foi analisado como esperado."""
        status, response = self.pix(amount, when, **kwargs)
        assert status == 201, response
        assert response["status"] == expected, response
        return response

    def record(self, amount: int, when: timedelta = timedelta(0), **kwargs):
        """Envia um Pix e devolve (resposta, id do Pix), para conferir a auditoria depois."""
        transaction_id = f"pix-{uuid4().hex[:12]}"
        status, response = self.pix(amount, when, transaction_id=transaction_id, **kwargs)
        assert status == 201, response

        return response, transaction_id

    def fund(self, amount: int, when: timedelta, sender: "PixAccount" = None) -> "PixAccount":
        """Alguém (uma conta nova, por padrão) paga esta conta e é aprovado. Devolve o pagador."""
        sender = sender or PixAccount()
        sender.send(amount, when, "approved", destination=self.as_destination())

        return sender

    def make_device_known(self, device_id: str = None, hours_ago: int = 30) -> None:
        """Faz o aparelho da conta virar conhecido: primeira aprovação há `hours_ago` horas.

        Os 30 h padrão passam das 24 h de espera. Quem precisa de um Pix de
        histórico a 24 h do instante BASE pede mais (ex.: 50), para o aparelho
        já ser conhecido NAQUELE momento.
        """
        self.send(1000, timedelta(hours=-hours_ago), "approved", device_id=device_id)
