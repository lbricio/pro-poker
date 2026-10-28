"""Explicações didáticas, faixas de mãos, tipos de mão e tabelas de referência."""

from __future__ import annotations

import json
from functools import lru_cache
from math import comb
from pathlib import Path

from pokertrainer import engine as E
from pokertrainer.i18n import pick, tr

ASSETS = Path(__file__).resolve().parent / "assets"

# Probabilidade de terminar (7 cartas) com cada categoria — valores exatos conhecidos.
CATEGORY_ODDS_7 = [0.1741, 0.4382, 0.2350, 0.0483, 0.0462, 0.0303, 0.0260, 0.00168, 0.000311]

_CATEGORY_HELP = {
    "pt": [
        "Nenhuma combinação; vale a carta mais alta.",
        "Duas cartas do mesmo valor.",
        "Dois pares diferentes.",
        "Três cartas do mesmo valor.",
        "Cinco valores em sequência (naipes misturados). O Ás pode ser alto ou baixo.",
        "Cinco cartas do mesmo naipe.",
        "Uma trinca + um par.",
        "Quatro cartas do mesmo valor.",
        "Sequência com todas do mesmo naipe. A mais alta (10 a Ás) é o royal flush.",
    ],
    "en": [
        "No combination; the highest card plays.",
        "Two cards of the same rank.",
        "Two different pairs.",
        "Three cards of the same rank.",
        "Five ranks in a row (mixed suits). The Ace can be high or low.",
        "Five cards of the same suit.",
        "Three of a kind + a pair.",
        "Four cards of the same rank.",
        "A straight with all cards of the same suit. The highest (10 to Ace) is the royal flush.",
    ],
}


def category_help(cat: int) -> str:
    return pick(_CATEGORY_HELP["pt"], _CATEGORY_HELP["en"])[cat]
CATEGORY_EXAMPLE = [
    "As Jd 8c 5h 3s", "Kh Kc 9d 6s 2c", "Qs Qd 7h 7c 3d", "8h 8d 8s Kc 4d", "9c 8d 7h 6s 5c",
    "Ah Jh 8h 4h 2h", "Td Th Ts 4c 4s", "6c 6d 6h 6s Kd", "9s 8s 7s 6s 5s",
]


# ---------------------------------------------------------------- tabelas

@lru_cache(maxsize=1)
def preflop_table() -> dict[int, dict[str, float]] | None:
    f = ASSETS / "preflop_equity.json"
    if not f.exists():
        return None
    data = json.loads(f.read_text())
    return {int(k): v for k, v in data["equity"].items()}


def preflop_equity(label: str, n_opp: int) -> float | None:
    t = preflop_table()
    if not t or n_opp not in t:
        return None
    return t[n_opp].get(label)


def preflop_rank(label: str, n_opp: int) -> int | None:
    """Posição (1 = melhor) da mão entre as 169 mãos iniciais."""
    t = preflop_table()
    if not t or n_opp not in t:
        return None
    order = sorted(t[n_opp], key=t[n_opp].get, reverse=True)
    return order.index(label) + 1


def hit_chance(outs: int, unseen: int, cards_to_come: int) -> float:
    """Chance de sair pelo menos um out nas próximas cartas."""
    if outs <= 0:
        return 0.0
    return 1 - comb(unseen - outs, cards_to_come) / comb(unseen, cards_to_come)


def common_draws() -> list[tuple[str, int]]:
    return [
        (tr("Flush + sequência aberta", "Flush + open-ended straight"), 15),
        (tr("Flush draw (4 do mesmo naipe)", "Flush draw (4 of a suit)"), 9),
        (tr("Sequência aberta (2 pontas)", "Open-ended straight draw"), 8),
        (tr("Duas overcards (cartas acima da mesa)", "Two overcards (above the board)"), 6),
        (tr("Par → trinca ou dois pares", "Pair → trips or two pair"), 5),
        (tr("Gutshot (sequência pela metade)", "Gutshot (inside straight draw)"), 4),
        (tr("Par na mão → trinca (set)", "Pocket pair → set"), 2),
    ]


# ---------------------------------------------------------------- explicações

def street(n: int) -> str:
    return pick({3: "no flop", 4: "no turn", 5: "no river"}, {3: "on the flop", 4: "on the turn", 5: "on the river"})[n]


def _hand_at(hole: list[int], board: list[int]) -> int | None:
    return E.evaluate(hole + board) if len(board) >= 3 else None


