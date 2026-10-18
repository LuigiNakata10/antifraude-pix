"""Desenha o grafo de contas da demo, lendo as arestas do banco. Fica FORA da API.

Lê os papéis das contas de `output/demo/accounts.json` (escrito pelo
`seed_demo.py`) e as arestas de `account_link`, e grava a imagem em
`output/demo/grafo-demo-v2.png` (proporção de slide, 16:9).

v2: quando as contas são as da demo (os rótulos do `seed_demo.py`), cada cena
tem um lugar fixo no desenho, com uma legenda curta do passo; senão, cada grupo
de contas ligadas é posicionado sozinho e os grupos são encaixados lado a lado.
Nós, rótulos e legenda maiores, para leitura em projetor.

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

NODE_SIZE = 1500
OUTPUT = ROOT / "output" / "demo" / "grafo-demo-v2.png"
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


# O lugar de cada conta da demo, por cena (coordenadas num quadro de 10 x 5,6).
STORY_LAYOUT = {
    # 1. mesada x vítima nova
    "Vítima nova": (0.3, 4.9),
    "Filho (marcado no DICT)": (1.35, 3.6),
    "Mãe": (2.4, 4.9),
    # 5. DICT lento
    "Pagador (DICT lento)": (0.3, 1.1),
    "Marcada (DICT lento)": (2.2, 1.1),
    # 2. L1 paga a luz, não repassa; 4. padaria de boa-fé
    "Vítima do golpe": (3.8, 4.3),
    "L1 (laranja, marcada)": (5.0, 3.1),
    "Recebe o repasse": (6.3, 4.3),
    "Concessionária de luz": (3.8, 1.95),
    "Padaria (10 anos)": (5.0, 1.45),
    "Fornecedor": (6.6, 1.45),
    # 3. L2: mesmo aparelho de L1 e seis titulares novos
    "L2 (conta nova)": (8.2, 3.1),
    "Recebe o repasse de L2": (7.6, 1.0),
}
for _index, _angle in enumerate((125, 85, 45, 5, -35, -75)):
    from math import cos, radians, sin
    STORY_LAYOUT[f"Vítima nova {_index + 1}"] = (8.2 + 1.6 * cos(radians(_angle)), 3.1 + 1.6 * sin(radians(_angle)))

STORY_CAPTIONS = [
    (1.35, 5.6, "1. vítima nova barrada, mãe passa"),
    (1.25, 0.45, "5. DICT lento: decide sem ele"),
    (5.05, 5.6, "2. L1 paga a luz, não repassa"),
    (4.75, 0.75, "4. padaria de boa-fé segue normal"),
    (8.5, 5.6, "3. L2: aparelho de L1 + 6 novos"),
]
# Onde fica o rótulo da linha de aparelho compartilhado, entre L1 e L2.
STORY_DEVICE_NOTE = (6.6, 3.28, "mesmo aparelho")
# O quadro da demo: inclui as legendas de cena, que não são nós.
STORY_LIMITS = ((-0.45, 10.55), (0.2, 5.9))


def story_layout(graph: nx.MultiDiGraph):
    """O layout fixo da demo, se TODAS as contas forem as do `seed_demo.py`; senão, None."""
    labels = {node: graph.nodes[node]["label"] for node in graph.nodes}
    if not set(labels.values()) <= set(STORY_LAYOUT):
        return None

    return {node: STORY_LAYOUT[label] for node, label in labels.items()}


def component_layout(graph: nx.Graph, nodes: set, seed: int) -> dict:
    """Posições de um grupo de contas, normalizadas para caber num quadrado de lado 1."""
    sub = graph.subgraph(nodes)
    if len(nodes) == 1:
        return {next(iter(nodes)): (0.5, 0.5)}
    positions = nx.spring_layout(sub, seed=seed, k=1.6 / len(nodes) ** 0.5, iterations=500)
    xs = [x for x, _ in positions.values()]
    ys = [y for _, y in positions.values()]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1
    return {node: ((x - min(xs)) / span, (y - min(ys)) / span) for node, (x, y) in positions.items()}


def pack_layout(graph: nx.MultiDiGraph, shared: list) -> dict:
    """Cada componente ligado é desenhado sozinho e os componentes são encaixados.

    O maior grupo fica à esquerda, ocupando a altura toda; os menores são
    empilhados numa coluna à direita. Assim não sobram grandes vazios entre
    grupos que não têm ligação nenhuma entre si.
    """
    connected = graph.to_undirected()
    for keys in shared:
        for first, second in zip(keys, keys[1:]):
            connected.add_edge(first, second)
    components = sorted(nx.connected_components(connected), key=len, reverse=True)

    positions = {}
    big, rest = components[0], components[1:]
    for node, (x, y) in component_layout(connected, big, seed=11).items():
        positions[node] = (x * 1.55, y * 1.0)

    if rest:
        slot = 1.0 / len(rest)
        for index, nodes in enumerate(rest):
            scale = slot * 0.62
            for node, (x, y) in component_layout(connected, nodes, seed=3 + index).items():
                positions[node] = (1.9 + x * scale * 1.4, 1.0 - slot * (index + 1) + slot * 0.2 + y * scale)

    return positions


def draw(graph: nx.MultiDiGraph, shared: list) -> None:
    positions = story_layout(graph)
    captions = STORY_CAPTIONS if positions else []
    if positions is None:
        positions = pack_layout(graph, shared)
    ys = [y for _, y in positions.values()]
    label_offset = 0.06 * ((max(ys) - min(ys)) or 1)
    figure, axis = plt.subplots(figsize=(16, 9))

    for x, y, caption in captions:
        axis.text(x, y, caption, ha="center", va="center", fontsize=15, color="#333333", style="italic", zorder=6)
    if captions:
        x, y, note = STORY_DEVICE_NOTE
        axis.text(x, y, note, ha="center", va="bottom", fontsize=12, color="#555555", zorder=6)

    for keys in shared:
        for first, second in zip(keys, keys[1:]):
            axis.plot(
                [positions[first][0], positions[second][0]],
                [positions[first][1], positions[second][1]],
                color="#7f7f7f", linestyle=":", linewidth=3, zorder=0,
            )

    colors = [ROLE_COLORS[graph.nodes[node]["role"]] for node in graph.nodes]
    nx.draw_networkx_nodes(
        graph, positions, node_color=colors, node_size=NODE_SIZE, ax=axis, alpha=0.95, edgecolors="white", linewidths=2
    )
    # O rótulo vai ABAIXO do nó, sobre um fundo branco, para não brigar com as setas.
    for node, (x, y) in positions.items():
        axis.text(
            x, y - label_offset, graph.nodes[node]["label"], ha="center", va="top", fontsize=12, zorder=5,
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "none", "alpha": 0.9},
        )

    approved = [(u, v) for u, v, data in graph.edges(data=True) if data["statuses"] == {"approved"}]
    blocked = [(u, v) for u, v, data in graph.edges(data=True) if data["statuses"] != {"approved"}]
    common = {"arrows": True, "ax": axis, "node_size": NODE_SIZE, "width": 2.6, "arrowsize": 22}
    nx.draw_networkx_edges(graph, positions, edgelist=approved, edge_color="#2ca02c", **common)
    nx.draw_networkx_edges(graph, positions, edgelist=blocked, edge_color="#d62728", style="dashed", **common)
    labels = {(u, v): f"R$ {data['amount'] / 100:,.0f}".replace(",", ".") for u, v, data in graph.edges(data=True)}
    nx.draw_networkx_edge_labels(
        graph, positions, edge_labels=labels, font_size=11, ax=axis, label_pos=0.5,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.9, "pad": 0.6},
    )

    legend = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=ROLE_COLORS[role], markersize=18, label=name)
              for role, name in ROLE_NAMES.items()]
    legend += [
        plt.Line2D([0], [0], color="#2ca02c", lw=3, label="Pix aprovado"),
        plt.Line2D([0], [0], color="#d62728", lw=3, linestyle="--", label="Pix rejeitado ou com 2FA"),
        plt.Line2D([0], [0], color="#7f7f7f", lw=3, linestyle=":", label="mesmo aparelho"),
    ]
    axis.legend(
        handles=legend, loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=4, fontsize=14,
        frameon=False, handlelength=2.2, columnspacing=1.6,
    )
    axis.axis("off")
    if captions:
        axis.set_xlim(*STORY_LIMITS[0])
        axis.set_ylim(*STORY_LIMITS[1])
    else:
        axis.margins(0.04)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUTPUT, dpi=160, bbox_inches="tight", pad_inches=0.15)


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
