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