def runout_story(d: E.Deal, eq: E.EquityResult, hero_score: int, opp_scores: list[int]) -> list[str]:
    """Narra o que aconteceu nas cartas seguintes e compara com a probabilidade."""
    tips = []
    # evolução da sua mão
    prev = None
    steps = []
    for n in range(max(3, d.visible), 6):
        s = _hand_at(d.hero, d.board[:n])
        cat = s >> 20
        # melhoras que vêm só da mesa (servem a todos) não contam
        if prev is not None and cat <= E.board_category(d.board[:n]):
            cat = prev
        if prev is None or cat > prev:
            steps.append(f"{E.describe(s)} {street(n)}" if n > d.visible or d.visible == 0 else E.describe(s))
        prev = cat
    if len(steps) > 1 or d.visible == 0:
        tips.append(tr("Sua mão: ", "Your hand: ") + " → ".join(steps) + ".")

    best = max([hero_score] + opp_scores)
    winners = [i for i, s in enumerate(opp_scores) if s == best]
    if hero_score == best and not winners:
        tips.append(tr(f"Você venceu com {E.describe(hero_score).lower()}.",
                       f"You won with {E.describe(hero_score).lower()}."))
    elif hero_score == best:
        tips.append(tr(f"Empate: você dividiu o pote com {E.describe(hero_score).lower()}.",
                       f"Tie: you split the pot with {E.describe(hero_score).lower()}."))
    else:
        w = winners[0]
        # em que rua o vencedor passou à frente de você?
        turned = None
        for n in range(max(3, d.visible), 6):
            hs, os_ = _hand_at(d.hero, d.board[:n]), _hand_at(d.opponents[w], d.board[:n])
            if os_ > hs:
                turned = n
                break
        when = ""
        if turned is not None and turned > max(3, d.visible):
            when = tr(f" — ele passou à sua frente {street(turned)}", f" — they took the lead {street(turned)}")
        elif turned is not None and d.visible >= 3:
            when = tr(" — ele já estava na frente quando você decidiu", " — they were already ahead when you decided")
        tips.append(tr(f"Oponente {w + 1} venceu com {E.describe(best).lower()}{when}.",
                       f"Opponent {w + 1} won with {E.describe(best).lower()}{when}."))

    won = hero_score == best
    if eq.equity >= 0.5 and not won:
        tips.append(tr(f"Você era favorito ({eq.equity:.0%}) e perdeu. Isso acontece ~{1 - eq.equity:.0%} das "
                       "vezes: foi azar, não um erro de leitura.",
                       f"You were the favorite ({eq.equity:.0%}) and lost. That happens ~{1 - eq.equity:.0%} of "
                       "the time: bad luck, not a misread."))
    elif won and eq.equity < 0.8 / (len(opp_scores) + 1):
        tips.append(tr(f"Você venceu com só {eq.equity:.0%} de chance: sorte. A longo prazo, esta mão perde "
                       f"~{1 - eq.equity:.0%} das vezes.",
                       f"You won with only a {eq.equity:.0%} chance: luck. In the long run this hand loses "
                       f"~{1 - eq.equity:.0%} of the time."))
    return tips


