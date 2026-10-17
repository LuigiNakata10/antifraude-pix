import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from tests.utils.payload_generator import PayloadGenerator
from tests.utils.random_generator import RandomGenerator
from tests.utils.request_generator import RequestGenerator


# O instante "agora" de todos os cenários: o da transação do exemplo do desafio.
# Os testes não dependem do relógio da máquina; contam o tempo a partir daqui.
BASE = datetime(2026, 10, 17, 22, 15, 0, tzinfo=timezone(timedelta(hours=-3)))


def at(delta: timedelta = timedelta(0)) -> str:
    """O instante BASE + delta, em ISO 8601 com o fuso -03:00."""
    return (BASE + delta).isoformat()


class PixDestination:
    """Uma conta de destino, com o titular, para o mesmo destinatário voltar em vários Pix."""

    def __init__(self, age: timedelta = timedelta(days=365)) -> None:
        self.account_number = str(random.randrange(10**4, 10**5))
        self.document = RandomGenerator.generate_cpf()
        self.opening_date = at(-age)


class PixAccount:
    """Uma conta pagadora nova a cada teste, que conta a própria história pela API.

    O `age` é a idade da conta em relação ao instante BASE. Os Pix de cada
    conta precisam ser enviados em ordem cronológica: a API recusa um pedido
    anterior ao último já analisado da mesma conta.
    """

    def __init__(self, age: timedelta = timedelta(days=365)) -> None:
        self.account_number = str(random.randrange(10**6, 10**7))
        self.document = RandomGenerator.generate_cpf()
        self.opening_date = at(-age)
        self.device_id = f"dvc-{uuid4().hex[:8]}"

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

    def make_device_known(self, device_id: str = None, hours_ago: int = 30) -> None:
        """Faz o aparelho da conta virar conhecido: primeira aprovação há `hours_ago` horas.

        Os 30 h padrão passam das 24 h de espera. Quem precisa de um Pix de
        histórico a 24 h do instante BASE pede mais (ex.: 50), para o aparelho
        já ser conhecido NAQUELE momento.
        """
        self.send(1000, timedelta(hours=-hours_ago), "approved", device_id=device_id)
