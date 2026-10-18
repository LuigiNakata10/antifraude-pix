from concurrent.futures import ThreadPoolExecutor

from tests.utils.request_generator import RequestGenerator

# O pool de conexões da API tem 5 + 10: mais que isso de threads só espera.
THREADS = 8


def post_all(payloads: list) -> list:
    """Dispara todos os pedidos ao mesmo tempo e devolve (status HTTP, corpo) de cada um."""
    with ThreadPoolExecutor(max_workers=min(len(payloads), THREADS)) as pool:
        return list(pool.map(RequestGenerator.POST_pix_transaction, payloads))
