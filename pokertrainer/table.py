"""Mesa de Texas Hold'em No-Limit: blinds, rodadas de apostas, all-in, potes paralelos e showdown.

Sem interface: a tela chama `start_hand`, consulta `to_act` / `legal()` e aplica `act()`. Cada mudança gera um
evento em `events` (para o histórico e as animações).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from pokertrainer import engine as E

STREETS = ["preflop", "flop", "turn", "river"]


@dataclass(eq=False)
class Player:
    name: str
    stack: int
    is_hero: bool = False
    avatar: str = "🙂"
    ai: object | None = None          # pokertrainer.ai.Bot
    hole: list[int] = field(default_factory=list)
    bet: int = 0                      # apostado nesta rua
    total: int = 0                    # apostado na mão
    folded: bool = False
    all_in: bool = False
    sitting_out: bool = False
    last_action: str = ""
    # estatísticas observáveis (HUD)
    hands: int = 0
    vpip: int = 0
    pfr: int = 0
    bets_raises: int = 0
    calls: int = 0
    folds_to_bet: int = 0
    faced_bets: int = 0
    saw_flop: int = 0         # mãos em que viu o flop
    showdowns: int = 0        # foi ao showdown (WTSD = showdowns / saw_flop)
    showdown_wins: int = 0    # ganhou no showdown (W$SD = showdown_wins / showdowns)
    threebets: int = 0        # re-aumentou antes do flop diante de um aumento
    threebet_opp: int = 0
    cbets: int = 0            # aposta de continuação: quem aumentou antes do flop aposta no flop
    cbet_opp: int = 0
    _vpip_hand: bool = False
    _pfr_hand: bool = False
    _3b_opp_hand: bool = False
    _cbet_opp_hand: bool = False
    post_aggr: str = ""       # última rua (flop/turn/river) em que apostou/aumentou nesta mão ("" = nenhuma)
    uid: int = 0              # identidade estável (para a memória dos bots)

    @property
    def in_hand(self) -> bool:
        return not self.folded and not self.sitting_out and bool(self.hole)

    @property
    def can_act(self) -> bool:
        return self.in_hand and not self.all_in


@dataclass
class Legal:
    to_call: int
    can_check: bool
    min_raise_to: int     # aposta total mínima nesta rua para apostar/aumentar
    max_raise_to: int     # all-in
    can_raise: bool


@dataclass
class Event:
    kind: str             # "hand", "blind", "action", "street", "showdown", "win", "bust"
    seat: int = -1
    action: str = ""      # fold, check, call, bet, raise, allin
    amount: int = 0
    text: str = ""
    data: dict = field(default_factory=dict)


_UID = [0]


def new_uid() -> int:
    _UID[0] += 1
    return _UID[0]


class Table:
    def __init__(self, players: list[Player], sb: int = 5, bb: int = 10, rng: random.Random | None = None,
                 ante: int = 0) -> None:
        self.players = players
        for p in players:
            if not p.uid:
                p.uid = new_uid()
        self.sb, self.bb = sb, bb
        self.ante = ante                         # ante do big blind (o BB paga por todos; vai direto ao pote)
        self.bubble = False                      # torneio: falta uma eliminação para fechar a rodada
        self.rng = rng or random.Random()
        self.dealer = self.rng.randrange(len(players))
        self.board: list[int] = []
        self.deck: list[int] = []
        self.street = "preflop"
        self.current_bet = 0
        self.min_raise = bb
        self.to_act: int | None = None
        self._pending: set[int] = set()
        self.hand_no = 0
        self.hand_over = True
        self.events: list[Event] = []
        self.last_aggressor: int | None = None
        self._pf_raises = 0                      # aumentos antes do flop nesta mão
        self.pf_aggressor: int | None = None     # último a aumentar antes do flop
        self.winners: dict[int, int] = {}       # assento -> fichas ganhas na mão
        self.showdown_hands: dict[int, int] = {}  # assento -> pontuação no showdown
        self.shown: list[int] = []               # quem mostrou as cartas no showdown (na ordem); o resto descartou
        self.street_aggressor: int | None = None  # último a apostar/aumentar nesta rua
        self.runout = False                      # all-in sem mais apostas: todos mostram as cartas
        self._acted: set[int] = set()            # agiram desde o último aumento completo
        self._no_reraise: set[int] = set()       # já agiram e só enfrentam um all-in incompleto: não podem aumentar

    # ------------------------------------------------------------ utilidades
    @property
    def pot(self) -> int:
        return sum(p.total for p in self.players)

    def seats_in_hand(self) -> list[int]:
        return [i for i, p in enumerate(self.players) if p.in_hand]

    def _next(self, i: int, cond) -> int | None:
        """Próximo assento (no sentido horário) cujo jogador satisfaz `cond(player)`."""
        n = len(self.players)
        for k in range(1, n + 1):
            j = (i + k) % n
            if cond(self.players[j]):
                return j
        return None

    def _next_seat(self, i: int, seats: set[int]) -> int | None:
        n = len(self.players)
        for k in range(1, n + 1):
            j = (i + k) % n
            if j in seats:
                return j
        return None

    def _emit(self, **kw) -> None:
        self.events.append(Event(**kw))

    def position_of(self, seat: int) -> str:
        """Nome curto da posição (BTN, SB, BB, UTG…, HJ, CO)."""
        active = [i for i, p in enumerate(self.players) if not p.sitting_out and p.hole]
        if seat not in active or self.dealer not in active:
            return ""
        d = active.index(self.dealer)
        order = active[d:] + active[:d]          # começa no botão
        k, n = order.index(seat), len(order)
        if n == 2:
            return "BTN" if k == 0 else "BB"
        if k < 3:
            return ["BTN", "SB", "BB"][k]
        late = ["CO", "HJ"]
        if n - k <= 2 and n >= 5:
            return late[n - k - 1]
        return "UTG" if k == 3 else f"UTG+{k - 3}" if k <= 5 else "MP"

    # ------------------------------------------------------------ mão
    def start_hand(self) -> None:
        live = [p for p in self.players if p.stack > 0 and not p.sitting_out]
        if len(live) < 2:
            raise RuntimeError("jogadores insuficientes")
        self.hand_no += 1
        self.hand_over = False
        self.events = []
        self.winners = {}
        self.showdown_hands = {}
        self.shown = []
        self.street_aggressor = None
        self.runout = False
        self._acted, self._no_reraise = set(), set()
        for p in self.players:
            p.hole, p.bet, p.total = [], 0, 0
            p.folded = p.all_in = False
            p.last_action = ""
            p._vpip_hand = p._pfr_hand = p._3b_opp_hand = p._cbet_opp_hand = False
            p.post_aggr = ""
            if not p.uid:
                p.uid = new_uid()
            if p.stack <= 0:
                p.sitting_out = True
        self.dealer = self._next(self.dealer, lambda p: not p.sitting_out)
        self.deck = list(range(52))
        self.rng.shuffle(self.deck)
        self.board = []
        for p in self.players:
            if not p.sitting_out:
                p.hole = [self.deck.pop(), self.deck.pop()]
                p.hands += 1
        self._emit(kind="hand", seat=self.dealer, amount=self.hand_no)
        active = [i for i, p in enumerate(self.players) if not p.sitting_out]
        if len(active) == 2:
            sb_seat = self.dealer
        else:
            sb_seat = self._next(self.dealer, lambda p: not p.sitting_out)
        bb_seat = self._next(sb_seat, lambda p: not p.sitting_out)
        self._post(sb_seat, self.sb, "SB")
        self._post(bb_seat, self.bb, "BB")
        if self.ante:
            self._post_ante(bb_seat, self.ante)
        self.street = "preflop"
        self.current_bet = self.bb
        self.min_raise = self.bb
        self.last_aggressor = bb_seat
        self._pf_raises = 0
        self.pf_aggressor = None
        self._pending = {i for i, p in enumerate(self.players) if p.can_act}
        self.to_act = self._next(bb_seat, lambda p: p.can_act)
        self._check_round_end()

    def _post(self, seat: int, amount: int, label: str) -> None:
        p = self.players[seat]
        amt = min(amount, p.stack)
        p.stack -= amt
        p.bet += amt
        p.total += amt
        if p.stack == 0:
            p.all_in = True
        p.last_action = f"{label} {amt}"
        self._emit(kind="blind", seat=seat, amount=amt, text=label)

    def _post_ante(self, seat: int, amount: int) -> None:
        """Ante do big blind: fichas mortas direto no pote (não contam como aposta da rua)."""
        p = self.players[seat]
        amt = min(amount, p.stack)
        p.stack -= amt
        p.total += amt
        if p.stack == 0:
            p.all_in = True
        self._emit(kind="blind", seat=seat, amount=amt, text="ANTE")

    def legal(self, seat: int | None = None) -> Legal:
        seat = self.to_act if seat is None else seat
        p = self.players[seat]
        to_call = min(self.current_bet - p.bet, p.stack)
        max_to = p.bet + p.stack
        min_to = min(self.current_bet + self.min_raise, max_to) if self.current_bet else min(self.bb, max_to)
        # só pode aumentar se ainda há alguém para pagar e se tem fichas além do call
        others = [q for i, q in enumerate(self.players) if i != seat and q.can_act]
        # um all-in menor que o aumento mínimo não reabre a ação para quem já tinha agido
        can_raise = p.stack > to_call and bool(others) and seat not in self._no_reraise
        return Legal(to_call=to_call, can_check=to_call == 0, min_raise_to=min_to, max_raise_to=max_to,
                     can_raise=can_raise)

    def act(self, action: str, amount_to: int = 0) -> None:
        """action: fold | check | call | raise (aposta total `amount_to` nesta rua) | allin."""
        seat = self.to_act
        if seat is None or self.hand_over:
            return
        p = self.players[seat]
        lg = self.legal(seat)
        facing = self.current_bet > p.bet
        if facing:
            p.faced_bets += 1
        three_opp = self.street == "preflop" and self._pf_raises == 1 and not p._3b_opp_hand
        if three_opp:
            p._3b_opp_hand = True
            p.threebet_opp += 1
        cbet_opp = (self.street == "flop" and seat == self.pf_aggressor and self.current_bet == 0
                    and not p._cbet_opp_hand)
        if cbet_opp:
            p._cbet_opp_hand = True
            p.cbet_opp += 1
        if action == "check" and not lg.can_check:
            action = "call"
        if action == "allin":
            amount_to = lg.max_raise_to
            action = "raise" if amount_to > self.current_bet else "call"
        if action == "raise" and not lg.can_raise:
            action = "call" if lg.to_call else "check"
        if action == "fold":
            if lg.can_check:
                action = "check"
            else:
                p.folded = True
                p.last_action = "fold"
                if facing:
                    p.folds_to_bet += 1
                self._emit(kind="action", seat=seat, action="fold")
        if action == "check":
            p.last_action = "check"
            self._emit(kind="action", seat=seat, action="check")
        elif action == "call":
            amt = lg.to_call
            self._put(p, amt)
            p.calls += 1
            if self.street == "preflop" and amt > 0:
                p._vpip_hand = True
            p.last_action = "allin" if p.all_in else "call"
            self._emit(kind="action", seat=seat, action=p.last_action, amount=p.bet)
        elif action == "raise":
            amount_to = max(lg.min_raise_to, min(int(amount_to), lg.max_raise_to))
            raise_by = amount_to - self.current_bet
            self._put(p, amount_to - p.bet)
            if raise_by >= self.min_raise:
                self.min_raise = raise_by
                # aumento completo reabre a ação para todos
                self._pending = {i for i, q in enumerate(self.players) if q.can_act}
                self._acted, self._no_reraise = set(), set()
            else:
                # all-in menor que um aumento mínimo: todos precisam responder, mas quem já agiu só paga ou larga
                self._pending |= {i for i, q in enumerate(self.players) if q.can_act and q.bet < amount_to}
                self._no_reraise |= self._acted - {seat}
            self.street_aggressor = seat
            kind = "bet" if self.current_bet == 0 else "raise"
            self.current_bet = max(self.current_bet, amount_to)
            self.last_aggressor = seat
            p.bets_raises += 1
            if self.street == "preflop":
                p._vpip_hand = p._pfr_hand = True
                if three_opp:
                    p.threebets += 1
                self._pf_raises += 1
                self.pf_aggressor = seat
            if cbet_opp:
                p.cbets += 1
            if self.street != "preflop":
                p.post_aggr = self.street
            p.last_action = "allin" if p.all_in else kind
            self._emit(kind="action", seat=seat, action=p.last_action, amount=p.bet)
        self._pending.discard(seat)
        self._acted.add(seat)
        self._advance(seat)

    def _put(self, p: Player, amt: int) -> None:
        amt = max(0, min(amt, p.stack))
        p.stack -= amt
        p.bet += amt
        p.total += amt
        if p.stack == 0:
            p.all_in = True

    def _advance(self, seat: int) -> None:
        if len(self.seats_in_hand()) == 1:
            self._finish_uncontested()
            return
        self._pending = {i for i in self._pending if self.players[i].can_act}
        if self._pending:
            self.to_act = self._next_seat(seat, self._pending)
            return
        self._end_street()

    def _check_round_end(self) -> None:
        self._pending = {i for i in self._pending if self.players[i].can_act}
        live = [i for i in self.seats_in_hand() if self.players[i].can_act]
        if not self._pending or (len(live) <= 1 and all(self.players[i].bet >= self.current_bet for i in live)):
            self._end_street()

    def _end_street(self) -> None:
        for p in self.players:
            p.bet = 0
        self.current_bet = 0
        self.min_raise = self.bb
        self._acted, self._no_reraise = set(), set()
        live = [i for i in self.seats_in_hand() if self.players[i].can_act]
        if self.street == "river":
            self._showdown()
            return
        nxt = STREETS[STREETS.index(self.street) + 1]
        self.street = nxt
        if nxt == "flop":
            for p in self.players:
                if p.in_hand:
                    p.saw_flop += 1
        self.deck.pop()  # carta queimada
        add = 3 if nxt == "flop" else 1
        for _ in range(add):
            self.board.append(self.deck.pop())
        self._emit(kind="street", text=nxt, data={"board": list(self.board)})
        for p in self.players:
            if p.in_hand and not p.all_in:
                p.last_action = ""
        if len(live) <= 1:
            # ninguém mais pode apostar: corre as cartas até o river (todos mostram as cartas)
            self.runout = True
            self.to_act = None
            self._end_street()
            return
        self._pending = set(live)
        self.street_aggressor = None
        self.to_act = self._next(self.dealer, lambda q: q.can_act)

    def _finish_uncontested(self) -> None:
        w = self.seats_in_hand()[0]
        pot = self.pot
        self.players[w].stack += pot
        self.winners = {w: pot}
        self._emit(kind="win", seat=w, amount=pot, text="")
        self._close_hand()

    def side_pots(self) -> list[tuple[int, list[int]]]:
        """[(valor, assentos que podem ganhar)] do pote principal aos paralelos."""
        contrib = {i: p.total for i, p in enumerate(self.players) if p.total > 0}
        levels = sorted({v for i, v in contrib.items() if self.players[i].in_hand})
        pots, prev = [], 0
        for lv in levels:
            amount = sum(min(v, lv) - min(v, prev) for v in contrib.values())
            elig = [i for i in self.seats_in_hand() if contrib.get(i, 0) >= lv]
            if amount > 0:
                pots.append((amount, elig))
            prev = lv
        # fichas de quem desistiu acima do maior nível vão para o último pote
        leftover = self.pot - sum(a for a, _ in pots)
        if leftover and pots:
            a, el = pots[-1]
            pots[-1] = (a + leftover, el)
        return pots

    def _showdown(self) -> None:
        self.to_act = None
        while len(self.board) < 5:
            self.board.append(self.deck.pop())
        scores = {i: E.evaluate(self.players[i].hole + self.board) for i in self.seats_in_hand()}
        self.showdown_hands = scores
        self.shown = self._show_order(scores)
        for i in scores:
            self.players[i].showdowns += 1
        self._emit(kind="showdown", data={"scores": dict(scores)})
        won: dict[int, int] = {}
        for amount, elig in self.side_pots():
            best = max(scores[i] for i in elig)
            ws = [i for i in elig if scores[i] == best]
            share, rest = divmod(amount, len(ws))
            # fichas que sobram da divisão vão para o primeiro vencedor à esquerda do dealer
            order = sorted(ws, key=lambda i: (i - self.dealer - 1) % len(self.players))
            for k, i in enumerate(order):
                won[i] = won.get(i, 0) + share + (1 if k < rest else 0)
        for i, amt in won.items():
            self.players[i].stack += amt
            self.players[i].showdown_wins += 1
            self._emit(kind="win", seat=i, amount=amt, text=E.describe(scores[i]))
        self.winners = won
        self._close_hand()

    def _show_order(self, scores: dict[int, int]) -> list[int]:
        """Quem mostra as cartas: começa pelo último a apostar no river (ou o primeiro à esquerda do botão); depois,
        cada um só mostra se empata ou vence o melhor já mostrado — quem perde descarta. Num all-in todos mostram."""
        seats = list(scores)
        if self.runout:
            return seats
        n = len(self.players)
        start = self.street_aggressor if self.street_aggressor in scores else self._next(
            self.dealer, lambda q: q.in_hand)
        order = sorted(seats, key=lambda i: (i - start) % n)
        shown, best = [], -1
        for i in order:
            if scores[i] >= best:
                shown.append(i)
                best = scores[i]
        return shown

    def _close_hand(self) -> None:
        self.hand_over = True
        self.to_act = None
        for p in self.players:
            if p.hole and not p.sitting_out:
                p.vpip += p._vpip_hand
                p.pfr += p._pfr_hand
        for i, p in enumerate(self.players):
            if p.stack == 0 and not p.sitting_out:
                self._emit(kind="bust", seat=i)
