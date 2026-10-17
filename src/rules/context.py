from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class PixRequest:
    """O pedido já normalizado: o que o motor sabe do Pix, e nada do que veio cru.

    Datas com fuso (a referência das regras é `transaction_date`), documentos
    só com dígitos, valor em centavos inteiros.
    """

    transaction_id: str
    amount: int
    transaction_date: datetime
    payer_branch: str
    payer_account_number: str
    payer_document: str
    source_opening_date: datetime
    device_id: str
    destination_key: str
    destination_document: str
    destination_opening_date: datetime


@dataclass(frozen=True)
class AccountHistory:
    """O que a conta pagadora já fez, lido do banco DEPOIS da trava.

    São os indicadores de R1 a R4, em valores prontos: a política nunca roda
    consulta. As janelas são `(t - janela, t]`, com `t` a `transaction_date`
    do pedido atual, e nenhum indicador inclui o Pix atual: quem o soma, uma
    única vez, é a regra.
    """

    # SUM do valor dos Pix `approved` da conta nas últimas 24 h (R1 e R2).
    approved_amount_24h: int
    # COUNT das análises da conta nos últimos 2 minutos, qualquer status (R3).
    attempts_2m: int
    # A primeira aprovação da conta neste aparelho, se houver (R4).
    first_device_approved_at: Optional[datetime]


@dataclass(frozen=True)
class PixContext:
    """Tudo de que a política precisa para decidir, montado por uma única camada.

    As regras base e o módulo de conta laranja leem do mesmo contexto. Os
    indicadores do módulo (estado da conta, evidências e ato) entram aqui na
    etapa dele; `dict_available` já diz se E1 e E4 são conhecidas ou
    desconhecidas, e desconhecido nunca conta como evidência.
    """

    request: PixRequest
    history: AccountHistory
    dict_available: bool
