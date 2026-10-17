import random
from uuid import uuid4

from tests.utils.random_generator import RandomGenerator


class PayloadGenerator:
    @staticmethod
    def create_pix_payload(
        transaction_id: str = None,
        amount: int = None,
        transaction_date: str = None,
        source_opening_date: str = None,
        destination_opening_date: str = None,
        device_id: str = None,
        with_geolocation: bool = True,
        source_account_number: str = None,
        payer_document: str = None,
        destination_account_number: str = None,
        destination_document: str = None,
    ) -> dict:
        """Um Pix válido, no formato do desafio, com qualquer campo trocado a pedido.

        Sem argumento nenhum, o que precisa ser único sai aleatório — o `id`
        do Pix, a conta e o documento de quem paga —, pra que dois testes
        nunca dividam o histórico da mesma conta. As datas são fixas (as do
        exemplo do desafio): o contrato não depende do relógio.
        """
        if transaction_id is None:
            transaction_id = f"pix-{uuid4().hex[:12]}"
        if amount is None:
            amount = 150000
        if transaction_date is None:
            transaction_date = "2026-10-17T22:15:00-03:00"
        if source_opening_date is None:
            source_opening_date = "2025-03-02T10:00:00-03:00"
        if destination_opening_date is None:
            destination_opening_date = "2026-10-10T09:00:00-03:00"
        if device_id is None:
            device_id = f"dvc-{uuid4().hex[:8]}"
        if source_account_number is None:
            source_account_number = str(random.randrange(10**6, 10**7))
        if payer_document is None:
            payer_document = RandomGenerator.generate_cpf()
        if destination_account_number is None:
            destination_account_number = str(random.randrange(10**4, 10**5))
        if destination_document is None:
            destination_document = RandomGenerator.generate_cpf()

        payload = {
            "id": transaction_id,
            "amount": amount,
            "transaction_date": transaction_date,
            "source_account": {
                "branch": "0001",
                "account_number": source_account_number,
                "opening_date": source_opening_date,
                "owner": {"document_number": payer_document},
            },
            "destination_account": {
                "participant": "60701190",
                "branch": "3675",
                "account_number": destination_account_number,
                "opening_date": destination_opening_date,
                "owner": {"document_number": destination_document},
            },
            "source": {
                "device_id": device_id,
                "channel": "app",
                "ip": "198.51.100.23",
            },
        }

        if with_geolocation:
            payload["source"]["geolocation"] = {"latitude": -23.56, "longitude": -46.65}

        return payload
