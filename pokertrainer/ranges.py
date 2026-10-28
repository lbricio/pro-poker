"""Faixas de mãos dos oponentes conforme a posição e a ação.

Ninguém aumenta, aposta ou paga com uma mão aleatória. Antes do flop a faixa vem da posição e do que o jogador
fez (aumentou, pagou um aumento, só pagou o big blind); depois do flop, cada combinação da faixa recebe um peso
conforme a classe da mão naquela mesa e a ação (apostou, pagou, passou). As faixas viram listas de combinações
com repetição (mais repetições = mais peso), que o motor de equidade sorteia.
"""

from __future__ import annotations

from functools import lru_cache

from pokertrainer import coach
from pokertrainer import engine as E
from pokertrainer.i18n import tr

# ---------------------------------------------------------------- pré-flop

# % das mãos com que um jogador sólido abre (aumenta primeiro) em cada posição de uma mesa cheia
OPEN_PCT = {"UTG": 14, "UTG+1": 16, "UTG+2": 18, "MP": 20, "HJ": 23, "CO": 28, "BTN": 42, "SB": 36, "BB": 30}
CALL_BAND = (4, 30)     # quem só paga um aumento: top 30% sem o top 4% (com essas ele voltaria a aumentar)
LIMP_BAND = (6, 55)     # quem só paga o big blind: mãos medianas (as fortes aumentariam)
THREEBET_PCT = 5        # quem re-aumenta (3-bet) por valor
ANY = (0, 100)

# posição de quem tem `k` jogadores para agir depois dele antes do flop (mesa de até 10)
POS_BY_BEHIND = {1: "SB", 2: "BTN", 3: "CO", 4: "HJ", 5: "MP", 6: "UTG+2", 7: "UTG+1", 8: "UTG", 9: "UTG"}
SEAT_ORDER = ["UTG", "UTG+1", "UTG+2", "MP", "HJ", "CO", "BTN", "SB", "BB"]


@lru_cache(maxsize=None)
def band_labels(lo: int, hi: int) -> frozenset[str]:
    """Mãos entre o top `lo`% e o top `hi`% (ex.: (4, 30) = top 30% sem o top 4%)."""
    top = coach.range_labels(hi)
    return top - coach.range_labels(lo) if lo > 0 else top


@lru_cache(maxsize=None)
def band_combos(lo: int, hi: int) -> tuple[tuple[int, int], ...]:
    if lo <= 0 and hi >= 100:
        return tuple((a, b) for a in range(52) for b in range(a + 1, 52))
    return tuple(E.label_combos(band_labels(lo, hi)))


@lru_cache(maxsize=1)
def _percentiles() -> dict[str, float]:
    out, acc = {}, 0
    for lab in coach.hand_order():
        acc += 6 if len(lab) == 2 else 4 if lab.endswith("s") else 12
        out[lab] = acc / 1326 * 100
    return out


def hand_pct(hole: list[int]) -> float:
    """Em que top % das mãos iniciais a mão está (AA ≈ 0,5; 72o ≈ 100)."""
    return _percentiles().get(E.starting_hand_label(*hole), 100.0)


def open_pct(pos: str) -> int:
    return OPEN_PCT.get(pos, 20)


# ---------------------------------------------------------------- depois do flop: classes de mão

STRONG, TOP, WEAK, DRAW, GUTSHOT, AIR = range(6)
CLASS_NAMES = {STRONG: ("dois pares ou melhor", "two pair or better"), TOP: ("par alto (top pair ou overpair)",
               "top pair or overpair"), WEAK: ("par médio ou baixo", "middle or low pair"),
               DRAW: ("projeto forte (8+ outs)", "strong draw (8+ outs)"),
               GUTSHOT: ("projeto fraco ou cartas altas", "weak draw or overcards"), AIR: ("nada", "nothing")}


def class_name(c: int) -> str:
    return tr(*CLASS_NAMES[c])


def draw_outs(hole: list[int], board: list[int]) -> int:
    """Outs aproximados de flush e sequência (rápido, para classificar faixas inteiras)."""
    if len(board) not in (3, 4):
        return 0
    cards = hole + board
    outs = 0
    for sv in range(4):
        n = sum(1 for c in cards if c & 3 == sv)
        if n == 4 and any(c & 3 == sv for c in hole):
            outs += 9
            break
    mask = 0
    for c in cards:
        mask |= 1 << (c >> 2)
    bmask = 0
    for c in board:
        bmask |= 1 << (c >> 2)
    if E.STRAIGHT_HIGH[mask] < 0:
        ranks = sum(1 for r in range(13) if not mask >> r & 1
                    and E.STRAIGHT_HIGH[mask | 1 << r] >= 0 and E.STRAIGHT_HIGH[bmask | 1 << r] < 0)
        outs += 4 * min(2, ranks)
    return outs