def explain(d: E.Deal, eq: E.EquityResult, n_opp: int) -> list[str]:
    """Pontos didáticos (HTML curto) sobre a mão da rodada."""
    tips: list[str] = []
    fair = 1 / (n_opp + 1)
    rel = eq.equity / fair
    if rel >= 1.6:
        strength = tr("muito acima", "well above")
    elif rel >= 1.15:
        strength = tr("acima", "above")
    elif rel >= 0.85:
        strength = tr("perto", "close to")
    else:
        strength = tr("abaixo", "below")
    tips.append(tr(f"Com {n_opp + 1} jogadores, a fatia “justa” de cada um é <b>{fair:.0%}</b>. "
                   f"Sua mão está <b>{strength}</b> dessa média.",
                   f"With {n_opp + 1} players, each one's “fair” share is <b>{fair:.0%}</b>. "
                   f"Your hand is <b>{strength}</b> that average."))

    if d.visible == 0:
        a, b = d.hero
        label = E.starting_hand_label(a, b)
        rank = preflop_rank(label, n_opp)
        if rank:
            pl = "s" if n_opp > 1 else ""
            tips.append(tr(f"<b>{label}</b> é a {rank}ª melhor das 169 mãos iniciais contra {n_opp} oponente{pl}.",
                           f"<b>{label}</b> is #{rank} of the 169 starting hands against {n_opp} opponent{pl}."))
        r1, r2 = sorted((a >> 2, b >> 2), reverse=True)
        if r1 == r2:
            tips.append(tr("Pares na mão já começam com uma combinação feita; contra 1 oponente, até 22 é "
                           "levemente favorito (~50%).",
                           "Pocket pairs start with a made hand; against 1 opponent even 22 is a slight "
                           "favorite (~50%)."))
        else:
            if label.endswith("s"):
                tips.append(tr("Cartas do mesmo naipe valem só ~2–4 pontos a mais que as de naipes diferentes.",
                               "Suited cards are worth only ~2–4 points more than offsuit ones."))
            gap = r1 - r2
            if gap == 1:
                tips.append(tr("Cartas conectadas formam mais sequências.", "Connected cards make more straights."))
            if r1 == 12:
                tips.append(tr("Ter um Ás ajuda muito: se nada se formar, sua carta alta vence com frequência.",
                               "Holding an Ace helps a lot: if nothing comes, your high card often wins."))
            if r1 < 8:
                tips.append(tr("Duas cartas baixas e sem par perdem para quase qualquer par ou carta alta.",
                               "Two low unpaired cards lose to almost any pair or high card."))
        if n_opp > 1:
            hu = preflop_equity(label, 1)
            if hu is not None:
                tips.append(tr(f"Contra 1 oponente esta mão teria <b>{hu:.0%}</b>: cada oponente a mais "
                               "reduz sua chance.",
                               f"Against 1 opponent this hand would have <b>{hu:.0%}</b>: every extra opponent "
                               "lowers your chance."))
    else:
        board = d.visible_board
        cur = E.describe_cards(d.hero + board)
        tips.append(tr(f"Sua mão agora: <b>{cur}</b>.", f"Your hand now: <b>{cur}</b>."))
        o = E.outs(d.hero, board)
        total = sorted({c for cs in o.values() for c in cs})
        if total:
            parts = ", ".join(f"{E.category_name(k).lower()} ({len(v)})" for k, v in
                              sorted(o.items(), reverse=True))
            n = len(total)
            if d.visible == 3:
                approx, exact = n * 4, hit_chance(n, 47, 2)
                rule = tr("regra do 4", "rule of 4")
            else:
                approx, exact = n * 2, hit_chance(n, 46, 1)
                rule = tr("regra do 2", "rule of 2")
            tips.append(tr(f"Você tem <b>{n} outs</b> para melhorar: {parts}. Pela {rule}: ~{approx}% "
                           f"(exato: {exact:.0%}).",
                           f"You have <b>{n} outs</b> to improve: {parts}. By the {rule}: ~{approx}% "
                           f"(exact: {exact:.0%})."))
            tips.append(tr("Atenção: melhorar não garante vencer — o oponente também pode melhorar, e alguns outs "
                           "podem completar uma mão maior para ele.",
                           "Careful: improving doesn't guarantee a win — opponents can improve too, and some outs "
                           "may complete a bigger hand for them."))
        else:
            tips.append(tr("Nenhuma carta melhora a categoria da sua mão: você depende do que já tem.",
                           "No card improves your hand's category: you rely on what you already have."))
        suits = [c & 3 for c in board]
        if max(suits.count(s) for s in range(4)) >= 3:
            tips.append(tr("Há 3+ cartas do mesmo naipe na mesa: flush possível para os oponentes.",
                           "There are 3+ cards of one suit on the board: a flush is possible for opponents."))
        ranks = [c >> 2 for c in board]
        if len(set(ranks)) < len(ranks):
            tips.append(tr("A mesa tem par: full house e trinca ficam mais prováveis para todos.",
                           "The board is paired: full houses and trips become more likely for everyone."))
    if n_opp >= 3:
        tips.append(tr("Com muitos oponentes, mãos que dependem só de carta alta perdem valor; "
                       "pares altos e projetos fortes ganham.",
                       "With many opponents, hands that rely on high card alone lose value; "
                       "high pairs and strong draws gain."))
    return tips


# ---------------------------------------------------------------- faixas de mãos (ranges)

RANGES = [0, 100, 50, 30, 15, 8]   # 0 = conforme a ação (realista); senão, top X% fixo (100 = qualquer mão)


def range_name(pct: int, short: bool = False) -> str:
    if pct <= 0:
        return tr("Pela ação", "By action") if short else tr("Conforme a ação (realista)",
                                                               "Based on their action (realistic)")
    if pct >= 100:
        return tr("Qualquer mão", "Any hand") if short else tr("Qualquer mão (aleatória)", "Any hand (random)")
    if short:
        return f"Top {pct}%"
    desc = {50: tr("jogadores soltos", "loose players"), 30: tr("jogo médio", "average player"),
            15: tr("jogadores sólidos", "solid players"), 8: tr("só mãos premium", "premium hands only")}
    return f"Top {pct}% — {desc.get(pct, '')}"


