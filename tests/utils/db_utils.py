from os import environ
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError


RESET_QUERIES = [
    "DROP SCHEMA public CASCADE;",
    "CREATE SCHEMA public;",
    "GRANT ALL ON SCHEMA public TO CURRENT_USER;",
    "GRANT ALL ON SCHEMA public TO public;",
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = PROJECT_ROOT / "database" / "database.sql"

DEFAULT_DATABASE_URL = "postgresql+psycopg2://bootcamp:bootcamp@localhost:5432/bootcamp"

DATABASE_OFFLINE = (
    "Não consegui falar com o banco em {host}:{port}.\n"
    "Ele precisa estar de pé pros testes rodarem. Suba com:  docker compose up\n"
    "Se ele já está de pé, confira a porta na DATABASE_URL do seu .env."
)


class DbUtils:
    """Apaga o banco inteiro e o recria do zero — quando alguém chama.

    Não existe limpeza automática neste projeto. O `rollback()` roda no
    teste que o chamar, na linha em que for chamado, e em mais lugar
    nenhum. Todos os testes dividem o mesmo banco, e cada um enxerga o
    que os anteriores deixaram pra trás.

    O nome engana um pouco: isto não desfaz uma transação. Ele derruba
    o schema `public` com tudo que estiver dentro e roda o
    `database/database.sql` de novo — tabelas vazias e os quatro status
    do INSERT de volta.

    Quando o seu teste precisa chamar: sempre que alguma asserção
    depender de QUANTAS linhas existem no banco — contar, listar,
    paginar, filtrar. Nesses casos `DbUtils.rollback()` é a primeira
    linha do teste, antes de criar qualquer coisa (o exemplo está em
    `tests/integration/pix_transaction/`). Um teste que só olha
    as entidades que ele mesmo criou, pela chave que recebeu de volta,
    não precisa de limpeza nenhuma — e fica mais rápido sem ela.

    A limpeza acontece pela mesma conexão que a aplicação usa (a
    DATABASE_URL), e não por um programa externo: quem tem Docker
    rodando já tem tudo que precisa.
    """

    @staticmethod
    def database_url() -> str:
        return environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

    @staticmethod
    def rollback() -> None:
        engine = create_engine(DbUtils.database_url(), isolation_level="AUTOCOMMIT")

        try:
            with engine.connect() as connection:
                for query in RESET_QUERIES:
                    connection.exec_driver_sql(query)

                connection.exec_driver_sql(SCHEMA_FILE.read_text())
        except OperationalError:
            message = DATABASE_OFFLINE.format(host=engine.url.host, port=engine.url.port)
            raise RuntimeError(message) from None
        finally:
            engine.dispose()

    @staticmethod
    def analysis_row(transaction_id: str) -> dict:
        """A linha de auditoria de um Pix, só leitura: as colunas do DICT e o `analysis_details`.

        Exceção consciente ao black box: o que o motor registra para auditoria
        (E1 e E4 de cada conta, `dict_status`, estado, evidências e ato) nunca
        volta na resposta, então só se confere olhando o banco. Os testes de
        decisão continuam provando a decisão pela API.
        """
        engine = create_engine(DbUtils.database_url())
        try:
            with engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT payer_dict_e1, payer_dict_e4, destination_dict_e1, destination_dict_e4, analysis_details "
                        "FROM pix_analysis WHERE transaction_id = :transaction_id"
                    ),
                    {"transaction_id": transaction_id},
                ).mappings().one()
        finally:
            engine.dispose()

        return dict(row)

    @staticmethod
    def dict_lookup_count(account_key: str) -> int:
        """Quantas respostas do DICT o motor guardou para a conta, só leitura.

        Cada consulta AO VIVO que respondeu vira uma linha em `dict_lookup`; uma
        leitura do cache não cria nenhuma. Por isso a contagem é o número de
        chamadas ao DICT que deram certo, sem depender do log do Mockserver (que
        fica lento à medida que cresce).
        """
        engine = create_engine(DbUtils.database_url())
        try:
            with engine.connect() as connection:
                return connection.execute(
                    text("SELECT COUNT(*) FROM dict_lookup WHERE account_key = :key"), {"key": account_key}
                ).scalar()
        finally:
            engine.dispose()
