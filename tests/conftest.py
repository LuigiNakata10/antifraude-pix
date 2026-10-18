from pathlib import Path
from os import path, environ

import pytest

root = Path(__file__).resolve().parents[1]

if not environ.get("APP_ENV") or environ.get("APP_ENV") == "local":
    from dotenv import load_dotenv

    load_dotenv(path.join(str(root), ".env"))

    if environ.get("SERVER_LOCALHOST") is None:
        environ["SERVER_LOCALHOST"] = "0.0.0.0"


@pytest.fixture(scope="session", autouse=True)
def warm_up_dict_mock():
    """Antes da primeira conta, o DICT simulado precisa estar de pé e aquecido.

    O motor espera só 200 ms pelo DICT; as primeiras respostas de um Mockserver
    recém-iniciado demoram mais que isso. Veja `tests/utils/warm_up.py`.
    """
    from tests.utils.warm_up import warm_up_dict_mock as wait_for_mock

    try:
        wait_for_mock()
    except RuntimeError as error:
        pytest.exit(str(error), returncode=2)
