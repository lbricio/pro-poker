"""Simula muitas mesas com bots de todas as personalidades e dificuldades misturados e gera um relatório.

- mesas de tamanho aleatório (2 a 10 jogadores), refeitas a cada `--per-table` mãos;
- cada assento recebe uma combinação sorteada de dificuldade × personalidade (o Campeão só existe no Pro);
- blinds 5/10, stacks de 1000 (100 big blinds); quem quebra recompra;
- os bots usam tudo o que usam no jogo: humor/tilt, memória sobre os outros, pressão etc.

Uso:  uv run python tools/simulate_population.py --hands 1000000 [--out relatorio.md] [--workers 6]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pokertrainer import ai  # noqa: E402
from pokertrainer import table as T  # noqa: E402
from pokertrainer.i18n import set_lang  # noqa: E402

BB = 10
FIELDS = ("hands", "net", "net2", "won", "sd", "sd_won", "vpip", "pfr", "busts")


def combos() -> list[tuple[str, str]]:
    out = [(d, a) for d in ai.DIFFICULTIES for a in ai.ARCHETYPES if a != "champion"]
    out.append(("pro", "champion"))
    return out


def run_chunk(args: tuple) -> dict:
    seed, hands, per_table = args[:3]
    level = args[3] if len(args) > 3 else None     # modo por nível: todos os assentos do mesmo nível
    allowed = args[4] if len(args) > 4 else None   # só estes níveis (misturados entre si)
    rng = random.Random(seed)
    all_combos = [c for c in combos() if (level is None or c[0] == level) and (allowed is None or c[0] in allowed)]
    stats: dict[str, dict[str, float]] = defaultdict(lambda: dict.fromkeys(FIELDS, 0.0))

    def new_player(combo):
        d, a = combo
        pers = ai.make_personality(d, rng, a)
        p = T.Player(f"{d}:{a}", 1000, ai=ai.Bot(pers, random.Random(rng.random())))
        p.combo = combo
        return p

    done = 0
    while done < hands:
        size = rng.randint(2, 10)
        t = T.Table([new_player(rng.choice(all_combos)) for _ in range(size)], 5, BB, rng)
        for _ in range(min(per_table, hands - done)):
            for p in t.players:
                if p.stack <= 0:                         # recompra (conta como quebra)
                    stats["|".join(p.combo)]["busts"] += 1
                    p.stack, p.sitting_out = 1000, False
            before = [(p.vpip, p.pfr) for p in t.players]
            t.start_hand()
            while not t.hand_over:
                s = t.to_act
                d = t.players[s].ai.decide(t, s)
                t.act(d.action, d.amount_to)
            for i, p in enumerate(t.players):
                k = "|".join(p.combo)
                st = stats[k]
                net = (t.winners.get(i, 0) - p.total) / BB
                st["hands"] += 1
                st["net"] += net
                st["net2"] += net * net
                st["won"] += i in t.winners
                if i in t.showdown_hands:
                    st["sd"] += 1
                    st["sd_won"] += i in t.winners
                st["vpip"] += p.vpip - before[i][0]
                st["pfr"] += p.pfr - before[i][1]
                p.ai.after_hand(t.winners.get(i, 0) - p.total, BB, False)
            for i, p in enumerate(t.players):
                p.ai.observe_hand(t, i)
            done += 1
    return {k: dict(v) for k, v in stats.items()}


def merge(results: list[dict]) -> dict:
    tot: dict[str, dict[str, float]] = defaultdict(lambda: dict.fromkeys(FIELDS, 0.0))
    for r in results:
        for k, v in r.items():
            for f in FIELDS:
                tot[k][f] += v[f]
    return tot


def summarize(st: dict) -> dict:
    n = max(1, st["hands"])
    mean = st["net"] / n
    var = max(0.0, st["net2"] / n - mean * mean)
    return {"hands": int(st["hands"]), "bb100": mean * 100, "ci": 1.96 * math.sqrt(var / n) * 100,
            "won": st["won"] / n, "sd_won": st["sd_won"] / st["sd"] if st["sd"] else 0.0,
            "vpip": st["vpip"] / n, "pfr": st["pfr"] / n, "busts100": st["busts"] / n * 100}


def report(tot: dict, hands: int, seconds: float, by_level: bool = False, levels: tuple | None = None) -> str:
    set_lang("pt")
    name = {a: ai.archetype_short(a) for a in ai.ARCHETYPES}
    lvl = {d: ai.difficulty_name(d) for d in ai.DIFFICULTIES}

    def group(keyfn):
        g: dict[str, dict[str, float]] = defaultdict(lambda: dict.fromkeys(FIELDS, 0.0))
        for k, v in tot.items():
            for f in FIELDS:
                g[keyfn(k)][f] += v[f]
        return g

    head = ("| {} | Mãos | bb/100 | ±IC 95% | Mãos ganhas | Showdowns vencidos | VPIP | PFR | Quebras/100 mãos |\n"
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    if levels:
        intro = (f"Só os níveis {', '.join(ai.difficulty_name(d) for d in levels)}, misturados na mesma mesa; "
                 "personalidades sorteadas por assento.")
    elif by_level:
        intro = ("Cada mesa tem um nível só (Fácil com Fácil, Médio com Médio…); personalidades sorteadas por "
                 "assento (o Campeão só no Pro). Como as mesas são fechadas, a média de cada nível fica perto de "
                 "zero: compare as personalidades dentro de cada nível.")
    else:
        intro = "Mesas com combinações dificuldade × personalidade sorteadas por assento (níveis misturados)."
    lines = [f"# Simulação de população — {hands:,} mãos".replace(",", "."), "",
             f"{intro} Mesas de 2 a 10 jogadores, blinds 5/10 e 100 big blinds. Tempo: {seconds / 60:.0f} min.",
             "", "A coluna Mãos conta mãos jogadas por jogador.", ""]

    def row(label, s):
        return (f"| {label} | {s['hands']:,} | {s['bb100']:+.1f} | {s['ci']:.1f} | {s['won']:.1%} | "
                f"{s['sd_won']:.1%} | {s['vpip']:.0%} | {s['pfr']:.0%} | {s['busts100']:.2f} |").replace(",", ".")

    lines += ["## Por nível", "", head.format("Nível")]
    by_lvl = group(lambda k: k.split("|")[0])
    for d in ai.DIFFICULTIES:
        if by_lvl[d]["hands"]:
            lines.append(row(lvl[d], summarize(by_lvl[d])))
    lines += ["", "## Por personalidade", "", head.format("Personalidade")]
    by_arch = group(lambda k: k.split("|")[1])
    for a in sorted(by_arch, key=lambda a: -summarize(by_arch[a])["bb100"]):
        lines.append(row(name[a], summarize(by_arch[a])))
    lines += ["", "## Nível × personalidade", "", head.format("Nível · Personalidade")]
    for d in ai.DIFFICULTIES:
        keys = [k for k in tot if k.startswith(d + "|")]
        for k in sorted(keys, key=lambda k: -summarize(tot[k])["bb100"]):
            lines.append(row(f"{lvl[d]} · {name[k.split('|')[1]]}", summarize(tot[k])))
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=1_000_000)
    ap.add_argument("--chunk", type=int, default=5000)
    ap.add_argument("--per-table", type=int, default=200)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", default="simulacao_populacao.md")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--by-level", action="store_true", help="cada mesa com um nível só (sem misturar)")
    ap.add_argument("--levels", default="", help="só estes níveis, misturados entre si (ex.: pro,semipro)")
    args = ap.parse_args()
    n_chunks = math.ceil(args.hands / args.chunk)
    levels = tuple(x.strip() for x in args.levels.split(",") if x.strip()) or None
    jobs = [(args.seed * 100000 + i, min(args.chunk, args.hands - i * args.chunk), args.per_table,
             ai.DIFFICULTIES[i % len(ai.DIFFICULTIES)] if args.by_level else None, levels)
            for i in range(n_chunks)]
    t0 = time.time()
    results = []
    with Pool(args.workers) as pool:
        for k, r in enumerate(pool.imap_unordered(run_chunk, jobs), 1):
            results.append(r)
            done = min(args.hands, k * args.chunk)
            el = time.time() - t0
            print(f"{done:>9,} mãos  ({k}/{n_chunks})  {el / 60:5.1f} min  ~{el / k * (n_chunks - k) / 60:4.1f} min "
                  f"restantes", flush=True)
    tot = merge(results)
    secs = time.time() - t0
    Path(args.out).write_text(report(tot, args.hands, secs, args.by_level, levels))
    Path(args.out).with_suffix(".json").write_text(json.dumps(tot))
    print("relatório:", args.out)


if __name__ == "__main__":
    main()
