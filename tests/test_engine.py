import random
from itertools import combinations

import pytest

from pokertrainer import coach
from pokertrainer import engine as E


def cs(s):
    return [E.card(x) for x in s.split()]


def brute_best(cards):
    """Referência lenta: melhor de todas as combinações de 5 cartas."""
    return max(E.evaluate(list(c)) for c in combinations(cards, 5))


@pytest.mark.parametrize("hand,cat", [
    ("As Ks Qs Js Ts 2c 3d", E.STRAIGHT_FLUSH),
    ("Ah 2h 3h 4h 5h 9c 9d", E.STRAIGHT_FLUSH),
    ("9c 9d 9h 9s 2c 3d 4h", E.QUADS),
    ("Ah Ad Kc Kd Ks 2c 2d", E.FULL_HOUSE),
    ("Ah Jh 8h 4h 2h Kc Kd", E.FLUSH),
    ("Ah 2c 3d 4s 5h Kc Kd", E.STRAIGHT),
    ("8h 8d 8s Kc 4d 2c 3h", E.TRIPS),
    ("Qs Qd 7h 7c 3d 3s 2h", E.TWO_PAIR),
    ("Kh Kc 9d 6s 2c 3h 4d", E.PAIR),
    ("As Jd 8c 5h 3s 2c 9d", E.HIGH),
])
def test_categories(hand, cat):
    assert E.category(E.evaluate(cs(hand))) == cat


def test_ordering_and_kickers():
    assert E.evaluate(cs("Ah Kd 7c 7d 2s 3h 9c")) > E.evaluate(cs("Ah Qd 7c 7d 2s 3h 9c"))
    assert E.evaluate(cs("Ah 2c 3d 4s 5h Kc Qd")) < E.evaluate(cs("2c 3d 4s 5h 6h Kc Qd"))  # roda < 6-alta
    # três pares: o kicker pode vir do terceiro par
    assert E.evaluate(cs("Kh Kd Qh Qd Jc Js 2c")) > E.evaluate(cs("Kh Kd Qh Qd 2c 2s Tc"))


def test_matches_bruteforce_on_random_hands():
    rng = random.Random(3)
    for _ in range(3000):
        hand = rng.sample(range(52), 7)
        assert E.evaluate(hand) == brute_best(hand)


def test_table_matches_evaluator():
    rng = random.Random(5)
    t = E.rank_table()
    for _ in range(3000):
        hand = rng.sample(range(52), 7)
        key = 1
        for c in hand:
            key *= E.PRIMES[c >> 2]
        if E.category(E.evaluate(hand)) not in (E.FLUSH, E.STRAIGHT_FLUSH):
            assert t[key] == E.evaluate(hand)


@pytest.mark.parametrize("hero,board,n,expected", [
    ("As Ah", "", 1, 0.852),
    ("7c 2d", "", 1, 0.346),
    ("As Ah", "", 4, 0.560),
    ("8c 8d", "8h 2s 2c Jd", 1, 0.988),
])
def test_equity_known_values(hero, board, n, expected):
    r = E.equity(cs(hero), cs(board), n, 40000, random.Random(1))
    assert r.equity == pytest.approx(expected, abs=0.01)
    assert sum(r.final_categories) == pytest.approx(1.0)


def test_equity_exact_on_river_like_spot():
    # mesa com royal flush: todos empatam
    r = E.equity(cs("2c 3d"), cs("As Ks Qs Js Ts"), 1, 2000, random.Random(1))
    assert r.equity == pytest.approx(0.5) and r.tie == 1.0


def test_outs():
    o = E.outs(cs("Ah Kh"), cs("2h 7h Qc"))
    assert len(o[E.FLUSH]) == 9
    assert len(o[E.PAIR]) == 6
    o = E.outs(cs("9s 8s"), cs("7d 6c 2h Kd"))
    assert len(o[E.STRAIGHT]) == 8


def test_describe():
    assert E.describe(E.evaluate(cs("As Ks Qs Js Ts 2c 3d"))) == "Royal flush"
    assert E.describe_cards(cs("Qh Qs")) == "Par de Damas"
    assert E.starting_hand_label(*cs("Kh Ah")) == "AKs"
    assert E.starting_hand_label(*cs("7c 7d")) == "77"


def test_deal_unique_cards():
    d = E.deal(3, 9, random.Random(2))
    allc = d.hero + d.board + [c for o in d.opponents for c in o]
    assert len(allc) == len(set(allc)) == 2 + 5 + 18


def test_rating():
    assert coach.rate(1, 5).hit and coach.rate(1, 5).points == 95
    assert not coach.rate(12, 5).hit
    assert coach.rate(30, 5).points == 0


def test_preflop_table_present():
    t = coach.preflop_table()
    assert t is not None and len(t[1]) == 169
    assert coach.preflop_rank("AA", 1) == 1
    assert t[1]["AA"] == pytest.approx(0.852, abs=0.006)


def test_explain_runs_for_all_modes():
    rng = random.Random(4)
    for vis in (0, 3, 4):
        for n in (1, 5):
            d = E.deal(vis, n, rng)
            r = E.equity(d.hero, d.visible_board, n, 500, rng)
            assert coach.explain(d, r, n)


def test_round_tips_on_many_random_deals():
    rng = random.Random(11)
    for i in range(300):
        vis = (0, 3, 4)[i % 3]
        n = 1 + i % 9
        d = E.deal(vis, n, rng)
        r = E.equity(d.hero, d.visible_board, n, 300, rng)
        hs, opp = E.showdown(d)
        assert coach.guess_feedback(d, r, n, rng.randint(0, 100), 5)
        assert coach.runout_story(d, r, hs, opp)


def test_scenarios_scale():
    sc = coach.scenario("preflop", 4)
    assert sc.fair == pytest.approx(20)
    assert 9 <= sc.lo <= 12 and 55 <= sc.hi <= 57          # 32o ≈ 11% … AA ≈ 56%
    assert sum(sc.hist) == pytest.approx(1, abs=1e-3)
    for mode in ("flop", "turn"):
        for n in (1, 4, 9):
            s = coach.scenario(mode, n)
            assert s.hi == 100 and 0 <= s.lo < s.fair < s.hi
            # média da distribuição ≈ fatia justa (simetria)
            mean = sum((b + 0.5) * h for b, h in enumerate(s.hist))
            assert mean == pytest.approx(s.fair, abs=2.5)


def test_describe_english():
    from pokertrainer import i18n
    i18n.set_lang("en")
    try:
        assert E.describe_cards(cs("Qh Qs")) == "Pair of Queens"
        assert E.describe(E.evaluate(cs("Kh Kc Kd Ts Tc 2c 3d"))) == "Full house, Kings over Tens"
        assert E.category_name(E.TRIPS) == "Three of a kind"
    finally:
        i18n.set_lang("pt")
    assert E.describe_cards(cs("Qh Qs")) == "Par de Damas"
