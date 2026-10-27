"""Gera assets/preflop_equity.json: equidade de cada uma das 169 mãos iniciais contra 1..9 oponentes.

Uso:  uv run python tools/build_preflop_table.py [iteracoes]
"""

from __future__ import annotations

import json
import random
import sys
from multiprocessing import Pool
from pathlib import Path

from pokertrainer.engine import RANK_CHARS, card, equity

OUT = Path(__file__).resolve().parent.parent / "pokertrainer" / "assets" / "preflop_equity.json"
MAX_OPP = 9


def labels() -> list[str]:
    out = []
    for i in range(12, -1, -1):
        for j in range(12, -1, -1):
            a, b = RANK_CHARS[i], RANK_CHARS[j]
            if i == j:
                out.append(a + b)
            elif i > j:
                out.append(a + b + "s")
            else:
                out.append(b + a + "o")
    return out


def hole(label: str) -> list[int]:
    a, b = label[0], label[1]
    if len(label) == 2 or label[2] == "o":
        return [card(a + "s"), card(b + "h")]
    return [card(a + "s"), card(b + "s")]


def job(args: tuple[str, int, int]) -> tuple[str, int, float]:
    label, n, iters = args
    r = equity(hole(label), [], n, iters, random.Random(hash((label, n)) & 0xFFFFFFFF))
    return label, n, round(r.equity, 4)


def main() -> None:
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 60000
    tasks = [(lab, n, iters) for n in range(1, MAX_OPP + 1) for lab in labels()]
    data: dict[str, dict[str, float]] = {str(n): {} for n in range(1, MAX_OPP + 1)}
    with Pool() as pool:
        for k, (lab, n, eq) in enumerate(pool.imap_unordered(job, tasks, chunksize=4), 1):
            data[str(n)][lab] = eq
            if k % 169 == 0:
                print(f"{k}/{len(tasks)}", flush=True)
    OUT.write_text(json.dumps({"iterations": iters, "equity": data}, separators=(",", ":")))
    print("salvo em", OUT)


if __name__ == "__main__":
    main()
