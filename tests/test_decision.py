import random

import pytest

from pokertrainer import decision as D
from pokertrainer import engine as E
from pokertrainer import ranges as R


def cs(s):
    return [E.card(x) for x in s.split()]


def facing(pot=200, bet=100, callers=0, street=3, ip=True, stack=1000):
    """Pote de `pot` já com a aposta de `bet` (como o app monta a situação)."""
    return D.Spot(street, pot, bet, callers, "bet", 3 * bet, "BTN" if ip else "BB", ["BB"], stack, ip,
                  [R.CALL_BAND], ["bet"], R.CALL_BAND, [("2,5×", 250), ("3×", 300), ("All-in", stack)])


def checked(pot=100, street=3, ip=True):
    return D.Spot(street, pot, 0, 0, "check", 66, "BTN" if ip else "BB", ["BB"], 1000, ip, [R.CALL_BAND],
                  ["check" if ip else "wait"], R.CALL_BAND, [("⅓", 35), ("½", 50), ("⅔", 65), ("Pote", 100)])


def test_pot_odds_math():
    sp = facing(200, 100)                 # pote 100 + aposta 100; pagar 100 → pote final 300
    assert sp.final_pot == 300 and sp.need == pytest.approx(1 / 3)
    assert sp.ev_call(0.5) == pytest.approx(50)
    assert sp.actions() == (D.FOLD, D.CALL, D.RAISE)
    sp = checked()
    assert not sp.facing_bet and sp.need == 0 and not sp.can_fold
    assert sp.actions() == (D.FOLD, D.CHECK, D.BET)


def test_ranges_depend_on_action():
    board = cs("Kd 7s 2c")
    hero = cs("Ah 7h")                    # par médio
    base = R.band_combos(*R.CALL_BAND)
    vs_bet = E.equity(hero, board, 1, 20000, random.Random(1),
                      opp_ranges=[R.weighted(base, board, set(hero + board), ("bet",))]).equity
    vs_check = E.equity(hero, board, 1, 20000, random.Random(1),
                        opp_ranges=[R.weighted(base, board, set(hero + board), ("check",))]).equity
    vs_random = E.equity(hero, board, 1, 20000, random.Random(1)).equity
    assert vs_bet < vs_check < vs_random
    # antes do flop: quem aumenta do UTG tem faixa forte
    a8 = cs("Ah 8d")
    assert E.equity(a8, [], 1, 20000, opp_ranges=[list(R.band_combos(0, R.open_pct("UTG")))]).equity < 0.45


def test_hand_classes():
    b = cs("Kd 7s 2c")
    assert R.hand_class(cs("Ks Qh"), b) == R.TOP
    assert R.hand_class(cs("Ah 7h"), b) == R.WEAK
    assert R.hand_class(cs("7c 7d"), b) == R.STRONG
    assert R.hand_class(cs("6s 5s"), cs("7s 4d 2s")) == R.DRAW
    assert R.hand_class(cs("9h 8h"), b) == R.AIR
    assert R.hand_pct(cs("As Ah")) < 1 and R.hand_pct(cs("7c 2d")) > 95


def test_facing_bet_grades_with_position_and_implied_odds():
    sp = facing(200, 100)                 # precisa de 33%
    assert D.evaluate(sp, 0.20, 1, 0, D.CALL).quality == "mistake"
    v = D.evaluate(sp, 0.45, 1, 0, D.CALL, eq_call=0.40)
    assert v.best == D.CALL and v.quality == "best"
    v = D.evaluate(sp, 0.60, 1, 0, D.RAISE, eq_call=0.58, size=250)
    assert v.best == D.RAISE and v.quality == "best"
    # fora de posição o preço sobe (realiza menos a chance)
    oop = facing(200, 100, ip=False)
    assert D.evaluate(oop, 0.36, 1, 0, D.CALL).need_eff > oop.need
    # projeto forte com stack fundo: odds implícitas
    hero, board = cs("6s 5s"), cs("7s 4d 2s")
    deep = facing(200, 100, stack=3000)
    v = D.evaluate(deep, 0.30, 1, 9, D.CALL, hero=hero, board=board)
    assert v.need_eff < deep.need and v.best == D.CALL


def test_value_bet_needs_to_beat_calling_range():
    sp = checked()
    # muita chance contra a faixa atual, mas pouca contra quem pagaria: passe
    v = D.evaluate(sp, 0.70, 1, 0, D.BET, eq_call=0.40, hero=cs("Ah 7h"), board=cs("Kd 7s 2c"))
    assert v.best == D.CHECK and v.quality == "mistake"
    v = D.evaluate(sp, 0.85, 1, 0, D.BET, eq_call=0.62, hero=cs("Ks Qh"), board=cs("Kd 7s 2c"), size=50)
    assert v.best == D.BET and v.quality == "best"
    # tamanho errado: jogada certa vira "aceitável"
    v = D.evaluate(sp, 0.95, 1, 0, D.BET, eq_call=0.9, hero=cs("7c 7d"), board=cs("Kd 7s 2c"), size=35)
    assert v.quality == "ok" and v.size_tip
    # semiblefe
    v = D.evaluate(sp, 0.35, 1, 9, D.CHECK, eq_call=0.3, hero=cs("6s 5s"), board=cs("7s 4d 2s"))
    assert v.best == D.BET and v.quality == "ok"


def test_preflop_open_by_position():
    sp = D.Spot(0, 15, 10, 0, "open", 25, "UTG", ["UTG+1"], 1000, True, [R.ANY], ["wait"], R.ANY,
                [("2,2 bb", 22), ("2,5 bb", 25), ("3 bb", 30)])
    assert D.evaluate(sp, 0.5, 8, 0, D.RAISE, hero=cs("As Ah"), size=25).quality == "best"
    assert D.evaluate(sp, 0.5, 8, 0, D.FOLD, hero=cs("Kc 9d")).best == D.FOLD     # K9o não abre do UTG
    btn = D.Spot(0, 15, 10, 0, "open", 25, "BTN", ["SB", "BB"], 1000, True, [R.ANY] * 2, ["wait"] * 2, R.ANY,
                 [("2,2 bb", 22), ("2,5 bb", 25), ("3 bb", 30)])
    assert D.evaluate(btn, 0.5, 2, 0, D.RAISE, hero=cs("Kc 9d"), size=25).quality == "best"
    assert D.evaluate(btn, 0.5, 2, 0, D.CALL, hero=cs("Kc 9d")).quality == "mistake"   # limp


def test_make_spot_and_deal_all_streets():
    rng = random.Random(3)
    for street in (0, 3, 4, 5):
        for n in (1, 3, 9):
            for _ in range(25):
                sp = D.make_spot(rng, street, n)
                assert sp.street == street and sp.pot > 0 and sp.stack > 0
                assert 0 <= sp.need < 0.6
                assert D.Spot.from_list(sp.to_list()) == sp
                d = D.deal_opponents(sp, D.deal_hero_board(sp, rng, n), rng, n)
                cards = d.hero + d.board + [c for o in d.opponents for c in o]
                assert len(d.opponents) == n and len(set(cards)) == 7 + 2 * n
                q, detail = D.situation(sp, n)
                assert q and detail
                assert len(D.seat_actions(sp, n)) == n


def test_old_history_spots_still_load():
    sp = D.Spot.from_list([3, 100, 50, 0, "bet", 150])
    assert sp.facing_bet and sp.kind == "bet"
