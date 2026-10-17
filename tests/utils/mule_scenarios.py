from datetime import timedelta

from tests.utils.pix_account import PixAccount

REAL = 100  # R$ 1,00 em centavos
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def hub_receiving_from_new_senders(
    payer: PixAccount, senders: int = 6, first_time: int = 4, each: int = 1000 * REAL, before: timedelta = timedelta(0)
) -> list:
    """A conta recebe de vários titulares na última hora; só alguns são de primeira vez.

    Os que NÃO são de primeira vez já tinham um Pix aprovado para a conta 3 horas
    antes (fora da janela de 1 hora). `before` desloca tudo para trás no tempo.
    Devolve os pagadores, na ordem em que enviaram.
    """
    result = []
    for index in range(senders):
        sender = PixAccount()
        if index >= first_time:
            payer.fund(100 * REAL, before - 3 * HOUR, sender=sender)
        payer.fund(each, before - (50 - 5 * index) * MINUTE, sender=sender)
        result.append(sender)

    return result
