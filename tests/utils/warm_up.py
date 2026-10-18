import time

import requests

from tests.utils.dict_mock import MOCKSERVER_URL, STATISTICS_PATH


def warm_up_dict_mock(timeout_seconds: float = 60.0, fast_ms: float = 60.0, fast_in_a_row: int = 3) -> None:
    """Espera o DICT simulado atender e aquecer, antes de a primeira conta ser consultada.

    O Mockserver não tem healthcheck (a imagem nem tem shell), então o
    `docker compose up --wait` só garante que o contêiner SUBIU. As primeiras
    respostas depois do início são lentas (de 150 ms a vários segundos numa
    máquina fraca), e o motor só espera 200 ms pelo DICT: sem esta espera, os
    primeiros testes que dependem do mock veriam "DICT indisponível" e falhariam
    sem nenhum defeito no motor.

    Considera aquecido quando responde 200 em até `fast_ms` por `fast_in_a_row`
    vezes seguidas. Se o prazo acabar com o mock respondendo, mas devagar, segue
    em frente (a máquina é lenta, e o resto da suíte diz o que acontece); se ele
    nunca respondeu, para com uma mensagem clara.
    """
    deadline = time.monotonic() + timeout_seconds
    fast = 0
    answered = False
    last_error = None

    while time.monotonic() < deadline:
        started = time.perf_counter()
        try:
            response = requests.get(
                f"{MOCKSERVER_URL}{STATISTICS_PATH}",
                params={"participant": "0", "branch": "0", "account": "warm-up"},
                timeout=5,
            )
        except requests.RequestException as error:
            last_error = error
            fast = 0
            time.sleep(0.5)
            continue

        answered = True
        elapsed_ms = (time.perf_counter() - started) * 1000
        fast = fast + 1 if response.status_code == 200 and elapsed_ms <= fast_ms else 0
        if fast >= fast_in_a_row:
            return
        time.sleep(0.1)

    if not answered:
        raise RuntimeError(
            f"O DICT simulado (Mockserver) não respondeu em {timeout_seconds:.0f} s em {MOCKSERVER_URL}: {last_error}.\n"
            "Suba a stack com `docker compose up --build -d --wait` e confira `docker compose logs mockserver`."
        )