def hand_class(hole: list[int], board: list[int]) -> int:
    cat = E.evaluate(hole + board) >> 20
    if cat > E.board_category(board):
        if cat >= E.TWO_PAIR:
            return STRONG
        if cat == E.PAIR:
            ranks = [c >> 2 for c in hole + board]
            pair = max(rk for rk in set(ranks) if ranks.count(rk) >= 2)
            if pair >= max(c >> 2 for c in board):
                return TOP
            return DRAW if draw_outs(hole, board) >= 8 else WEAK
    outs = draw_outs(hole, board)
    if outs >= 8:
        return DRAW
    if len(board) < 5 and (outs >= 4 or min(c >> 2 for c in hole) > max(c >> 2 for c in board)):
        return GUTSHOT
    return AIR


# peso de cada classe (STRONG, TOP, WEAK, DRAW, GUTSHOT, AIR) conforme a ação; por rua (3 flop, 4 turn, 5 river)
WEIGHTS = {
    "bet": {3: (1.0, .9, .35, .7, .35, .2), 4: (1.0, .85, .25, .6, .25, .15), 5: (1.0, .7, .12, 0, 0, .25)},
    "call": {3: (.9, 1.0, .7, .95, .5, .08), 4: (.9, 1.0, .55, .85, .3, .05), 5: (.95, .95, .45, 0, 0, .03)},
    "check": {3: (.35, .6, .9, .75, .9, 1.0), 4: (.3, .6, .9, .75, .9, 1.0), 5: (.25, .55, .9, 0, 0, 1.0)},
    "call_raise": {3: (1.0, .55, .12, .55, .1, .02), 4: (1.0, .5, .1, .45, .05, .01),
                   5: (1.0, .35, .03, 0, 0, .01)},
}


def weighted(combos, board: list[int], known: set[int], actions: tuple[str, ...] = ()) -> list[tuple[int, int]]:
    """Combinações livres da faixa, repetidas conforme o peso das ações (0 a 10 cópias)."""
    out = []
    street = len(board)
    for a, b in combos:
        if a in known or b in known:
            continue
        w = 1.0
        if actions and street >= 3:
            c = hand_class([a, b], board)
            for act in actions:
                w *= WEIGHTS[act][street][c]
        k = int(round(w * 10))
        if k:
            out.extend([(a, b)] * k)
    return out


def class_mix(combos: list[tuple[int, int]], board: list[int]) -> dict[int, float]:
    """Fração de cada classe numa faixa ponderada (para explicar o que o oponente costuma ter)."""
    if not combos or len(board) < 3:
        return {}
    cnt: dict[int, int] = {}
    for a, b in combos:
        c = hand_class([a, b], board)
        cnt[c] = cnt.get(c, 0) + 1
    n = len(combos)
    return {c: v / n for c, v in cnt.items()}


# ---------------------------------------------------------------- mesa ao vivo (cash game / torneio)

def table_ranges(t, hero_seat: int = 0) -> list[list[tuple[int, int]]]:
    """Faixa de cada oponente ainda na mão, a partir do que ele fez nesta mão (para o assistente da mesa)."""
    hero = t.players[hero_seat]
    known = set(hero.hole) | set(t.board)
    out = []
    for i in t.seats_in_hand():
        if i == hero_seat:
            continue
        p = t.players[i]
        if p._pfr_hand:
            pf = (0, THREEBET_PCT) if t.pf_aggressor == i and t._pf_raises >= 2 else (0, open_pct(t.position_of(i)))
        elif p._vpip_hand:
            pf = CALL_BAND if t._pf_raises else LIMP_BAND
        else:
            pf = ANY                       # big blind que só passou
        acts: tuple[str, ...] = ()
        if len(t.board) >= 3:
            if p.post_aggr == t.street:
                acts = ("bet",)
            elif p.last_action == "call":
                acts = ("call",)
            elif p.last_action == "check":
                acts = ("check",)
        r = weighted(band_combos(*pf), list(t.board), known, acts)
        out.append(r or list(band_combos(0, 100)))
    return out
