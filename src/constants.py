import os


SERVICE_ROOT = os.path.abspath(os.path.dirname(__file__))

# Onde moram os arquivos de schema — os .json que descrevem o formato
# que cada requisicao precisa ter. Quem le essa pasta e o
# src/utils/schema_handler.py.
SCHEMA_PATH = os.path.join(SERVICE_ROOT, "schemas")

APP_ENV = os.environ.get("APP_ENV", "local")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "antifraude-pix-api")

DATABASE_URL = os.environ.get("DATABASE_URL")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN")

# O DICT: o serviço de fora que este projeto consulta (veja
# src/connectors/dict_connector.py). Na sua máquina o endereço aponta pro
# mock server do compose; em produção apontaria pro DICT de verdade. O
# código não sabe a diferença.
DICT_API_URL = os.environ.get("DICT_API_URL", "http://mockserver:1080")
DICT_API_INTERNAL_TOKEN = os.environ.get("DICT_API_INTERNAL_TOKEN", "default_token")

# Quantos segundos esperar pelo DICT antes de desistir: 200 ms. A decisão
# do Pix sai em poucos segundos, e esperar mais que isso por uma consulta
# de apoio custa mais do que decidir sem ela (E1 e E4 ficam desconhecidas).
DICT_API_TIMEOUT = float(os.environ.get("DICT_API_TIMEOUT", "0.2"))

# O ISPB do banco que roda este motor (fictício por padrão). O payload só traz o
# ISPB do destino, então a conta pagadora é sempre desta instituição, e um
# destino com este ISPB é uma conta nossa. Entra na chave "ispb:agência:conta"
# do grafo e das consultas ao DICT.
INSTITUTION_ISPB = os.environ.get("INSTITUTION_ISPB", "99999999")

# Quanto tempo uma resposta do DICT guardada em `dict_lookup` vale. É frescor
# TÉCNICO (relógio do servidor), não regra de negócio. O pagador é cliente do
# banco e muda pouco: 24 h. O destino é consultado ao vivo a cada Pix e o cache
# só serve de reserva se o DICT falhar: 1 h.
DICT_PAYER_CACHE_TTL_SECONDS = 24 * 3600
DICT_DESTINATION_CACHE_TTL_SECONDS = 3600

# Rotas públicas: não exigem o header INTERNAL-TOKEN. São as duas que
# precisam responder pra quem ainda não tem token nenhum: a raiz, que
# diz quem é este serviço, e o health check, que o Docker consulta pra
# saber se a API já está de pé.
BYPASS_ENDPOINTS = [
    "/",
    "/health_check",
]

REQUIRED_VARIABLES = ["DATABASE_URL", "INTERNAL_TOKEN"]


def check_variables():
    missing = []
    for name in REQUIRED_VARIABLES:
        if not globals().get(name):
            missing.append(name)

    if missing:
        raise EnvironmentError(
            f"Faltam variáveis de ambiente: {', '.join(missing)}. "
            "Rodando com 'docker compose up' elas já vêm preenchidas. "
            "Fora do Docker, copie o .env.example para .env."
        )
