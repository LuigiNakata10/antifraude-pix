from sqlalchemy.dialects.postgresql import insert

from database import Context
from models import PayerAccount


class PayerAccountRepository:
    """A camada que fala com a tabela `payer_account`. Só aqui existe query dela."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_or_create_locked(self, branch: str, account_number: str) -> PayerAccount:
        """Devolve a conta pagadora TRAVADA até o fim da transação, criando-a se não existir.

        A criação é segura sob concorrência: `INSERT ... ON CONFLICT DO NOTHING`
        e só então o `SELECT ... FOR NO KEY UPDATE` (`with_for_update(key_share=True)`).

        É FOR NO KEY UPDATE, e não FOR UPDATE: o INSERT de `pix_analysis` tem
        chave estrangeira para esta linha e pede FOR KEY SHARE, que conflita com
        FOR UPDATE e causa deadlock entre pedidos concorrentes mesmo com a ordem
        certa. Quem chega depois espera até o commit, e só então lê o histórico.
        """
        self.session.execute(
            insert(PayerAccount)
            .values(branch=branch, account_number=account_number)
            .on_conflict_do_nothing(index_elements=["branch", "account_number"])
        )

        return (
            self.session.query(PayerAccount)
            .filter(PayerAccount.branch == branch, PayerAccount.account_number == account_number)
            .with_for_update(key_share=True)
            .one()
        )
