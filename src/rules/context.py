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
    payer_key: str
    payer_document: str
    source_opening_date: datetime
    device_id: str
    destination_key: str
    destination_document: str
    destination_opening_date: datetime


@dataclass(frozen=True)
class AccountHistory:
    """O que a conta pagadora já fez, lido do banco DEPOIS da trava.

    São os indicadores de R1 a R5, em valores prontos: a política nunca roda
    consulta. As janelas são `(t - janela, t]`, com `t` a `transaction_date`
    do pedido atual. Nenhum indicador inclui o Pix atual: os tetos o somam
    uma única vez; a média de R5 usa somente as aprovações anteriores.
    """

    # SUM do valor dos Pix `approved` da conta nas últimas 24 h (R1 e R2).
    approved_amount_24h: int
    # COUNT das análises da conta nos últimos 2 minutos, qualquer status (R3).
    attempts_2m: int
    # A primeira aprovação da conta neste aparelho, se houver (R4).
    first_device_approved_at: Optional[datetime]
    # Soma e quantidade de todos os Pix enviados e aprovados até t (R5).
    # Não é uma janela de 24 h: a razão entre os dois é a média histórica.
    approved_amount_total: int
    approved_count_total: int


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
    e1_since: Optional[datetime] = None
    e4_since: Optional[datetime] = None
    observed: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LocalEvidence:
    """As evidências E2, E3 e E5 de uma conta, calculadas do histórico local."""

    e2: bool = False
    e3: bool = False
    e5: bool = False


@dataclass(frozen=True)
class AccountFlows:
    """Os indicadores brutos do grafo para UMA conta, lidos do banco depois da trava.

    Nenhum inclui o Pix atual, e só Pix `approved` contam: "recebido" significa
    aprovado pelo motor, não liquidado. As regras transformam estes números nas
    evidências; o repository só os conta.
    """

    # O que a conta recebeu em 30 dias, e quanto disso veio de contas com E1 no momento do Pix.
    received_30d: int = 0
    received_30d_from_e1: int = 0
    # A conta usou, em 30 dias, um aparelho também usado por uma conta com E1.
    shares_device_with_e1: bool = False
    # Contas distintas com Pix aprovado em qualquer direção, na janela de 30 dias.
    counterparties: int = 0
    # Titulares distintos que enviaram na última hora, e quantos nunca tinham enviado antes dela.
    holders_1h: int = 0
    first_time_holders_1h: int = 0
    # O que a conta recebeu em 24 h, de quantos titulares.
    received_24h: int = 0
    holders_24h: int = 0
    # Para o repasse: o que a conta recebeu e o que enviou na última hora.
    received_1h: int = 0
    sent_1h: int = 0


@dataclass(frozen=True)
class MuleHistory:
    """O histórico de que o módulo de conta laranja precisa, lido do banco depois da trava."""

    # A primeira aprovação deste pagador para este titular de destino. Dela saem
    # o "destinatário conhecido" e a "relação anterior".
    first_approval_to_destination: Optional[datetime] = None
    payer_flows: AccountFlows = field(default_factory=AccountFlows)
    destination_flows: AccountFlows = field(default_factory=AccountFlows)


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
