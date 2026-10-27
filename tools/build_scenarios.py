"""Gera assets/scenarios.json: para cada modo (pré-flop, flop, turn) e número de oponentes (1..9),
a pior e a melhor chance possíveis e a distribuição (histograma de 1 em 1 ponto) das chances.

- Pré-flop: exato a partir da tabela das 169 mãos (assets/preflop_equity.json), ponderado pelas combinações.
- Flop/turn: o máximo é 100% (dá para ter a mão imbatível, ex.: royal flush). A distribuição vem de
  mãos aleatórias simuladas; o mínimo é estimado refinando as piores mãos encontradas.

Uso:  uv run python tools/build_scenarios.py [mãos_por_cenário]
"""

from __future__ import annotations

import json
import random
import sys
from multiprocessing import Pool
from pathlib import Path

from pokertrainer import engine as E

ASSETS = Path(__file__).resolve().parent.parent / "pokertrainer" / "assets"
MAX_OPP = 9
BINS = 100
MIN_MARGIN = 0.015


def hist_of(values: list[float], weights: list[float] | None = None) -> list[float]:
    h = [0.0] * BINS
    weights = weights or [1.0] * len(values)
    for v, w in zip(values, weights):
        h[min(BINS - 1, int(v * BINS))] += w
    tot = sum(h)
    return [round(x / tot, 5) for x in h]


def preflop() -> dict[str, dict]:
    table = json.loads((ASSETS / "preflop_equity.json").read_text())["equity"]
    out = {}
    for n in range(1, MAX_OPP + 1):
        t = table[str(n)]
        vals, ws = [], []
        for lab, eq in t.items():
            vals.append(eq)
            ws.append(6 if len(lab) == 2 else 4 if lab.endswith("s") else 12)
        out[str(n)] = {"min": min(vals), "max": max(vals), "hist": hist_of(vals, ws),
                       "best": max(t, key=t.get), "worst": min(t, key=t.get)}
    return out


def sample_job(args: tuple[int, int, int, int]) -> list[tuple[float, list[int], list[int]]]:
    visible, n, count, seed = args
    rng = random.Random(seed)
    res = []
    for _ in range(count):
        d = E.deal(visible, n, rng)
        r = E.equity(d.hero, d.visible_board, n, 1500, rng)
        res.append((r.equity, d.hero, d.visible_board))
    return res


def refine_job(args: tuple[list[int], list[int], int]) -> float:
    hero, board, n = args
    return E.equity(hero, board, n, 30000, random.Random(7)).equity


def postflop(visible: int, per: int, pool: Pool) -> dict[str, dict]:
    out = {}
    for n in range(1, MAX_OPP + 1):
        chunks = [(visible, n, per // 20, 1000 * n + k + 17 * visible) for k in range(20)]
        rows = [r for part in pool.map(sample_job, chunks) for r in part]
        vals = [r[0] for r in rows]
        worst = sorted(rows, key=lambda r: r[0])[:24]
        refined = pool.map(refine_job, [(h, b, n) for _, h, b in worst])
        # amostragem acha mãos ruins, mas não necessariamente a pior: buscas dirigidas acharam até
        # ~0,6 ponto abaixo, então aplicamos 1,5 ponto de margem para a resposta nunca ficar fora da barra
        lo = min(min(refined), min(vals)) - MIN_MARGIN
        out[str(n)] = {"min": round(max(0.0, lo), 4), "max": 1.0, "hist": hist_of(vals)}
        print(f"  visível={visible} oponentes={n}: mín≈{lo:.3f}", flush=True)
    return out


def main() -> None:
    per = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    data = {"preflop": preflop()}
    with Pool() as pool:
        data["flop"] = postflop(3, per, pool)
        data["turn"] = postflop(4, per, pool)
    (ASSETS / "scenarios.json").write_text(json.dumps(data, separators=(",", ":")))
    print("salvo em", ASSETS / "scenarios.json")


if __name__ == "__main__":
    main()
