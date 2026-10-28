"""Motor de poker (Texas Hold'em): cartas, avaliação de mãos e cálculo de equidade.

Cartas são inteiros 0..51: posto = c // 4 (0 = 2 ... 12 = Ás), naipe = c % 4 (paus, ouros, copas, espadas).
A pontuação de uma mão é um inteiro: quanto maior, melhor (categoria << 20 | desempates).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import combinations_with_replacement

from pokertrainer.i18n import lang, tr

RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "cdhs"
SUIT_SYMBOLS = {"c": "♣", "d": "♦", "h": "♥", "s": "♠"}

_RANK_NAMES = {
    "pt": ["Dois", "Três", "Quatro", "Cinco", "Seis", "Sete", "Oito", "Nove", "Dez", "Valete", "Dama", "Rei", "Ás"],
    "en": ["Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Jack", "Queen", "King", "Ace"],
}
_RANK_PLURAL = {
    "pt": ["Dois", "Três", "Quatros", "Cincos", "Seis", "Setes", "Oitos", "Noves", "Dez", "Valetes", "Damas", "Reis",
           "Ases"],
    "en": ["Twos", "Threes", "Fours", "Fives", "Sixes", "Sevens", "Eights", "Nines", "Tens", "Jacks", "Queens", "Kings",
           "Aces"],
}

HIGH, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)
_CATEGORY_NAMES = {
    "pt": ["Carta alta", "Par", "Dois pares", "Trinca", "Sequência", "Flush", "Full house", "Quadra", "Straight flush"],
    "en": ["High card", "Pair", "Two pair", "Three of a kind", "Straight", "Flush", "Full house", "Four of a kind",
           "Straight flush"],
}


def rank_name(r: int) -> str:
    return _RANK_NAMES[lang()][r]


def rank_plural(r: int) -> str:
    return _RANK_PLURAL[lang()][r]


def category_name(cat: int) -> str:
    return _CATEGORY_NAMES[lang()][cat]


PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]


def card(s: str) -> int:
    """'As' -> int."""
    return RANK_CHARS.index(s[0].upper()) * 4 + SUIT_CHARS.index(s[1].lower())


def card_str(c: int) -> str:
    return RANK_CHARS[c >> 2] + SUIT_CHARS[c & 3]


def card_pretty(c: int) -> str:
    r = RANK_CHARS[c >> 2]
    return ("10" if r == "T" else r) + SUIT_SYMBOLS[SUIT_CHARS[c & 3]]


# ---------------------------------------------------------------- avaliação a partir de contagens de postos

def _straight_high(mask: int) -> int:
    """Maior carta da sequência contida na máscara de postos, ou -1."""
    for hi in range(12, 3, -1):
        m = 0b11111 << (hi - 4)
        if mask & m == m:
            return hi
    if mask & 0b1000000001111 == 0b1000000001111:  # A-2-3-4-5
        return 3
    return -1


STRAIGHT_HIGH = [_straight_high(m) for m in range(1 << 13)]


def _top_bits(mask: int, n: int) -> list[int]:
    out = []
    for r in range(12, -1, -1):
        if mask >> r & 1:
            out.append(r)
            if len(out) == n:
                break
    return out


def _pack(cat: int, kickers: list[int]) -> int:
    v = cat
    for i in range(5):
        v = (v << 4) | (kickers[i] if i < len(kickers) else 0)
    return v


def score_from_ranks(counts: list[int]) -> int:
    """Melhor mão sem flush a partir de contagens por posto (5 a 7 cartas)."""
    mask = 0
    quads, trips, pairs, singles = [], [], [], []
    for r in range(12, -1, -1):
        n = counts[r]
        if n:
            mask |= 1 << r
            (singles, pairs, trips, quads)[n - 1].append(r)
    if quads:
        q = quads[0]
        rest = [r for r in range(12, -1, -1) if counts[r] and r != q]
        return _pack(QUADS, [q, rest[0]] if rest else [q])
    if trips and (len(trips) > 1 or pairs):
        t = trips[0]
        p = max(([trips[1]] if len(trips) > 1 else []) + pairs[:1])
        return _pack(FULL_HOUSE, [t, p])
    s = STRAIGHT_HIGH[mask]
    if s >= 0:
        return _pack(STRAIGHT, [s])
    if trips:
        return _pack(TRIPS, [trips[0]] + singles[:2])
    if len(pairs) >= 2:
        kick = max(pairs[2:3] + singles[:1])
        return _pack(TWO_PAIR, [pairs[0], pairs[1], kick])
    if pairs:
        return _pack(PAIR, [pairs[0]] + singles[:3])
    return _pack(HIGH, singles[:5])


def _build_table() -> dict[int, int]:
    """Tabela produto-de-primos -> pontuação para todas as combinações de 7 postos (sem flush)."""
    table: dict[int, int] = {}
    for combo in combinations_with_replacement(range(13), 7):
        counts = [0] * 13
        ok = True
        for r in combo:
            counts[r] += 1
            if counts[r] > 4:
                ok = False
                break
        if not ok:
            continue
        key = 1
        for r in combo:
            key *= PRIMES[r]
        table[key] = score_from_ranks(counts)
    return table


@lru_cache(maxsize=1)
def rank_table() -> dict[int, int]:
    return _build_table()


def evaluate(cards: list[int] | tuple[int, ...]) -> int:
    """Pontuação da melhor mão de 5 cartas entre 5 a 7 cartas."""
    counts = [0] * 13
    suits = [0, 0, 0, 0]
    for c in cards:
        counts[c >> 2] += 1
        suits[c & 3] |= 1 << (c >> 2)
    for m in suits:
        if m.bit_count() >= 5:
            # com 7 cartas, flush exclui quadra e full house
            s = STRAIGHT_HIGH[m]
            if s >= 0:
                return _pack(STRAIGHT_FLUSH, [s])
            return _pack(FLUSH, _top_bits(m, 5))
    return score_from_ranks(counts)


def category(score: int) -> int:
    return score >> 20


def best_five(cards: list[int]) -> list[int]:
    """As 5 cartas que formam a melhor mão entre 5 a 7 cartas."""
    from itertools import combinations
    return list(max(combinations(cards, 5), key=lambda c: evaluate(list(c))))


def describe(score: int) -> str:
    """Nome legível da mão, ex.: 'Par de Ases', 'Full house: Reis com Dez'."""
    cat = score >> 20
    k = [(score >> (16 - 4 * i)) & 0xF for i in range(5)]
    n, pl = rank_name, rank_plural
    if cat == STRAIGHT_FLUSH:
        return "Royal flush" if k[0] == 12 else tr(f"Straight flush até {n(k[0])}", f"Straight flush, {n(k[0])} high")
    if cat == QUADS:
        return tr(f"Quadra de {pl(k[0])}", f"Four of a kind, {pl(k[0])}")
    if cat == FULL_HOUSE:
        return tr(f"Full house: {pl(k[0])} com {pl(k[1])}", f"Full house, {pl(k[0])} over {pl(k[1])}")
    if cat == FLUSH:
        return tr(f"Flush, {n(k[0])} alto", f"Flush, {n(k[0])} high")
    if cat == STRAIGHT:
        return tr(f"Sequência até {n(k[0])}", f"Straight, {n(k[0])} high")
    if cat == TRIPS:
        return tr(f"Trinca de {pl(k[0])}", f"Three of a kind, {pl(k[0])}")
    if cat == TWO_PAIR:
        return tr(f"Dois pares: {pl(k[0])} e {pl(k[1])}", f"Two pair, {pl(k[0])} and {pl(k[1])}")
    if cat == PAIR:
        return tr(f"Par de {pl(k[0])}", f"Pair of {pl(k[0])}")
    return tr(f"Carta alta: {n(k[0])}", f"High card, {n(k[0])}")


def describe_cards(cards: list[int]) -> str:
    """Descrição da mão atual (funciona também com 2 cartas)."""
    if len(cards) >= 5:
        return describe(evaluate(cards))
    r = sorted((c >> 2 for c in cards), reverse=True)
    if len(r) == 2 and r[0] == r[1]:
        return tr(f"Par de {rank_plural(r[0])}", f"Pair of {rank_plural(r[0])}")
    return tr(f"Carta alta: {rank_name(r[0])}", f"High card, {rank_name(r[0])}")


def starting_hand_label(c1: int, c2: int) -> str:
    """Notação de mão inicial: 'AKs', 'QJo', '77'."""
    r1, r2 = c1 >> 2, c2 >> 2
    if r1 < r2:
        r1, r2 = r2, r1
    if r1 == r2:
        return RANK_CHARS[r1] * 2
    return RANK_CHARS[r1] + RANK_CHARS[r2] + ("s" if (c1 & 3) == (c2 & 3) else "o")


# ---------------------------------------------------------------- equidade (Monte Carlo)

@dataclass
class EquityResult:
    equity: float          # vitória + parte dos empates (0..1)
    win: float
    tie: float
    iterations: int
    final_categories: list[float] = field(default_factory=lambda: [0.0] * 9)  # sua mão final no river
    stderr: float = 0.0
    vs_random: float | None = None   # mesma mão contra mãos aleatórias (quando os oponentes têm faixa)
    eq_call: float | None = None     # contra as mãos que pagariam a sua aposta/aumento (treino de decisões)


def label_combos(labels) -> list[tuple[int, int]]:
    """Todas as combinações de 2 cartas das mãos iniciais dadas ('AKs', 'QQ', '72o'...)."""
    want = set(labels)
    return [(a, b) for a in range(52) for b in range(a + 1, 52) if starting_hand_label(a, b) in want]


def _pick_range_hands(combos: list[tuple[int, int]], n: int, used: set[int], rng: random.Random) -> list[list[int]]:
    """Sorteia `n` mãos da faixa sem repetir cartas (rejeição; `used` é atualizado)."""
    hands = []
    choice = rng.choice
    for _ in range(n):
        for _try in range(60):
            a, b = choice(combos)
            if a not in used and b not in used:
                break
        else:
            # muitas colisões (faixas estreitas e parecidas): sorteia entre as combinações ainda livres
            free_combos = [(x, y) for x, y in combos if x not in used and y not in used]
            if free_combos:
                a, b = choice(free_combos)
            else:  # faixa toda bloqueada: cai para mão aleatória
                free = [c for c in range(52) if c not in used]
                a, b = rng.sample(free, 2)
        used.add(a)
        used.add(b)
        hands.append([a, b])
    return hands


def equity(hero: list[int], board: list[int], n_opponents: int, iterations: int = 20000,
           rng: random.Random | None = None, cancel=None,
           opp_combos: list[tuple[int, int]] | None = None,
           opp_ranges: list[list[tuple[int, int]]] | None = None) -> EquityResult:
    """Probabilidade de a mão do jogador vencer contra `n_opponents` mãos, até o river.

    Por padrão as mãos dos oponentes são aleatórias; com `opp_combos` elas saem dessa faixa de mãos; com
    `opp_ranges` cada oponente tem a sua faixa (combinações repetidas = mais peso), e `n_opponents` é ignorado.
    Empates contam como fração (1/k do pote quando k jogadores empatam).
    `cancel` é uma função opcional chamada de tempos em tempos; se retornar True, a simulação para.
    """
    rng = rng or random.Random()
    table = rank_table()
    known = set(hero) | set(board)
    if opp_ranges is not None:
        n_opponents = len(opp_ranges)
        opp_ranges = [[(a, b) for a, b in r if a not in known and b not in known] or None for r in opp_ranges]
    deck = [c for c in range(52) if c not in known]
    need_board = 5 - len(board)
    need = need_board + 2 * n_opponents
    if opp_combos is not None:
        opp_combos = [(a, b) for a, b in opp_combos if a not in known and b not in known] or None

    prime = [PRIMES[c >> 2] for c in range(52)]
    suit = [c & 3 for c in range(52)]
    bit = [1 << (c >> 2) for c in range(52)]

    def score7(key: int, sm: list[int], hole: tuple[int, int] | list[int]) -> int:
        a, b = hole
        k = key * prime[a] * prime[b]
        # checa flush apenas no naipe que pode tê-lo
        for s in range(4):
            m = sm[s]
            if suit[a] == s:
                m |= bit[a]
            if suit[b] == s:
                m |= bit[b]
            if m.bit_count() >= 5:
                sh = STRAIGHT_HIGH[m]
                if sh >= 0:
                    return (STRAIGHT_FLUSH << 20) | (sh << 16)
                return _pack(FLUSH, _top_bits(m, 5))
        return table[k]

    win_eq = 0.0
    wins = ties = 0
    sq = 0.0
    cats = [0] * 9
    done = 0
    sample = rng.sample
    for it in range(iterations):
        if cancel is not None and (it & 1023) == 0 and cancel():
            break
        if opp_ranges is not None:
            used = set(known)
            hands = []
            for r in opp_ranges:
                if r is None:
                    free = [c for c in deck if c not in used]
                    h = sample(free, 2)
                    used.update(h)
                    hands.append(h)
                else:
                    hands += _pick_range_hands(r, 1, used, rng)
            draw = sample([c for c in deck if c not in used], need_board)
            for h in hands:
                draw += h
        elif opp_combos is None:
            draw = sample(deck, need)
        else:
            used = set(known)
            hands = _pick_range_hands(opp_combos, n_opponents, used, rng)
            draw = sample([c for c in deck if c not in used], need_board)
            for h in hands:
                draw += h
        full = board + draw[:need_board]
        key = 1
        sm = [0, 0, 0, 0]
        counts = [0, 0, 0, 0]
        for c in full:
            key *= prime[c]
            sm[suit[c]] |= bit[c]
            counts[suit[c]] += 1
        # com menos de 3 cartas de um naipe na mesa, ninguém faz flush
        if max(counts) >= 3:
            hs = score7(key, sm, hero)
            opp = [score7(key, sm, draw[i:i + 2]) for i in range(need_board, need, 2)]
        else:
            hs = table[key * prime[hero[0]] * prime[hero[1]]]
            opp = [table[key * prime[draw[i]] * prime[draw[i + 1]]] for i in range(need_board, need, 2)]
        cats[hs >> 20] += 1
        best = max(opp)
        if hs > best:
            wins += 1
            v = 1.0
        elif hs == best:
            ties += 1
            v = 1.0 / (1 + opp.count(best))
        else:
            v = 0.0
        win_eq += v
        sq += v * v
        done += 1
    n = max(done, 1)
    mean = win_eq / n
    var = max(sq / n - mean * mean, 0.0)
    return EquityResult(equity=mean, win=wins / n, tie=ties / n, iterations=done,
                        final_categories=[c / n for c in cats], stderr=(var / n) ** 0.5)


# ---------------------------------------------------------------- distribuição de uma mão

@dataclass
class Deal:
    hero: list[int]
    board: list[int]          # 5 cartas completas (as visíveis são as primeiras `visible`)
    opponents: list[list[int]]
    visible: int              # 0 (pré-flop), 3 (flop) ou 4 (turn)

    @property
    def visible_board(self) -> list[int]:
        return self.board[:self.visible]


def deal(visible: int, n_opponents: int, rng: random.Random | None = None,
         opp_combos: list[tuple[int, int]] | None = None) -> Deal:
    rng = rng or random.Random()
    if opp_combos is not None:
        hero = rng.sample(range(52), 2)
        used = set(hero)
        opps = _pick_range_hands(opp_combos, n_opponents, used, rng)
        board = rng.sample([c for c in range(52) if c not in used], 5)
        return Deal(hero=hero, board=board, opponents=opps, visible=visible)
    cards = rng.sample(range(52), 2 + 5 + 2 * n_opponents)
    return Deal(hero=cards[:2], board=cards[2:7],
                opponents=[cards[7 + 2 * i:9 + 2 * i] for i in range(n_opponents)], visible=visible)


def showdown(d: Deal) -> tuple[list[int], list[int]]:
    """Pontuações finais (jogador, oponentes) com a mesa completa."""
    return evaluate(d.hero + d.board), [evaluate(o + d.board) for o in d.opponents]


def outs(hero: list[int], board: list[int]) -> dict[int, list[int]]:
    """Cartas que melhoram a categoria da mão na próxima carta (flop/turn), agrupadas pela nova categoria."""
    if len(board) not in (3, 4):
        return {}
    cur = evaluate(hero + board) >> 20
    known = set(hero) | set(board)
    res: dict[int, list[int]] = {}
    for c in range(52):
        if c in known:
            continue
        cat = evaluate(hero + board + [c]) >> 20
        # descarta melhorias que estão só na mesa (todos compartilham)
        if cat > cur and cat > board_category(board + [c]):
            res.setdefault(cat, []).append(c)
    return res


def board_category(cards: list[int]) -> int:
    """Categoria formada só pelas cartas da mesa (3 a 5 cartas)."""
    if len(cards) >= 5:
        return evaluate(cards) >> 20
    counts = sorted((sum(1 for c in cards if c >> 2 == r) for r in range(13)), reverse=True)
    if counts[0] == 4:
        return QUADS
    if counts[0] == 3:
        return TRIPS
    if counts[0] == 2:
        return TWO_PAIR if counts[1] == 2 else PAIR
    return HIGH
