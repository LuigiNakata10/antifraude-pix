from dataclasses import dataclass, field
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
class DictSignals:
    """O que o DICT disse de UMA conta, em sinais prontos, e como o motor soube.

    `status` é `consultado` (resposta ao vivo), `cache` (resposta guardada,
    usada quando o DICT falhou) ou `indisponivel`. `e1` e `e4` são `None`
    quando desconhecidos: desconhecido nunca conta como evidência.
    """

    status: str
    e1: Optional[bool]
    e4: Optional[bool]


@dataclass(frozen=True)
class LocalEvidence:
    """As evidências E2, E3 e E5 de uma conta, calculadas do histórico local."""

    e2: bool = False
    e3: bool = False
    e5: bool = False


@dataclass(frozen=True)
class MuleHistory:
    """O histórico de que o módulo de conta laranja precisa, lido do banco depois da trava.

    Nenhum valor inclui o Pix atual. Só Pix `approved` contam como "recebido" ou
    "enviado": "recebido" significa aprovado pelo motor, não liquidado.
    """

    # A `transaction_date` da primeira análise em que o motor viu o DESTINO
    # marcado (E1) ou com notificações abertas (E4). `None` se nunca viu: o
    # início da evidência é, então, o próprio Pix atual.
    destination_e1_since: Optional[datetime] = None
    destination_e4_since: Optional[datetime] = None
    # A primeira aprovação deste pagador para este titular de destino. Dela saem
    # o "destinatário conhecido" e a "relação anterior".
    first_approval_to_destination: Optional[datetime] = None
    payer_local: LocalEvidence = field(default_factory=LocalEvidence)
    destination_local: LocalEvidence = field(default_factory=LocalEvidence)


@dataclass(frozen=True)
class PixContext:
    """Tudo de que a política precisa para decidir, montado por uma única camada.

    As regras base e o módulo de conta laranja leem do mesmo contexto.
    """

    request: PixRequest
    history: AccountHistory
    payer_dict: DictSignals
    destination_dict: DictSignals
    mule: MuleHistory
