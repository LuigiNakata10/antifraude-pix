"""Desenha o grafo de contas da demo, lendo as arestas do banco. Fica FORA da API.

Lê os papéis das contas de `output/demo/accounts.json` (escrito pelo
`seed_demo.py`) e as arestas de `account_link`, e grava a imagem em
`output/demo/grafo-demo.png`.

    python scripts/seed_demo.py
    python scripts/graph_demo.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

load_dotenv(ROOT / ".env")

from tests.utils import DbUtils  # noqa: E402
from tests.utils.pix_account import INSTITUTION_ISPB  # noqa: E402

NODE_SIZE = 900
OUTPUT = ROOT / "output" / "demo" / "grafo-demo.png"
ROLE_COLORS = {
    "marked": "#d62728",
    "suspect": "#ff7f0e",
    "victim": "#9467bd",
    "regular": "#2ca02c",
    "company": "#1f77b4",
}
ROLE_NAMES = {
    "marked": "marcada no DICT",
    "suspect": "suspeita (evidências locais)",
    "victim": "vítima",
    "regular": "conta comum",
    "company": "empresa",
}

# Cada Pix grava uma aresta `pix`; a decisão dele vem da análise. Só as arestas
# entre as contas da demo entram no desenho.
PIX_EDGES = """
    SELECT (:ispb || ':' || p.branch || ':' || p.account_number) AS from_key,
           a.destination_key AS to_key, a.amount, a.status
    FROM pix_analysis a JOIN payer_account p ON p.id = a.payer_account_id
    WHERE (:ispb || ':' || p.branch || ':' || p.account_number) = ANY(:keys)
      AND a.destination_key = ANY(:keys)
"""
DEVICE_EDGES = """
    SELECT l.from_key, l.to_key FROM account_link l JOIN pix_analysis a ON a.id = l.pix_analysis_id
    WHERE a.status = 'approved' AND l.link_type = 'device' AND l.from_key = ANY(:keys)
"""


def load_edges(keys: list) -> tuple:
    engine = create_engine(DbUtils.database_url())
    try:
        with engine.connect() as connection:
            pix = connection.execute(text(PIX_EDGES), {"keys": keys, "ispb": INSTITUTION_ISPB}).mappings().all()
            device = connection.execute(text(DEVICE_EDGES), {"keys": keys}).mappings().all()
    finally:
        engine.dispose()

    return pix, device


def build_graph(accounts: dict, pix: list, device: list) -> tuple:
    graph = nx.MultiDiGraph()
    for key, info in accounts.items():
        graph.add_node(key, **info)

    totals = defaultdict(lambda: {"amount": 0, "statuses": set()})
    for edge in pix:
        entry = totals[(edge["from_key"], edge["to_key"])]
        entry["amount"] += edge["amount"]
        entry["statuses"].add(edge["status"])
    for (source, target), entry in totals.items():
        graph.add_edge(source, target, amount=entry["amount"], statuses=entry["statuses"])

    by_device = defaultdict(set)
    for edge in device:
        by_device[edge["to_key"]].add(edge["from_key"])
    shared = [sorted(keys) for keys in by_device.values() if len(keys) > 1]

    return graph, shared


def draw(graph: nx.MultiDiGraph, shared: list) -> None:
    positions = nx.spring_layout(graph.to_undirected(), seed=11, k=2.4, iterations=400)
    figure, axis = plt.subplots(figsize=(16, 10))

    colors = [ROLE_COLORS[graph.nodes[node]["role"]] for node in graph.nodes]
    nx.draw_networkx_nodes(graph, positions, node_color=colors, node_size=NODE_SIZE, ax=axis, alpha=0.95)
    # O rótulo vai ABAIXO do nó, sobre um fundo branco, para não brigar com as setas.
    for node, (x, y) in positions.items():
        axis.text(
            x, y - 0.075, graph.nodes[node]["label"], ha="center", va="top", fontsize=8, zorder=5,
            bbox={"boxstyle": "round,pad=0.2", "facecolor": "white", "edgecolor": "none", "alpha": 0.85},
        )

    approved = [(u, v) for u, v, data in graph.edges(data=True) if data["statuses"] == {"approved"}]
    blocked = [(u, v) for u, v, data in graph.edges(data=True) if data["statuses"] != {"approved"}]
    nx.draw_networkx_edges(graph, positions, edgelist=approved, edge_color="#2ca02c", arrows=True, ax=axis, node_size=NODE_SIZE, width=1.6)
    nx.draw_networkx_edges(
        graph, positions, edgelist=blocked, edge_color="#d62728", style="dashed", arrows=True, ax=axis, node_size=NODE_SIZE, width=1.6
    )
    labels = {(u, v): f"R$ {data['amount'] / 100:,.0f}".replace(",", ".") for u, v, data in graph.edges(data=True)}
    nx.draw_networkx_edge_labels(
        graph, positions, edge_labels=labels, font_size=8, ax=axis, label_pos=0.5,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 0.5},
    )

    for keys in shared:
        for first, second in zip(keys, keys[1:]):
            axis.plot(
                [positions[first][0], positions[second][0]],
                [positions[first][1], positions[second][1]],
                color="#7f7f7f", linestyle=":", linewidth=2.2, zorder=0,
            )

    legend = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=ROLE_COLORS[role], markersize=11, label=name)
              for role, name in ROLE_NAMES.items()]
    legend += [
        plt.Line2D([0], [0], color="#2ca02c", lw=2, label="Pix aprovado"),
        plt.Line2D([0], [0], color="#d62728", lw=2, linestyle="--", label="Pix rejeitado ou com 2FA"),
        plt.Line2D([0], [0], color="#7f7f7f", lw=2, linestyle=":", label="mesmo aparelho"),
    ]
    axis.legend(handles=legend, loc="lower left", fontsize=8)
    axis.set_title("Grafo de contas da demo: o motor segue o dinheiro e o aparelho a partir das contas marcadas")
    axis.axis("off")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(OUTPUT, dpi=140)


def main() -> int:
    accounts_file = OUTPUT.parent / "accounts.json"
    if not accounts_file.exists():
        print("Rode antes: python scripts/seed_demo.py")
        return 1

    accounts = json.loads(accounts_file.read_text(encoding="utf-8"))
    pix, device = load_edges(list(accounts))
    graph, shared = build_graph(accounts, pix, device)
    draw(graph, shared)
    print(f"{graph.number_of_nodes()} contas, {graph.number_of_edges()} fluxos de Pix, "
          f"{len(shared)} aparelho(s) compartilhado(s). Imagem em {OUTPUT}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