def _combo_weight(label: str) -> int:
    return 6 if len(label) == 2 else 4 if label.endswith("s") else 12


@lru_cache(maxsize=1)
def hand_order() -> list[str]:
    """As 169 mãos da melhor para a pior: média da força contra 1 e contra 3 oponentes (relativa à fatia justa)."""
    t = preflop_table()
    if not t:
        return []
    return sorted(t[1], key=lambda lab: t[1][lab] / 0.5 + t[3][lab] / 0.25, reverse=True)


@lru_cache(maxsize=None)
def range_labels(pct: int) -> frozenset[str]:
    order = hand_order()
    if pct >= 100 or not order:
        return frozenset(order)
    target, acc, out = pct / 100 * 1326, 0, []
    for lab in order:
        if acc >= target:
            break
        out.append(lab)
        acc += _combo_weight(lab)
    return frozenset(out)


@lru_cache(maxsize=None)
def range_combos(pct: int) -> list[tuple[int, int]] | None:
    """Combinações de cartas da faixa; None = mãos aleatórias."""
    if pct >= 100:
        return None
    return E.label_combos(range_labels(pct))


# ---------------------------------------------------------------- tipos de mão (para estatísticas)

HAND_TYPES = {
    "pf_pair_hi": ("Pares altos (TT+)", "High pairs (TT+)"),
    "pf_pair_lo": ("Pares baixos (22–99)", "Low pairs (22–99)"),
    "pf_ace": ("Ás + outra carta", "Ace + another card"),
    "pf_broadway": ("Duas cartas altas (T–K)", "Two high cards (T–K)"),
    "pf_suited": ("Mesmo naipe / conectadas", "Suited / connected"),
    "pf_other": ("Mãos fracas", "Weak hands"),
    "pp_strong": ("Dois pares ou melhor", "Two pair or better"),
    "pp_pair": ("Um par", "One pair"),
    "pp_draw": ("Projeto (8+ outs)", "Draw (8+ outs)"),
    "pp_weak": ("Nada / projeto fraco", "Nothing / weak draw"),
}


def hand_type_name(key: str) -> str:
    return tr(*HAND_TYPES.get(key, (key, key)))


def hand_type(d: E.Deal) -> str:
    a, b = d.hero
    r1, r2 = sorted((a >> 2, b >> 2), reverse=True)
    if d.visible == 0:
        if r1 == r2:
            return "pf_pair_hi" if r1 >= 8 else "pf_pair_lo"
        if r1 == 12:
            return "pf_ace"
        if r2 >= 8:
            return "pf_broadway"
        if (a & 3) == (b & 3) or r1 - r2 == 1:
            return "pf_suited"
        return "pf_other"
    board = d.visible_board
    cat = E.evaluate(d.hero + board) >> 20
    own = cat > E.board_category(board)
    if own and cat >= E.TWO_PAIR:
        return "pp_strong"
    if own and cat == E.PAIR:
        return "pp_pair"
    n_outs = len({c for cs in E.outs(d.hero, board).values() for c in cs})
    return "pp_draw" if n_outs >= 8 else "pp_weak"


def range_tips(d: E.Deal, eq: E.EquityResult, pct: int) -> list[str]:
    """Comparação com mãos aleatórias quando os oponentes jogam uma faixa."""
    if pct >= 100:
        return []
    tips = []
    if eq.vs_random is not None:
        diff = (eq.equity - eq.vs_random) * 100
        tips.append(tr(f"Contra mãos aleatórias esta mão teria <b>{eq.vs_random:.0%}</b>; contra o top {pct}% tem "
                       f"<b>{eq.equity:.0%}</b> ({diff:+.0f} pontos).",
                       f"Against random hands this hand would have <b>{eq.vs_random:.0%}</b>; against the top "
                       f"{pct}% it has <b>{eq.equity:.0%}</b> ({diff:+.0f} points)."))
    if d.visible == 0:
        tips.append(tr("Faixas fortes são cheias de pares altos e Ases: mãos como Ás com kicker fraco ficam "
                       "<b>dominadas</b> (perdem para o mesmo Ás com kicker melhor).",
                       "Strong ranges are full of high pairs and Aces: hands like an Ace with a weak kicker get "
                       "<b>dominated</b> (they lose to the same Ace with a better kicker)."))
    else:
        tips.append(tr("Jogadores que só entram com mãos boas acertam mais pares altos na mesa: um par médio vale "
                       "bem menos do que contra mãos aleatórias.",
                       "Players who only play good hands hit more top pairs: a middle pair is worth much less "
                       "than against random hands."))
    return tips
