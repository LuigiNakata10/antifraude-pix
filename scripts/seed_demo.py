"""Monta a demo da apresentação pela API e pelo mock do DICT, e imprime cada decisão.

Cada passo cria contas novas, então pode rodar quantas vezes quiser contra a
mesma API de pé (`docker compose up -d`). Sai com código 1 se alguma decisão
for diferente da esperada. Guarda os papéis das contas em
`output/demo/accounts.json`, que o `graph_demo.py` lê para desenhar o grafo.

    python scripts/seed_demo.py
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from tests.utils import DictMock, PixAccount, PixDestination, RandomGenerator  # noqa: E402
from tests.utils.dict_mock import statistics  # noqa: E402
from tests.utils.pix_account import at  # noqa: E402
from tests.utils.warm_up import warm_up_dict_mock  # noqa: E402
from tests.utils.mule_scenarios import hub_receiving_from_new_senders  # noqa: E402

REAL = 100
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)

ACCOUNTS = {}
RESULTS = []


def register(party, label: str, role: str):
    """Guarda a conta para o desenho do grafo: o rótulo e o papel (marcada, suspeita, comum...)."""
    ACCOUNTS[party.key] = {"label": label, "role": role}

    return party


def company() -> PixDestination:
    return PixDestination(age=400 * DAY, document=RandomGenerator.generate_cnpj())


def show(step: str, text: str, response: dict, expected_status: str, expected_code: str, note: str = "") -> None:
    reason = response["metadata"]["reason"]
    ok = response["status"] == expected_status and reason["code"] == expected_code
    RESULTS.append(ok)
    print(f"  [{'ok' if ok else 'ERRO'}] {step}  {text}")
    print(f"        -> {response['status']} ({reason['code']})")
    if note:
        print(f"        {note}")
    if not ok:
        print(f"        ESPERADO: {expected_status} ({expected_code})")


def title(text: str) -> None:
    print(f"\n{text}")


def main() -> int:
    print("Demo do motor antifraude Pix: primeiro a conta, depois o ato.")
    try:
        # O Mockserver recém-iniciado responde devagar: sem isto, o primeiro passo
        # da demo ao vivo pode ver "DICT indisponível" e errar.
        warm_up_dict_mock()
    except RuntimeError as error:
        print(error)
        return 1

    # ------------------------------------------------------------------ 1
    title("1. Uma conta marcada no DICT: a vítima nova é barrada, a mãe de sempre não")
    son = register(PixDestination(), "Filho (marcado no DICT)", "marked")
    mother = register(PixAccount(), "Mãe", "regular")
    mother.send(100 * REAL, -10 * DAY, "approved", destination=son)
    DictMock.mark(son, mule=1, e1_since=at(-DAY))
    print("  O DICT passa a marcar a conta do filho. A mãe já mandava a mesada antes disso.")
    victim = register(PixAccount(), "Vítima nova", "victim")
    _, response = victim.pix(500 * REAL, destination=son)
    show("1a", "Vítima nova paga R$ 500 à conta marcada", response, "rejected", "MULE_DESTINATION")
    _, response = mother.pix(100 * REAL, destination=son)
    show("1b", "A mãe manda a mesada de sempre (relação anterior)", response, "approved", "POLICY_PASSED")

    # ------------------------------------------------------------------ 2
    title("2. A conta laranja paga a luz, mas não repassa o dinheiro do golpe")
    laranja = register(PixAccount(device_id="dvc-demo-aparelho-compartilhado"), "L1 (laranja, marcada)", "marked")
    golpe_victim = register(PixAccount(), "Vítima do golpe", "victim")
    DictMock.unavailable(laranja)
    golpe_victim.make_device_known()
    golpe_victim.send(5000 * REAL, -30 * MINUTE, "approved", destination=laranja.as_destination())
    DictMock.mark(laranja, mule=1)
    print("  O dinheiro do golpe entrou na conta de L1 quando o DICT estava fora do ar; agora L1 está marcada.")
    utility = register(company(), "Concessionária de luz", "company")
    response, _ = laranja.record(180 * REAL, destination=utility)
    show("2a", "L1 paga R$ 180 de luz (gasto típico)", response, "approved", "POLICY_PASSED")
    _, response = laranja.pix(4000 * REAL, destination=register(PixDestination(), "Recebe o repasse", "regular"))
    show("2b", "L1 tenta repassar R$ 4.000 do que acabou de receber", response, "rejected", "MULE_PAYER")

    # ------------------------------------------------------------------ 3
    title("3. L2 divide o aparelho com L1 e recebe de vários titulares novos: também é barrada")
    l2 = register(PixAccount(age=12 * DAY, device_id="dvc-demo-aparelho-compartilhado"), "L2 (conta nova)", "suspect")
    l2.send(100, -2 * HOUR, "approved", destination=company())
    for index, sender in enumerate(hub_receiving_from_new_senders(l2, senders=6, first_time=6, each=900 * REAL)):
        register(sender, f"Vítima nova {index + 1}", "victim")
    _, response = l2.pix(4000 * REAL, destination=register(PixDestination(), "Recebe o repasse de L2", "regular"))
    show("3 ", "L2 tenta repassar R$ 4.000 (aparelho de L1 + 6 titulares novos na hora)", response, "rejected", "SUSPECTED_MULE_FORWARDING")

    # ------------------------------------------------------------------ 4
    title("4. Receber de boa-fé não trava ninguém: a padaria antiga continua pagando o fornecedor")
    bakery = register(PixAccount(age=3650 * DAY, document=RandomGenerator.generate_cnpj()), "Padaria (10 anos)", "company")
    for _ in range(10):
        bakery.fund(10 * REAL, -2 * HOUR)
    laranja.send(50 * REAL, 10 * MINUTE, "approved", destination=bakery.as_destination())
    print("  A padaria recebeu R$ 50 de L1 (marcada), em meio a 10 clientes comuns.")
    supplier = register(company(), "Fornecedor", "company")
    _, response = bakery.pix(300 * REAL, 15 * MINUTE, destination=supplier)
    show("4 ", "A padaria paga R$ 300 ao fornecedor", response, "approved", "POLICY_PASSED")

    # ------------------------------------------------------------------ 5
    title("5. O DICT cai e o motor continua respondendo, só com as regras locais")
    payer = register(PixAccount(), "Pagador (DICT lento)", "regular")
    marked_but_unseen = register(PixDestination(), "Marcada (DICT lento)", "marked")
    DictMock.respond(marked_but_unseen, body=statistics(mule=1), delay_ms=500)
    _, response = payer.pix(100 * REAL, destination=marked_but_unseen)
    show(
        "5 ",
        "Pix para uma conta marcada, com o DICT lento demais (acima de 200 ms)",
        response,
        "approved",
        "POLICY_PASSED",
        note="Desconhecido nunca conta como evidência: a indisponibilidade é registrada, e vale o resto da política.",
    )

    out = ROOT / "output" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    (out / "accounts.json").write_text(json.dumps(ACCOUNTS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{sum(RESULTS)} de {len(RESULTS)} decisões como esperado. Papéis das contas em {out / 'accounts.json'}.")
    print("Para desenhar o grafo: python scripts/graph_demo.py")

    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
