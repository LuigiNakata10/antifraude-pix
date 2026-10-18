from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from connectors import DictConnector, DictQuery, DictResult
from constants import DICT_API_TIMEOUT, DICT_DESTINATION_CACHE_TTL_SECONDS, DICT_PAYER_CACHE_TTL_SECONDS
from controllers.base_controller import BaseController
from repositories import DictLookupRepository


@dataclass(frozen=True)
class DictObservation:
    """O que o motor soube do DICT sobre UMA conta, e como soube.

    `status` é `consultado` (resposta ao vivo), `cache` (resposta guardada,
    usada porque o DICT falhou) ou `indisponivel` (sem resposta e sem cache
    válido; `response` é vazio).
    """

    status: str
    response: Optional[dict]


class DictController(BaseController):
    """Decide de onde vem a resposta do DICT: ao vivo ou do cache.

    - O PAGADOR é lido do cache de 5 minutos, sem renovar fetched_at na leitura;
      é consultado no primeiro Pix ou na primeira análise após a expiração.
    - O DESTINO é sempre consultado AO VIVO, para uma marcação nova valer no
      Pix seguinte; o cache de 1 h só o socorre se o DICT falhar.
    - Quando as duas consultas são necessárias, rodam em paralelo, com um único
      limite de tempo (DICT_API_TIMEOUT): quem não respondeu a tempo é
      desconhecido, e desconhecido nunca vira decisão.

    Roda ANTES da trava da conta pagadora, para a trava nunca esperar a rede. A
    gravação no cache é uma transação curta própria, commitada aqui mesmo.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = DictLookupRepository(self.context)
        self.connector = DictConnector()

    def lookup(self, payer: DictQuery, destination: DictQuery) -> tuple:
        """Devolve (observação do pagador, observação do destino)."""
        now = datetime.now(timezone.utc)
        payer_cached = self.repository.get_latest_since(payer.key, now - timedelta(seconds=DICT_PAYER_CACHE_TTL_SECONDS))
        destination_cached = self.repository.get_latest_since(
            destination.key, now - timedelta(seconds=DICT_DESTINATION_CACHE_TTL_SECONDS)
        )
        # Materializa os JSONs antes do rollback, sem objetos ORM expirados durante HTTP.
        payer_cached = DictObservation("cache", payer_cached.response) if payer_cached is not None else None
        destination_cached = DictObservation("cache", destination_cached.response) if destination_cached is not None else None
        self.session.rollback()

        queries = {"destination": destination}
        if payer_cached is None:
            queries["payer"] = payer
        live = self._query_in_parallel(queries)

        payer_observation = self._observe(payer_cached, live.get("payer"), prefer_cache=True)
        destination_observation = self._observe(destination_cached, live.get("destination"), prefer_cache=False)

        for name, query in queries.items():
            result = live.get(name)
            if result is not None and result.available:
                self.repository.create(query.key, result.response)
        self.session.commit()

        return payer_observation, destination_observation

    def _query_in_parallel(self, queries: dict) -> dict:
        """Consulta o DICT para cada conta ao mesmo tempo e devolve só quem respondeu dentro do prazo."""
        executor = ThreadPoolExecutor(max_workers=len(queries))
        futures = {name: executor.submit(self.connector.get_statistics, query) for name, query in queries.items()}
        done, _ = wait(futures.values(), timeout=DICT_API_TIMEOUT)
        executor.shutdown(wait=False)

        return {name: future.result() for name, future in futures.items() if future in done and not future.exception()}

    @staticmethod
    def _observe(cached, live: Optional[DictResult], prefer_cache: bool) -> DictObservation:
        if prefer_cache and cached is not None:
            return DictObservation("cache", cached.response)
        if live is not None and live.available:
            return DictObservation("consultado", live.response)
        if cached is not None:
            return DictObservation("cache", cached.response)

        return DictObservation("indisponivel", None)
