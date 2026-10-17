from abc import ABCMeta
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from database import get_context
from errors import LockTimeout
from utils.logger import get_logger


LOCK_NOT_AVAILABLE = "55P03"
UNIQUE_VIOLATION = "23505"


class BaseController(metaclass=ABCMeta):
    """O que todo controller tem em comum: a conexão com o banco e o log.

    Nada chega por parâmetro: o controller pega o CONTEXTO da requisição
    em que está rodando. Quem preparou esse contexto foi o middleware.

    Guardar o `self.context`, e não só a sessão, é o que permite o
    repository receber `context` em vez de `db`: o contexto é a coisa que
    viaja entre as camadas, e a sessão é só o que ele carrega hoje.

    É aqui que a sessão nasce, no `get_or_create_session` — construir um
    controller é a mesma coisa que dizer "eu uso banco".
    """

    def __init__(self, class_name: str) -> None:
        self.context = get_context()
        self.session = self.context.get_or_create_session()
        self.logger = get_logger(class_name)

    def start_write_transaction(self) -> None:
        """Limita a 5 s a espera por uma trava, só nesta transação (SET LOCAL).

        Estourou, o Postgres levanta 55P03 e o `lock_timeout_guard` o transforma
        em 503. Sem prazo, um pedido preso seguraria a conta para sempre.
        """
        self.session.execute(text("SET LOCAL lock_timeout = '5s'"))

    @contextmanager
    def lock_timeout_guard(self):
        """Espera de trava acima de 5 s: desfaz tudo e responde 503 QIT003005."""
        try:
            yield
        except OperationalError as error:
            if getattr(error.orig, "pgcode", None) == LOCK_NOT_AVAILABLE:
                self.session.rollback()
                raise LockTimeout() from None
            raise

    @staticmethod
    def is_unique_violation(error: IntegrityError) -> bool:
        """O Postgres recusou por UNIQUE (23505): outro pedido chegou primeiro."""
        return getattr(error.orig, "pgcode", None) == UNIQUE_VIOLATION
