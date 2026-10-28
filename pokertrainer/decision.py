"""Treino de decisões: situações de aposta com posição e stacks, a melhor jogada e a explicação.

A chance da sua mão é calculada contra as mãos com que os oponentes fariam o que fizeram (faixas em
`pokertrainer.ranges`), não contra cartas aleatórias. A nota usa:
- antes do flop: a tabela de aberturas por posição; contra um aumento, a chance contra a faixa de quem aumentou,
  o preço e a posição (fora de posição você realiza menos da sua chance);
- depois do flop: pagar se a chance contra quem apostou cobre o preço (com odds implícitas para projetos com stack
  fundo); apostar/aumentar por valor se você está à frente das mãos que PAGAM; semiblefe com projetos fortes;
- o tamanho da aposta/aumento escolhido (secundário: o tamanho errado vira "aceitável").
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from pokertrainer import engine as E
from pokertrainer import ranges as R
from pokertrainer.i18n import tr

FOLD, CHECK, CALL, BET, RAISE = "fold", "check", "call", "bet", "raise"
SB, BB = 5, 10
MARGIN = 0.02           # perto do limite, as duas jogadas valem quase o mesmo
OOP_TAX = 0.04          # fora de posição você realiza menos da sua chance
IMPLIED = 0.05          # odds implícitas de um projeto forte com stack fundo
STACKS_BB = [40, 60, 100, 100, 100, 150]


def action_name(a: str) -> str:
    return tr({FOLD: "Desistir", CHECK: "Passar", CALL: "Pagar", BET: "Apostar", RAISE: "Aumentar"}[a],
              {FOLD: "Fold", CHECK: "Check", CALL: "Call", BET: "Bet", RAISE: "Raise"}[a])


def _r5(x: float) -> int:
    return max(5, int(round(x / 5)) * 5)


@dataclass
class Spot:
    """A situação na sua vez."""
    street: int                 # cartas visíveis na mesa: 0, 3, 4 ou 5
    pot: int                    # pote antes da sua decisão (inclui apostas da rua)
    bet: int                    # quanto você precisa pôr para pagar (0 = ninguém apostou)
    callers: int                # oponentes que pagaram a aposta/aumento depois de quem apostou
    kind: str                   # open | vs_raise | limped | check | bet
    hero_bet: int               # tamanho padrão da sua aposta/aumento (total na rua)
    hero_pos: str = ""
    opp_pos: list[str] = field(default_factory=list)
    stack: int = 1000           # stack efetivo atrás (antes da decisão)
    in_position: bool = True    # você age por último depois do flop
    pre: list[tuple[int, int]] = field(default_factory=list)   # faixa pré-flop de cada oponente
    acts: list[str] = field(default_factory=list)              # ação de cada oponente nesta rua
    hero_pre: tuple[int, int] = (0, 100)                         # sua faixa pré-flop (para dar cartas coerentes)
    sizes: list[tuple[str, int]] = field(default_factory=list)  # opções de tamanho (rótulo, total)

    # ------------------------------------------------------------ contas
    @property
    def facing_bet(self) -> bool:
        return self.bet > 0

    @property
    def to_call(self) -> int:
        return self.bet

    @property
    def final_pot(self) -> int:
        """Pote se você pagar."""
        return self.pot + self.bet

    @property
    def need(self) -> float:
        return self.bet / self.final_pot if self.bet else 0.0

    def ev_call(self, equity: float) -> float:
        return equity * self.final_pot - self.to_call

    @property
    def spr(self) -> float:
        return self.stack / max(1, self.pot)

    @property
    def can_fold(self) -> bool:
        return self.facing_bet and self.kind != "limped"

    def actions(self) -> tuple[str, str, str]:
        """(desistir, passiva, agressiva)."""
        if self.kind == "limped":
            return (FOLD, CHECK, RAISE)
        if self.kind == "open":
            return (FOLD, CALL, RAISE)
        return (FOLD, CALL, RAISE) if self.facing_bet else (FOLD, CHECK, BET)

    def to_list(self) -> list:
        return [self.street, self.pot, self.bet, self.callers, self.kind, self.hero_bet, self.hero_pos,
                list(self.opp_pos), self.stack, self.in_position, [list(x) for x in self.pre], list(self.acts),
                list(self.hero_pre), [list(x) for x in self.sizes]]

    @classmethod
    def from_list(cls, v: list) -> Spot:
        if len(v) <= 6:   # histórico antigo (sem posição): situação genérica
            street, pot, bet, callers, kind, hero_bet = v
            return cls(street, pot, bet, callers, "bet" if bet else "check", hero_bet)
        sp = cls(*v[:6], v[6], list(v[7]), v[8], v[9], [tuple(x) for x in v[10]], list(v[11]), tuple(v[12]),
                 [tuple(x) for x in v[13]])
        return sp


# ---------------------------------------------------------------- geração das situações

def _positions_behind(k: int) -> list[str]:
    """Posições de quem age depois de alguém com `k` jogadores atrás (pré-flop)."""
    order = ["UTG", "UTG+1", "UTG+2", "MP", "HJ", "CO", "BTN", "SB", "BB"]
    return order[len(order) - k:]


def make_spot(rng: random.Random, street: int, n_opp: int) -> Spot:
    stack_bb = rng.choice(STACKS_BB)
    if street == 0:
        return _preflop_spot(rng, n_opp, stack_bb)
    return _postflop_spot(rng, street, n_opp, stack_bb)


def _preflop_spot(rng: random.Random, n_opp: int, stack_bb: int) -> Spot:
    kind = rng.choices(["open", "vs_raise", "limped"], [0.4, 0.45, 0.15])[0]
    stack = stack_bb * BB
    if kind == "open":
        k = min(n_opp, 8)
        pos = R.POS_BY_BEHIND[k]
        opp_pos = _positions_behind(k)
        to_call = SB if pos == "SB" else BB
        sizes = [(bb(22), 22), (bb(25), 25), (bb(30), 30)]
        if pos == "SB":
            sizes = [(bb(30), 30), (bb(35), 35)]
        return Spot(0, SB + BB, to_call, 0, "open", sizes[1][1] if pos != "SB" else 30, pos, opp_pos, stack - (
            SB if pos == "SB" else 0), True, [R.ANY] * len(opp_pos), ["wait"] * len(opp_pos), R.ANY, sizes)
    if kind == "limped":
        # você é o big blind; `n_opp` jogadores só pagaram (o último pode ser o small blind completando)
        opp_pos = _positions_behind(n_opp + 1)[:-1][-n_opp:] if n_opp <= 8 else ["UTG"] * n_opp
        pot = BB + BB * n_opp + (SB if "SB" not in opp_pos else 0)
        iso = 3 * BB + BB * n_opp
        sizes = [(bb(iso), iso), (bb(iso + BB), iso + BB)]
        return Spot(0, pot, 0, n_opp - 1, "limped", iso, "BB", opp_pos, stack - BB, False,
                    [R.LIMP_BAND] * n_opp, ["limp"] * n_opp, R.ANY, sizes)
    # vs_raise: alguém aumentou, outros pagaram; você está no botão (blinds desistiram) ou no big blind
    hero_pos = rng.choice(["BTN", "BB"])
    earlier = ["UTG", "UTG+1", "UTG+2", "MP", "HJ", "CO"]
    raiser = rng.choice(earlier[: max(1, len(earlier) - (n_opp - 1))])
    after = earlier[earlier.index(raiser) + 1:] + (["BTN", "SB"] if hero_pos == "BB" else [])
    callers = sorted(rng.sample(after, min(n_opp - 1, len(after))), key=lambda p: R.SEAT_ORDER.index(p))
    while len(callers) < n_opp - 1:
        callers.append("MP")
    r = rng.choice([25, 25, 30, 30, 35])
    dead = SB + BB if hero_pos == "BTN" else SB
    pot = dead + r * (1 + len(callers)) + (BB if hero_pos == "BB" else 0)
    to_call = r - (BB if hero_pos == "BB" else 0)
    ip = hero_pos == "BTN"
    three = (3 if ip else 4) * r + r * len(callers)
    sizes = [(bb(three), three), (bb(three + r), three + r)]
    pre = [(0, R.open_pct(raiser))] + [R.CALL_BAND] * len(callers)
    acts = ["raise"] + ["call"] * len(callers)
    return Spot(0, pot, to_call, len(callers), "vs_raise", three, hero_pos, [raiser] + callers,
                stack - (BB if hero_pos == "BB" else 0), ip, pre, acts, R.ANY, sizes)


def _postflop_spot(rng: random.Random, street: int, n_opp: int, stack_bb: int) -> Spot:
    # pré-flop: um aumento de 2,5 bb pago pelos demais; quem aumentou foi você ou o oponente 1
    hero_raised = rng.random() < 0.45
    raise_bb = 2.5
    pot_bb = raise_bb * (n_opp + 1) + 1.5 - 1.0   # blinds mortos incluídos de forma simples
    stack = stack_bb - raise_bb
    # ruas anteriores: às vezes houve aposta (½–⅔ do pote) paga por todos
    for _ in range({3: 0, 4: 1, 5: 2}[street]):
        # multiway quase sempre vai passando; apostas pagas por todos só com poucos jogadores
        if n_opp <= 2 and rng.random() < 0.5:
            b = pot_bb * rng.choice([0.5, 0.66])
            b = min(b, stack)
            pot_bb += b * (n_opp + 1)
            stack -= b
    ip = rng.random() < 0.5
    hero_pos = "BTN" if ip else "BB"
    opp_pos = ["BB" if ip else "CO"] + (["MP", "HJ", "UTG", "UTG+1", "UTG+2", "SB", "CO", "BTN"][:n_opp - 1])
    pre = ([R.CALL_BAND] * n_opp) if hero_raised else ([(0, R.open_pct(opp_pos[0]))] + [R.CALL_BAND] * (n_opp - 1))
    hero_pre = (0, R.open_pct(hero_pos if ip else "CO")) if hero_raised else R.CALL_BAND
    pot = _r5(pot_bb * BB)
    stack_c = max(BB, _r5(stack * BB))
    facing = rng.random() < 0.5
    if not facing:
        sizes = [("⅓", _r5(pot / 3)), ("½", _r5(pot / 2)), ("⅔", _r5(pot * 2 / 3)), (tr("Pote", "Pot"), pot)]
        sizes = [(lab, min(v, stack_c)) for lab, v in sizes]
        acts = ["check"] * n_opp if ip else ["wait"] * n_opp
        return Spot(street, pot, 0, 0, "check", sizes[2][1], hero_pos, opp_pos, stack_c, ip, pre, acts,
                    hero_pre, sizes)
    frac = rng.choice([0.33, 0.5, 0.66, 0.75, 1.0])
    bet = min(_r5(pot * frac), stack_c)
    callers = n_opp - 1
    pot_now = pot + bet * (1 + callers)
    sizes = [(num(2.5) + "×", min(stack_c, _r5(bet * 2.5))), ("3×", min(stack_c, bet * 3)), ("All-in", stack_c)]
    acts = ["bet"] + ["call"] * callers
    return Spot(street, pot_now, bet, callers, "bet", sizes[1][1], hero_pos, opp_pos, stack_c, ip, pre, acts,
                hero_pre, sizes)


# ---------------------------------------------------------------- cartas coerentes com a situação

def deal_hero_board(spot: Spot, rng: random.Random, n_opp: int) -> E.Deal:
    """Suas cartas (da sua faixa, se a situação a define) e a mesa completa; os oponentes vêm depois."""
    combos = R.band_combos(*spot.hero_pre) if spot.street else None
    hero = list(rng.choice(combos)) if combos else rng.sample(range(52), 2)
    board = rng.sample([c for c in range(52) if c not in hero], 5)
    return E.Deal(hero=hero, board=board, opponents=[], visible=spot.street)


def opponent_ranges(spot: Spot, deal: E.Deal, after: str | None = None,
                    fixed_pct: int | None = None) -> list[list[tuple[int, int]]]:
    """Faixa ponderada de cada oponente. `after`: condiciona também à reação à sua jogada ("call" = pagam sua
    aposta; "call_raise" = pagam seu aumento). `fixed_pct`: faixa fixa (top X%) ignorando a ação."""
    board = deal.visible_board
    known = set(deal.hero) | set(board)
    out = []
    n = max(len(spot.pre), len(deal.opponents) or 0, 1)
    for k in range(n):
        if fixed_pct is not None:
            base = R.band_combos(0, fixed_pct)
            acts: tuple[str, ...] = ()
        else:
            base = R.band_combos(*(spot.pre[k] if k < len(spot.pre) else R.ANY))
            a = spot.acts[k] if k < len(spot.acts) else ""
            acts = (a,) if a in ("bet", "call", "check") else ()
        if after and len(board) >= 3:
            acts = acts + (after,)
        r = R.weighted(base, board, known, acts)
        out.append(r or list(R.band_combos(0, 100)))
    return out


def deal_opponents(spot: Spot, deal: E.Deal, rng: random.Random, n_opp: int, fixed_pct: int | None = None) -> E.Deal:
    """Sorteia as cartas de cada oponente da faixa dele (sem repetir cartas) e completa a mesa."""
    while len(spot.pre) < n_opp:
        spot.pre.append(R.ANY)
        spot.acts.append("wait")
    tmp = E.Deal(deal.hero, deal.board, [], deal.visible)
    ranges = opponent_ranges(spot, tmp, fixed_pct=fixed_pct)
    used = set(deal.hero) | set(deal.visible_board)
    opps = []
    for r in ranges[:n_opp]:
        free = [c for c in r if c[0] not in used and c[1] not in used]
        if not free:
            free = [(a, b) for a in range(52) for b in range(a + 1, 52) if a not in used and b not in used]
        a, b = rng.choice(free)
        used |= {a, b}
        opps.append([a, b])
    rest = [c for c in range(52) if c not in used]
    rng.shuffle(rest)
    board = deal.visible_board + rest[:5 - deal.visible]
    return E.Deal(hero=deal.hero, board=board, opponents=opps, visible=deal.visible)


# ---------------------------------------------------------------- avaliação

def value_threshold(n_opp: int) -> float:
    """Chance mínima contra as mãos que PAGAM para apostar/aumentar por valor."""
    return 0.5 if n_opp <= 1 else 0.42


@dataclass
class Verdict:
    action: str             # o que você fez
    best: str               # a melhor jogada
    scores: dict[str, int]  # pontos de cada jogada possível (100 = melhor)
    reason: str             # chave da explicação
    equity: float           # chance contra as faixas atuais
    need: float             # preço para pagar (0 se ninguém apostou)
    value: float            # chance contra quem paga a sua aposta/aumento
    outs: int
    need_eff: float = 0.0   # preço ajustado (posição, odds implícitas)
    size: int = 0           # tamanho escolhido
    size_ok: bool = True
    size_tip: str = ""
    hero_class: int = R.AIR
    pct: float = 100.0      # top % da sua mão (pré-flop)

    @property
    def points(self) -> int:
        p = self.scores.get(self.action, 0)
        if p >= 100 and not self.size_ok:
            p = 70
        return p

    @property
    def quality(self) -> str:
        p = self.points
        return "best" if p >= 100 else "ok" if p >= 40 else "mistake"

    @property
    def good(self) -> bool:
        return self.quality != "mistake"


def _preflop_verdict(spot: Spot, eq: float, eq_call: float, pct: float, n_opp: int) -> tuple[dict, str, float]:
    if spot.kind == "open":
        limit = R.open_pct(spot.hero_pos)
        if pct <= limit - 2:
            return {RAISE: 100, CALL: 10, FOLD: 0}, "open_raise", 0.0
        if pct <= limit + 2:
            return {RAISE: 100, FOLD: 70, CALL: 10}, "open_border", 0.0
        return {FOLD: 100, CALL: 0, RAISE: 0}, "open_fold", 0.0
    if spot.kind == "limped":
        fair = 1 / (n_opp + 1)
        if eq >= fair + (1 - fair) * 0.2 or pct <= 12:
            return {RAISE: 100, CHECK: 40, FOLD: 0}, "iso_raise", 0.0
        return {CHECK: 100, RAISE: 0, FOLD: 0}, "limp_check", 0.0
    # vs_raise
    need_eff = spot.need + (0.0 if spot.in_position else OOP_TAX)
    deep = spot.stack >= 60 * BB
    v = 0.55 if n_opp <= 1 else 1 / (n_opp + 1) + (1 - 1 / (n_opp + 1)) * 0.15
    if eq_call >= v or pct <= R.THREEBET_PCT:
        return {RAISE: 100, CALL: 50, FOLD: 0}, "threebet_value", need_eff
    if eq >= need_eff + MARGIN:
        return {CALL: 100, RAISE: 0, FOLD: 0}, "call_raise", need_eff
    if eq >= need_eff - MARGIN:
        return {CALL: 100, FOLD: 80, RAISE: 0} if eq >= need_eff else {FOLD: 100, CALL: 70, RAISE: 0}, \
            "borderline", need_eff
    if deep and spot.in_position and pct <= 45 and eq >= need_eff - 0.06:
        return {FOLD: 100, CALL: 60, RAISE: 0}, "implied_pf", need_eff
    return {FOLD: 100, CALL: 0, RAISE: 0}, "fold_price", need_eff


def evaluate(spot: Spot, equity: float, n_opp: int, outs: int, action: str | None = None,
             eq_call: float | None = None, hero: list[int] | None = None, board: list[int] | None = None,
             size: int | None = None) -> Verdict:
    """Pontua as três jogadas. `equity`: contra as faixas atuais; `eq_call`: contra quem paga a sua
    aposta/aumento. `action`: o que você fez (None = só a análise); `size`: o tamanho que você escolheu."""
    eq_call = equity if eq_call is None else eq_call
    hc = R.hand_class(hero, board) if hero and board and len(board) >= 3 else R.AIR
    pct = R.hand_pct(hero) if hero else 100.0
    v_thr = value_threshold(n_opp)
    draw = hc == R.DRAW and spot.street in (3, 4)
    need_eff = 0.0
    if spot.street == 0:
        scores, reason, need_eff = _preflop_verdict(spot, equity, eq_call, pct, n_opp)
    elif not spot.facing_bet:
        if eq_call >= v_thr:
            scores, reason = {BET: 100, CHECK: 40, FOLD: 0}, "bet_value"
        elif draw:
            scores, reason = {BET: 100, CHECK: 60, FOLD: 0}, "semibluff"
        elif spot.street == 5 and hc == R.AIR and spot.in_position and n_opp == 1:
            scores, reason = {CHECK: 100, BET: 40, FOLD: 0}, "river_bluff"
        else:
            scores, reason = {CHECK: 100, BET: 0, FOLD: 0}, "check_weak"
    else:
        need_eff = spot.need
        if not spot.in_position and spot.street in (3, 4):
            need_eff += OOP_TAX
        implied = draw and spot.stack - spot.to_call >= 3 * spot.final_pot
        if implied:
            need_eff -= IMPLIED
        if eq_call >= v_thr and equity >= spot.need:
            scores, reason = {RAISE: 100, CALL: 50, FOLD: 0}, "raise_value"
        elif equity >= need_eff + MARGIN:
            scores, reason = {CALL: 100, RAISE: 50 if draw else 0, FOLD: 0}, ("call_implied" if implied and
                                                                             equity < spot.need else "call_price")
        elif equity >= need_eff - MARGIN:
            scores = {CALL: 100, FOLD: 70, RAISE: 0} if equity >= need_eff else {FOLD: 100, CALL: 70, RAISE: 0}
            reason = "borderline"
        elif draw:
            scores, reason = {FOLD: 100, RAISE: 50, CALL: 0}, "fold_draw"
        else:
            scores, reason = {FOLD: 100, CALL: 0, RAISE: 0}, "fold_price"
    best = max(scores, key=scores.get)
    vd = Verdict(action or "", best, scores, reason, equity, spot.need, eq_call, outs, need_eff,
                 hero_class=hc, pct=pct)
    if action in (BET, RAISE) and size and spot.sizes and scores.get(action, 0) >= 100:
        good, tip = _size_ok(spot, vd, size)
        vd.size, vd.size_ok, vd.size_tip = size, good, tip
    elif size:
        vd.size = size
    return vd


def _size_ok(spot: Spot, v: Verdict, size: int) -> tuple[bool, str]:
    """O tamanho escolhido combina com a mão? (só afina a nota de uma jogada certa)"""
    pot = spot.pot
    if spot.street == 0:
        if spot.kind == "open":
            ok = size <= spot.sizes[-1][1]
            return ok, "" if ok else tr("Para abrir, 2,2–3 bb bastam.", "To open, 2.2–3 bb is enough.")
        if spot.kind == "vs_raise":
            want = spot.sizes[0][1] if spot.in_position else spot.sizes[-1][1]
            ok = size == want or (spot.in_position and size <= spot.sizes[-1][1])
            return ok, "" if ok else tr("Fora de posição, re-aumente um pouco mais (cerca de 4× o aumento).",
                                        "Out of position, re-raise a bit bigger (about 4× the raise).")
        return True, ""
    frac = size / max(1, pot) if not spot.facing_bet else size / max(1, spot.bet)
    if spot.facing_bet:
        if spot.spr <= 2 and v.hero_class == R.STRONG:
            ok = size >= spot.stack
            return ok, "" if ok else tr("Com o stack curto em relação ao pote, vá all-in com a mão forte.",
                                        "With a short stack relative to the pot, just go all-in with the strong hand.")
        ok = 2.2 <= frac <= 3.5 or size >= spot.stack
        return ok, "" if ok else tr("Um aumento de 2,5–3× a aposta costuma ser o tamanho certo.",
                                    "A raise of 2.5–3× the bet is usually the right size.")
    if v.reason == "bet_value":
        if v.hero_class == R.STRONG:
            ok = frac >= 0.6
            tip = tr("Com mão muito forte, aposte grande (⅔ do pote ou mais): quem paga, paga mais.",
                     "With a very strong hand, bet big (⅔ pot or more): whoever calls pays more.")
        else:
            ok = 0.3 <= frac <= 0.75
            tip = tr("Com valor fino (par alto), prefira ⅓ a ⅔ do pote: mãos piores ainda pagam.",
                     "With thin value (top pair), prefer ⅓ to ⅔ pot: worse hands still call.")
        return ok, "" if ok else tip
    if v.reason == "semibluff":
        ok = 0.45 <= frac <= 0.8
        return ok, "" if ok else tr("No semiblefe, ½ a ⅔ do pote equilibra pressão e custo.",
                                    "For a semi-bluff, ½ to ⅔ pot balances pressure and cost.")
    return True, ""


# ---------------------------------------------------------------- textos

def quality_label(q: str) -> tuple[str, str]:
    """(texto, cor) da nota."""
    return {"best": (tr("Melhor jogada", "Best play"), "#3ddc84"),
            "ok": (tr("Aceitável", "Acceptable"), "#f5c542"),
            "mistake": (tr("Erro", "Mistake"), "#ff6b6b")}[q]


def num(v: float, digits: int = 1) -> str:
    """Número curto no formato do idioma (2,5 / 2.5)."""
    txt = f"{v:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{v:.0f}"
    return txt.replace(".", tr(",", "."))


def bb(chips: float) -> str:
    return num(chips / BB) + " bb"


def ev_bb(spot: Spot, equity: float) -> str:
    ev = spot.ev_call(equity) / BB
    return ("+" if ev >= 0 else "−") + num(abs(ev)) + " bb"


def situation(spot: Spot, n_opp: int) -> tuple[str, str]:
    """(pergunta, detalhe) mostrados antes da decisão."""
    pos = spot.hero_pos
    stack = tr(f"Stack efetivo {bb(spot.stack)}", f"Effective stack {bb(spot.stack)}")
    if spot.kind == "open":
        q = tr(f"Todos desistiram até você ({pos}). Abrir, entrar só pagando ou desistir?",
               f"Folded to you ({pos}). Open, limp or fold?")
        d = tr(f"Blinds {SB}/{BB} · {n_opp} jogador{'es' if n_opp > 1 else ''} para agir depois de você · {stack}.",
               f"Blinds {SB}/{BB} · {n_opp} player{'s' if n_opp > 1 else ''} left to act · {stack}.")
    elif spot.kind == "limped":
        q = tr(f"Você é o big blind e {n_opp} jogador{'es' if n_opp > 1 else ''} só pagou. Passar ou aumentar?",
               f"You're the big blind and {n_opp} player{'s' if n_opp > 1 else ''} limped. Check or raise?")
        d = tr(f"Pote de {bb(spot.pot)} · você fala por último antes do flop, mas fica fora de posição depois · "
               f"{stack}.", f"Pot of {bb(spot.pot)} · you act last pre-flop but are out of position after · {stack}.")
    elif spot.kind == "vs_raise":
        raiser = spot.opp_pos[0] if spot.opp_pos else ""
        calls = tr(f" e {spot.callers} pag{'aram' if spot.callers > 1 else 'ou'}",
                   f" and {spot.callers} called") if spot.callers else ""
        where = tr("no botão (os blinds desistiram)", "on the button (blinds folded)") if spot.hero_pos == "BTN" \
            else tr("no big blind", "in the big blind")
        q = tr(f"{raiser} aumentou para {bb(spot.to_call + (BB if spot.hero_pos == 'BB' else 0))}{calls}. Você está "
               f"{where}.", f"{raiser} raised to {bb(spot.to_call + (BB if spot.hero_pos == 'BB' else 0))}{calls}. "
               f"You're {where}.")
        d = tr(f"Pagar {bb(spot.to_call)} → pote final {bb(spot.final_pot)} · "
               f"{'em posição' if spot.in_position else 'fora de posição'} depois do flop · {stack}.",
               f"Call {bb(spot.to_call)} → final pot {bb(spot.final_pot)} · "
               f"{'in position' if spot.in_position else 'out of position'} after the flop · {stack}.")
    elif spot.kind == "check":
        pos_txt = tr("em posição", "in position") if spot.in_position else tr("fora de posição", "out of position")
        if spot.in_position:
            q = tr("Passaram para você. Passar ou apostar?", "Checked to you. Check or bet?")
        else:
            q = tr("Você fala primeiro. Passar ou apostar?", "You act first. Check or bet?")
        d = tr(f"Pote de {bb(spot.pot)} · {pos_txt} · {stack} · SPR {num(spot.spr)}",
               f"Pot of {bb(spot.pot)} · {pos_txt} · {stack} · SPR {num(spot.spr)}")
    else:
        pos_txt = tr("em posição", "in position") if spot.in_position else tr("fora de posição", "out of position")
        lead = "" if spot.in_position else tr("Você passou e ", "You checked and ")
        calls = tr(f", {spot.callers} pag{'aram' if spot.callers > 1 else 'ou'}", f", {spot.callers} called") \
            if spot.callers else ""
        q = lead + tr(f"o oponente 1 apostou {bb(spot.bet)}{calls}. Qual a sua jogada?",
                      f"opponent 1 bet {bb(spot.bet)}{calls}. What's your play?")
        q = q[0].upper() + q[1:]
        d = tr(f"Pagar {bb(spot.bet)} → pote final {bb(spot.final_pot)} · {pos_txt} · {stack} · SPR {num(spot.spr)}",
               f"Call {bb(spot.bet)} → final pot {bb(spot.final_pot)} · {pos_txt} · {stack} · SPR {num(spot.spr)}")
    return q, d


def button_text(spot: Spot, action: str, size: int | None = None) -> str:
    amt = size if size else spot.hero_bet
    if action == CALL:
        if spot.kind == "open":
            return tr(f"Só pagar {bb(spot.to_call)}", f"Limp {bb(spot.to_call)}")
        return tr(f"Pagar {bb(spot.to_call)}", f"Call {bb(spot.to_call)}")
    if action == BET:
        return tr(f"Apostar {bb(amt)}", f"Bet {bb(amt)}")
    if action == RAISE:
        return tr(f"Aumentar p/ {bb(amt)}", f"Raise to {bb(amt)}")
    return action_name(action)


def seat_actions(spot: Spot, n_opp: int) -> list[str]:
    """O que cada oponente fez antes da sua vez (texto curto para o assento)."""
    out = []
    for k in range(n_opp):
        a = spot.acts[k] if k < len(spot.acts) else "wait"
        pos = spot.opp_pos[k] if k < len(spot.opp_pos) else ""
        txt = {"wait": tr("a agir", "to act"), "check": tr("passou", "checked"), "limp": tr("pagou 1 bb", "limped"),
               "raise": tr(f"aumentou p/ {bb(spot.to_call + (BB if spot.hero_pos == 'BB' else 0))}",
                           f"raised to {bb(spot.to_call + (BB if spot.hero_pos == 'BB' else 0))}"),
               "call": tr("pagou", "called"), "bet": tr(f"apostou {bb(spot.bet)}", f"bet {bb(spot.bet)}")}.get(a, a)
        out.append(f"{pos} · {txt}" if pos else txt)
    return out


def feedback(spot: Spot, v: Verdict, n_opp: int, vs_random: float | None = None) -> list[str]:
    """Por que a melhor jogada é a melhor (HTML curto)."""
    eq, need = v.equity, v.need
    tips = []
    if v.action:
        label, color = quality_label(v.quality)
        mine = action_name(v.action).lower()
        if v.quality == "best":
            tips.append(tr(f"Você escolheu <b>{mine}</b>: <span style='color:{color}'><b>{label.lower()}</b></span>.",
                           f"You chose to <b>{mine}</b>: <span style='color:{color}'><b>{label.lower()}</b></span>."))
        else:
            tips.append(tr(f"Você escolheu <b>{mine}</b> (<span style='color:{color}'>{label.lower()}</span>); "
                           f"a melhor jogada era <b>{action_name(v.best).lower()}</b>.",
                           f"You chose to <b>{mine}</b> (<span style='color:{color}'>{label.lower()}</span>); "
                           f"the best play was to <b>{action_name(v.best).lower()}</b>."))
        if not v.size_ok and v.size_tip:
            tips.append(tr("Jogada certa, tamanho a ajustar: ", "Right play, size to adjust: ") + v.size_tip)
    r = v.reason
    pos = spot.hero_pos
    if r == "open_raise":
        tips.append(tr(f"Sua mão está no top {v.pct:.0f}% das mãos iniciais; do {pos} um jogador sólido abre cerca do "
                       f"top {R.open_pct(pos)}%. Abra com um aumento — entrar só pagando (limp) deixa os blinds "
                       "verem o flop de graça e esconde pouco.",
                       f"Your hand is in the top {v.pct:.0f}% of starting hands; from {pos} a solid player opens about "
                       f"the top {R.open_pct(pos)}%. Open with a raise — limping lets the blinds see a cheap flop."))
    elif r == "open_border":
        tips.append(tr(f"Mão no limite da abertura do {pos} (top {v.pct:.0f}% contra ~{R.open_pct(pos)}%): abrir ou "
                       "desistir são aceitáveis; nunca só pagar.",
                       f"A borderline open from {pos} (top {v.pct:.0f}% vs ~{R.open_pct(pos)}%): opening or folding "
                       "are both fine; never limp."))
    elif r == "open_fold":
        tips.append(tr(f"Mão fraca demais para abrir do {pos} (top {v.pct:.0f}%; o limite é ~{R.open_pct(pos)}%). "
                       f"Ainda há {n_opp} jogador{'es' if n_opp > 1 else ''} para agir depois de você.",
                       f"Too weak to open from {pos} (top {v.pct:.0f}%; the limit is ~{R.open_pct(pos)}%). There "
                       f"{'are' if n_opp > 1 else 'is'} still {n_opp} player{'s' if n_opp > 1 else ''} to act."))
    elif r == "iso_raise":
        tips.append(tr(f"Contra quem só pagou (mãos medianas) você tem <b>{eq:.0%}</b>: aumente para isolar e jogar "
                       "um pote maior com a melhor mão.",
                       f"Against limpers (medium hands) you have <b>{eq:.0%}</b>: raise to isolate and play a bigger "
                       "pot with the best hand."))
    elif r == "limp_check":
        tips.append(tr(f"Contra quem só pagou você tem {eq:.0%}: não é forte o bastante para aumentar fora de posição. "
                       "Passe e veja o flop de graça.",
                       f"Against the limpers you have {eq:.0%}: not strong enough to raise out of position. Check "
                       "and see a free flop."))
    elif r == "threebet_value":
        tips.append(tr(f"Contra as mãos com que o {spot.opp_pos[0] if spot.opp_pos else ''} aumenta você tem "
                       f"<b>{eq:.0%}</b>, e <b>{v.value:.0%}</b> contra as que pagariam um re-aumento: re-aumente "
                       "(3-bet) por valor.",
                       f"Against the hands {spot.opp_pos[0] if spot.opp_pos else ''} raises with you have "
                       f"<b>{eq:.0%}</b>, and <b>{v.value:.0%}</b> against the ones that would call a re-raise: "
                       "3-bet for value."))
    elif r in ("call_raise", "borderline", "fold_price", "implied_pf", "call_price", "call_implied", "fold_draw"):
        oop = "" if spot.in_position or spot.street == 5 else tr(
            f" Fora de posição você aproveita menos a sua chance (+{OOP_TAX:.0%} no preço).",
            f" Out of position you realize less of your chance (+{OOP_TAX:.0%} on the price).")
        if r == "call_implied":
            tips.append(tr(f"O preço puro é {need:.0%} e você tem {eq:.0%}, mas com {bb(spot.stack)} atrás o projeto "
                           f"ganha muito quando completa (odds implícitas): pagar vale a pena.",
                           f"The raw price is {need:.0%} and you have {eq:.0%}, but with {bb(spot.stack)} behind the "
                           "draw wins a lot when it hits (implied odds): calling is worth it."))
        elif r in ("call_raise", "call_price"):
            tips.append(tr(f"Sua chance contra as mãos com que eles jogariam assim é <b>{eq:.0%}</b>; o preço é "
                           f"<b>{need:.0%}</b>.{oop} Pagar ganha em média <b>{ev_bb(spot, eq)}</b>.",
                           f"Your chance against the hands they'd play this way is <b>{eq:.0%}</b>; the price is "
                           f"<b>{need:.0%}</b>.{oop} Calling wins <b>{ev_bb(spot, eq)}</b> on average."))
        elif r == "borderline":
            tips.append(tr(f"No limite: chance {eq:.0%} contra preço de {v.need_eff:.0%}.{oop} Pagar e desistir "
                           "valem quase o mesmo.",
                           f"Borderline: chance {eq:.0%} vs a price of {v.need_eff:.0%}.{oop} Calling and folding "
                           "are about even."))
        elif r == "implied_pf":
            tips.append(tr(f"Pelo preço puro ({need:.0%}) é desistir, mas em posição e com stack fundo pagar para "
                           "acertar o flop também é aceitável.",
                           f"By the raw price ({need:.0%}) it's a fold, but in position and deep, calling to hit "
                           "the flop is acceptable too."))
        elif r == "fold_draw":
            tips.append(tr(f"O projeto não tem preço para pagar ({eq:.0%} contra {v.need_eff:.0%}). Um aumento como "
                           "semiblefe é aceitável; só pagar perde fichas.",
                           f"The draw doesn't have the price to call ({eq:.0%} vs {v.need_eff:.0%}). A semi-bluff "
                           "raise is acceptable; just calling loses chips."))
        elif spot.ev_call(eq) >= -BB * 0.05:
            tips.append(tr(f"Pelo preço puro ({need:.0%}) pagar ficaria perto do zero a zero ({ev_bb(spot, eq)}) com "
                           f"<b>{eq:.0%}</b> de chance, mas{oop.replace(' Fora', ' fora').rstrip('.') or ' sem margem'}"
                           " — desistir é melhor.",
                           f"By the raw price ({need:.0%}) calling would be about break-even ({ev_bb(spot, eq)}) with "
                           f"<b>{eq:.0%}</b>, but{oop.replace(' Out', ' out').rstrip('.') or ' there is no margin'}"
                           " — folding is better."))
        else:
            tips.append(tr(f"Sua chance contra as mãos com que eles jogariam assim é <b>{eq:.0%}</b>, abaixo do preço "
                           f"(<b>{v.need_eff or need:.0%}</b>).{oop} Pagar perde em média "
                           f"<b>{bb(-spot.ev_call(eq))}</b>; desistir custa zero.",
                           f"Your chance against the hands they'd play this way is <b>{eq:.0%}</b>, below the price "
                           f"(<b>{v.need_eff or need:.0%}</b>).{oop} Calling loses <b>{bb(-spot.ev_call(eq))}"
                           "</b> on average; folding costs nothing."))
    elif r == "raise_value":
        tips.append(tr(f"Você ganha de <b>{v.value:.0%}</b> das mãos que pagariam um aumento: aumente por valor. Só "
                       "pagar também ganha, mas deixa fichas na mesa.",
                       f"You beat <b>{v.value:.0%}</b> of the hands that would call a raise: raise for value. Just "
                       "calling wins too, but leaves chips on the table."))
    elif r == "bet_value":
        tips.append(tr(f"Contra as mãos que <b>pagariam</b> a sua aposta você tem <b>{v.value:.0%}</b> (acima de "
                       f"{value_threshold(n_opp):.0%}): aposte por valor.",
                       f"Against the hands that would <b>call</b> your bet you have <b>{v.value:.0%}</b> (above "
                       f"{value_threshold(n_opp):.0%}): bet for value."))
    elif r == "semibluff":
        tips.append(tr(f"Projeto forte: apostar (semiblefe) ganha o pote quando eles desistem e, se pagarem, você ainda "
                       f"tem {eq:.0%} de chance. Passar também é aceitável.",
                       f"Strong draw: betting (a semi-bluff) wins the pot when they fold and, if called, you still "
                       f"have {eq:.0%}. Checking is acceptable too."))
    elif r == "river_bluff":
        tips.append(tr("No river sua mão não ganha no showdown. Passar é o padrão; um blefe pequeno contra quem passou "
                       "(faixa sem as mãos mais fortes) é aceitável de vez em quando.",
                       "On the river your hand can't win at showdown. Checking is standard; a small bluff against a "
                       "player who checked (a range without the strongest hands) is fine once in a while."))
    elif r == "check_weak":
        tips.append(tr(f"Contra as mãos que pagariam uma aposta você teria só {v.value:.0%}: quem paga costuma ter "
                       "mão melhor. Passe.",
                       f"Against the hands that would call a bet you'd have only {v.value:.0%}: callers usually have "
                       "you beat. Check."))
    if spot.street >= 3 and v.hero_class is not None:
        tips.append(tr(f"Sua mão: {R.class_name(v.hero_class)}.", f"Your hand: {R.class_name(v.hero_class)}."))
    if vs_random is not None and abs(vs_random - eq) >= 0.04:
        tips.append(tr(f"Contra cartas aleatórias seriam {vs_random:.0%} — mas ninguém aposta ou aumenta com qualquer "
                       "mão. A conta certa é contra a faixa de quem agiu.",
                       f"Against random cards it would be {vs_random:.0%} — but nobody bets or raises with any two "
                       "cards. The right math is against the acting player's range."))
    return tips
