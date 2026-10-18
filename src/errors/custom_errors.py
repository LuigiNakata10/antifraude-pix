from errors import QIException


class SameAccountTransaction(QIException):
    """A origem e o destino identificam a mesma conta, não duas contas do mesmo titular."""

    code = "QIT003008"

    def __init__(self) -> None:
        super().__init__("Same Account Transaction", self.code, 422,
                         "The source and destination must be different accounts.",
                         "A conta de origem e a conta de destino devem ser diferentes.")


class InconsistentAccountIdentity(QIException):
    code = "QIT003007"

    def __init__(self, side) -> None:
        super().__init__("Inconsistent Account", self.code, 422,
                         f"The {side} account owner or opening date conflicts with known history.",
                         f"Titular ou abertura da conta ({side}) diverge do histórico observado.")


class InvalidTransactionDate(QIException):
    """A data não existe no calendário ou não comporta a conversão UTC/janelas do motor.

    422, e não 400: a API leu e entendeu o pedido; é o valor que não pode existir.
    O schema sabe contar dígitos, não dias.
    """

    code = "QIT003001"

    def __init__(self, field, value) -> None:
        title = "Invalid Date"
        http_status = 422
        description = f"The value {value} in {field} is not a supported date and time."
        translation = f"O valor {value} em {field} não é uma data e hora suportada pelo motor."
        super().__init__(title, self.code, http_status, description, translation)


class AccountOpenedAfterTransaction(QIException):
    """Uma conta não pode ter sido aberta depois do Pix que fez ou recebeu.

    Abertura exatamente igual à data do Pix é coerente: o erro é só a abertura
    estritamente posterior. Aceitar o contrário deixaria o pedido manipular a
    idade da conta, que é o que a regra de conta nova (R1) consulta.
    """

    code = "QIT003002"

    def __init__(self, account_side) -> None:
        title = "Account Opened After Transaction"
        http_status = 422
        description = f"The {account_side} account opening date is after the transaction date."
        translation = f"A data de abertura da conta ({account_side}) é posterior à data da transação."
        super().__init__(title, self.code, http_status, description, translation)


class NotFoundPixAnalysis(QIException):
    code = "QIT003003"

    def __init__(self, transaction_id) -> None:
        title = "Pix Analysis not Found"
        http_status = 404
        description = f"No analysis was found for the Pix transaction {transaction_id}."
        translation = f"Nenhuma análise foi encontrada para a transação Pix {transaction_id}."
        super().__init__(title, self.code, http_status, description, translation)


class TransactionIdConflict(QIException):
    """O mesmo `id` já foi analisado, mas com conteúdo diferente.

    409: conflito com o que já está no banco. A análise original nunca é
    sobrescrita, e o pedido novo não altera histórico nem contadores.
    """

    code = "QIT003004"

    def __init__(self, transaction_id) -> None:
        title = "Transaction Id Conflict"
        http_status = 409
        description = f"The Pix transaction {transaction_id} was already analyzed with different data."
        translation = f"A transação Pix {transaction_id} já foi analisada com dados diferentes."
        super().__init__(title, self.code, http_status, description, translation)


class LockTimeout(QIException):
    """A conta pagadora ficou travada por outro pedido além do prazo (5 s).

    503, com Retry-After: nada foi gravado e repetir o mesmo pedido é seguro.
    Falha técnica nunca vira decisão: o motor não aprova, rejeita nem pede
    2FA só porque não conseguiu a vez na conta.
    """

    code = "QIT003005"
    headers = {"Retry-After": "1"}

    def __init__(self) -> None:
        title = "Account Busy"
        http_status = 503
        description = "The payer account is being processed by another request. Retry shortly."
        translation = "A conta pagadora está sendo processada por outra requisição. Tente novamente em instantes."
        super().__init__(title, self.code, http_status, description, translation)


class OutOfOrderTransaction(QIException):
    """O Pix tem data anterior à do último já analisado para a mesma conta.

    422: a API entendeu o pedido, mas aceitá-lo obrigaria a reavaliar decisões
    já tomadas (um Pix anterior mudaria os acumulados dos seguintes). Recusado,
    não grava nada, não conta em frequência e não cria familiaridade.
    """

    code = "QIT003006"

    def __init__(self, transaction_date, last_transaction_date) -> None:
        title = "Out of Order Transaction"
        http_status = 422
        description = (
            f"The transaction date {transaction_date} is earlier than the last analyzed "
            f"transaction of this account ({last_transaction_date})."
        )
        translation = (
            f"A data da transação ({transaction_date}) é anterior à da última transação analisada "
            f"desta conta ({last_transaction_date})."
        )
        super().__init__(title, self.code, http_status, description, translation)
