import random

from pokertrainer import ai
from pokertrainer import engine as E
from pokertrainer import table as T


def cs(s):
    return [E.card(x) for x in s.split()]


def make(stacks):
    return T.Table([T.Player(f"P{i}", s, is_hero=i == 0) for i, s in enumerate(stacks)], 5, 10, random.Random(3))


def test_side_pots_and_showdown():
    t = make([100, 300, 300])
    t.start_hand()
    # cartas fixas: P0 tem a melhor mão, P1 a segunda
    t.players[0].hole, t.players[1].hole, t.players[2].hole = cs("As Ah"), cs("Ks Kh"), cs("7c 2d")
    used = set(cs("As Ah Ks Kh 7c 2d"))
    t.deck = [c for c in range(52) if c not in used and c not in cs("Qd 9s 5c 3h 4d Jc Tc 8c")] + \
        list(reversed(cs("Qd 9s 5c 3h 4d Jc Tc 8c")))
    while not t.hand_over:
        t.act("allin")
    total = sum(p.stack for p in t.players)
    assert total == 700
    pots = t.side_pots()
    assert [a for a, _ in pots] == [300, 400]
    assert t.players[0].stack == 300 and t.players[1].stack == 400 and t.players[2].stack == 0


def test_fold_to_big_blind_and_min_raise():
    t = make([1000, 1000, 1000])
    t.start_hand()
    lg = t.legal()
    assert lg.to_call == 10 and lg.min_raise_to == 20
    t.act("raise", 30)
    lg = t.legal()
    assert lg.min_raise_to == 50  # aumento mínimo = último aumento (20)
    while not t.hand_over:
        t.act("fold")
    assert sum(p.stack for p in t.players) == 3000
    assert len(t.winners) == 1


def test_bots_conserve_chips_and_finish_hands():
    rng = random.Random(11)
    for diff in ai.DIFFICULTIES:
        players = [ai.new_bot_player(diff, 1000, rng, set()) for _ in range(5)]
        t = T.Table(players, 5, 10, rng)
        total = 5000
        for _ in range(200):
            for i, p in enumerate(t.players):
                if p.stack == 0:
                    t.players[i] = ai.new_bot_player(diff, 1000, rng, set())
                    total += 1000
            t.start_hand()
            steps = 0
            while not t.hand_over:
                d = t.players[t.to_act].ai.decide(t, t.to_act)
                t.act(d.action, d.amount_to)
                steps += 1
                assert steps < 300
            assert sum(p.stack for p in t.players) == total
            for i, p in enumerate(t.players):
                p.ai.after_hand(t.winners.get(i, 0) - p.total, t.bb, False)


def test_mood_reacts_to_losses():
    pers = ai.make_personality("easy", random.Random(1))
    pers.base["tilt_prone"] = 0.9
    bot = ai.Bot(pers, random.Random(2))
    aggr0 = pers.eff("aggression")
    for _ in range(3):
        bot.after_hand(-400, 10, True)
    assert pers.tilt > 0.4 and pers.mood_emoji() == "😤"
    assert pers.eff("aggression") > aggr0
    for _ in range(25):
        bot.after_hand(0, 10, False)
    assert pers.tilt < 0.1


def test_hud_counters_threebet_cbet_showdown():
    t = make([1000, 1000, 1000])
    t.start_hand()
    first = t.to_act
    t.act("raise", 30)                 # abre
    second = t.to_act
    t.act("raise", 90)                 # 3-bet
    while t.street == "preflop" and not t.hand_over:
        t.act("call")
    p2 = t.players[second]
    assert p2.threebets == 1 and p2.threebet_opp == 1
    assert t.players[first].threebet_opp == 0       # quem abriu não tinha oportunidade de 3-bet
    assert t.pf_aggressor == second
    # no flop, quem fez o último aumento antes do flop tem a oportunidade de c-bet
    while not t.hand_over:
        if t.to_act == second and t.street == "flop" and t.current_bet == 0:
            t.act("raise", 100)
        else:
            t.act("call")
    assert p2.cbet_opp == 1 and p2.cbets == 1
    seen = [p for p in t.players if p.saw_flop]
    assert len(seen) == 3 and all(p.showdowns == 1 for p in seen)
    assert sum(p.showdown_wins for p in t.players) >= 1


def test_profile_style_and_verdicts():
    from pokertrainer import profile as PF
    base = dict.fromkeys(PF.COUNTERS, 0)
    assert PF.style(base) is None
    nit = dict(base, hands=100, vpip=10, pfr=8, bets_raises=30, calls=10)
    assert PF.style(nit) == "rock"
    tag = dict(base, hands=100, vpip=22, pfr=18, bets_raises=60, calls=25)
    assert PF.style(tag) == "tag"
    station = dict(base, hands=100, vpip=55, pfr=5, bets_raises=10, calls=80, faced_bets=50, folds_to_bet=5)
    assert PF.style(station) == "station"
    st = {s.key: s for s in PF.stats(station)}
    assert st["vpip"].verdict()[0] in ("solto demais", "too loose")
    assert st["fold_to_bet"].value == 0.1
    assert PF.advice(station)


def _population(seed, hands=1200):
    """Mesa de 6 bots de dificuldades variadas; resultado (bb) por faixa de habilidade."""
    rng = random.Random(seed)

    def newp():
        return ai.new_bot_player(rng.choice(ai.DIFFICULTIES), 1000, rng, set())

    t = T.Table([newp() for _ in range(6)], 5, 10, rng)
    low = high = 0.0
    n_low = n_high = 0
    for _ in range(hands):
        for i, p in enumerate(t.players):
            if p.stack == 0:
                t.players[i] = newp()
        t.start_hand()
        while not t.hand_over:
            d = t.players[t.to_act].ai.decide(t, t.to_act)
            t.act(d.action, d.amount_to)
        for i, p in enumerate(t.players):
            net = t.winners.get(i, 0) - p.total
            if p.ai.p.skill < 0.35:
                low += net
                n_low += 1
            elif p.ai.p.skill > 0.7:
                high += net
                n_high += 1
            p.ai.after_hand(net, t.bb, False)
        for i, p in enumerate(t.players):
            p.ai.observe_hand(t, i)
    return low, n_low, high, n_high


def test_skilled_bots_win_chips_from_weak_ones():
    from multiprocessing import Pool
    with Pool() as pool:
        res = pool.map(_population, range(1, 9))
    low = sum(r[0] for r in res) / max(1, sum(r[1] for r in res))
    high = sum(r[2] for r in res) / max(1, sum(r[3] for r in res))
    # ganho médio por mão: habilidosos ganham, fracos perdem (amostra grande para vencer a variância)
    assert high > low and low < 0


def test_difficulty_mix_is_realistic():
    from collections import Counter
    r = random.Random(4)
    n = 4000
    mix = {d: Counter(ai.make_personality(d, r).archetype for _ in range(n)) for d in ai.DIFFICULTIES}
    weak = ("fish", "station", "maniac", "conservative", "bluffer")
    share = {d: sum(mix[d][a] for a in weak) / n for d in mix}
    assert share["easy"] > 0.6 and 0 < share["pro"] < 0.12       # amadores existem, mas raros no topo
    assert share["easy"] > share["medium"] > share["hard"] > share["semipro"] > share["pro"]
    for a in weak:
        assert all(mix[d][a] > 0 for d in ("easy", "medium", "hard"))
    skills = {d: sum(ai.make_personality(d, r).skill for _ in range(300)) / 300 for d in ai.DIFFICULTIES}
    assert skills["easy"] < skills["medium"] < skills["hard"] < skills["semipro"] < skills["pro"]
    rates = {d: ai.Bot(ai.make_personality(d, r)).blunder_rate() for d in ("easy", "pro")}
    assert rates["easy"] > 5 * rates["pro"]


def _fake_showdown(target, hole, board, aggressive=True):
    from types import SimpleNamespace
    from pokertrainer import engine as E2
    target.hole = cs(hole)
    target.post_aggr = "river" if aggressive else ""
    observer = T.Player("Obs", 1000)
    observer.uid = 999
    score = E2.evaluate(target.hole + cs(board))
    return SimpleNamespace(players=[observer, target], showdown_hands={0: score - 1, 1: score}, board=cs(board))


def _bot(diff, seed=1):
    pers = ai.make_personality(diff, random.Random(seed))
    pers.attention = 1.0
    return ai.Bot(pers, random.Random(seed))


def test_memory_learns_slowly_and_resists_manipulation():
    target = T.Player("Você", 1000, is_hero=True)
    target.uid = 1
    target.hands = 40
    target.vpip = 10
    target.calls, target.bets_raises = 10, 12
    pro, easy = _bot("pro"), _bot("easy")
    base_pro = (pro.suspicion(target), pro.respect_shift(target))
    bluff = ("7c 2d", "As Kh 9s 5c 3h")       # carta alta depois de apostar no river
    t = _fake_showdown(target, *bluff)
    pro.observe_hand(t, 0)
    easy.observe_hand(t, 0)
    # um blefe isolado mexe pouco com o profissional (uma fração pequena do efeito máximo de 70%)
    one = pro.respect_shift(target) - base_pro[1]
    assert pro.suspicion(target) - base_pro[0] < 0.08
    assert abs(one) < 0.15 * ai.MAX_MEMORY_INFLUENCE
    for _ in range(7):
        pro.observe_hand(_fake_showdown(target, *bluff), 0)
    # um padrão repetido convence
    assert pro.suspicion(target) - base_pro[0] > 0.15
    assert pro.respect_shift(target) - base_pro[1] > 2.5 * one
    # e o efeito tem teto: a memória pesa no máximo 70% (o resto fica para o jogo e o acaso)
    assert pro.respect_shift(target) <= pro.p.influence <= ai.MAX_MEMORY_INFLUENCE
    # esquece aos poucos quando não vê mais nada
    high = pro.suspicion(target)
    from types import SimpleNamespace
    for _ in range(150):
        pro.observe_hand(SimpleNamespace(players=[target], showdown_hands={}, board=[]), 0)
    assert pro.suspicion(target) < high - 0.1
    # o fácil aprende com menos intensidade
    assert easy.p.learn < pro.p.learn and easy.p.prior < pro.p.prior


def test_value_hands_raise_fear():
    target = T.Player("X", 1000)
    target.uid = 2
    target.hands = 30
    target.vpip, target.calls, target.bets_raises = 9, 10, 10
    b = _bot("hard", 3)
    f0 = b.fear(target)
    for _ in range(5):
        b.observe_hand(_fake_showdown(target, "Ah Ad", "As Kh 9s 5c 3h"), 0)
    assert b.fear(target) > f0 + 0.1


def test_bots_learn_who_bluffs_at_a_real_table():
    rng = random.Random(9)
    maniac = ai.Bot(ai.make_personality("easy", rng), random.Random(1))
    maniac.p.archetype = "maniac"
    maniac.p.base.update(aggression=0.95, bluff=0.6, tightness=0.1, sticky=0.3)
    maniac.p.origin = dict(maniac.p.base)
    rock = ai.Bot(ai.make_personality("easy", rng), random.Random(2))
    rock.p.base.update(aggression=0.4, bluff=0.01, tightness=0.92)
    rock.p.origin = dict(rock.p.base)
    players = [T.Player("Maníaco", 100000, ai=maniac), T.Player("Pedra", 100000, ai=rock)]
    players += [ai.new_bot_player("pro", 100000, rng, set()) for _ in range(3)]
    t = T.Table(players, 5, 10, rng)
    for _ in range(500):
        for p in t.players:
            if p.stack <= 0:
                p.stack, p.sitting_out = 100000, False
        t.start_hand()
        while not t.hand_over:
            d = t.players[t.to_act].ai.decide(t, t.to_act)
            t.act(d.action, d.amount_to)
        for i, p in enumerate(t.players):
            p.ai.observe_hand(t, i)
    pros = [p.ai for p in players[2:]]
    m, r = players[0], players[1]
    assert sum(b.suspicion(m) for b in pros) > sum(b.suspicion(r) for b in pros)
    assert sum(b.fear(r) for b in pros) > sum(b.fear(m) for b in pros)



def test_memory_reaction_depends_on_personality():
    r = random.Random(5)
    by = {}
    for _ in range(400):
        p = ai.make_personality("medium", r)
        assert 0 < p.influence <= ai.MAX_MEMORY_INFLUENCE
        by.setdefault(p.archetype, []).append(p)
    avg = lambda arch, k: sum(getattr(p, k) for p in by[arch]) / len(by[arch])  # noqa: E731
    assert avg("rock", "fear_gain") > avg("maniac", "fear_gain")          # o retranqueiro se assusta fácil
    assert avg("maniac", "susp_gain") > avg("rock", "susp_gain")          # o maníaco acha que todos blefam
    assert avg("station", "influence") < avg("tag", "influence")          # o paga-tudo paga de qualquer jeito
    # mesma observação, reações diferentes
    target = T.Player("X", 1000)
    target.uid = 7
    target.hands = 30
    target.vpip, target.calls, target.bets_raises = 9, 10, 10
    scared, brave = _bot("medium", 11), _bot("medium", 12)
    scared.p.fear_gain, brave.p.fear_gain = 1.6, 0.4
    for b in (scared, brave):
        b.observe_hand(_fake_showdown(target, "Ah Ad", "As Kh 9s 5c 3h"), 0)
    assert scared.fear(target) > brave.fear(target)


def test_conservative_only_bets_with_50_percent():
    pers = ai.make_personality("easy", random.Random(2))
    pers.archetype = "conservative"
    bot = ai.Bot(pers, random.Random(3))
    t = make([1000, 1000])
    t.start_hand()
    while t.street == "preflop":
        t.act("call")
    seat = t.to_act
    t.players[seat].hole = cs("7c 2d")
    t.board = cs("Ah Kd 9s")
    bot._perceived = lambda *_: 0.3   # mão fraca: nunca aposta
    assert all(bot._postflop(t, seat).action == "check" for _ in range(50))


def test_pressure_only_from_hard_up():
    r = random.Random(8)
    easy = [ai.Bot(ai.make_personality("easy", r)) for _ in range(200)]
    semi = [ai.Bot(ai.make_personality("semipro", r)) for _ in range(300)]
    assert max(b.pressure() for b in easy) < 0.05
    assert sum(b.pressure() for b in semi) / 300 > 0.05
    # muito habilidosos (~0,9+) não pressionam por impulso
    top = [b for b in semi + [ai.Bot(ai.make_personality("pro", r)) for _ in range(300)] if b.p.skill >= 0.9]
    assert top and all(b.pressure() == 0 for b in top)
    # confiança aumenta a pressão de quem pressiona
    b = max((x for x in semi if 0.6 < x.p.skill < 0.8), key=lambda x: x.p.eff("aggression"))
    p0 = b.pressure()
    b.p.confidence = 0.8
    assert b.pressure() > p0


def test_bust_fear_depends_on_style_and_stack():
    r = random.Random(3)

    def bot(arch, diff):
        while True:
            p = ai.make_personality(diff, r)
            if p.archetype == arch:
                return ai.Bot(p, random.Random(1))

    rock, maniac = bot("rock", "easy"), bot("maniac", "easy")
    t = make([60, 5000, 5000])           # 6 big blinds
    assert rock.bust_fear(t, 0) > 0.4 and maniac.bust_fear(t, 0) < 0.15
    t2 = make([5000, 5000, 5000])
    assert rock.bust_fear(t2, 0) == 0


def test_bully_calls_short_stack_shove_wider():
    def call_rate(bully: float) -> float:
        calls = 0
        for k in range(300):
            t = make([3000, 120, 3000])          # jogador 1 está curto (12bb)
            t.dealer = 2
            t.start_hand()
            # posiciona a ação: o curto empurra, o bot decide
            while t.to_act != 1:
                t.act("fold" if t.to_act == 2 else "call")
            t.act("allin")
            seat = t.to_act
            if seat is None:
                continue
            t.players[seat].hole = cs("Kh 9d")
            pers = ai.make_personality("hard", random.Random(k))
            pers.bully = bully
            pers.survival = 0.0
            d = ai.Bot(pers, random.Random(k)).decide(t, seat)
            calls += d.action in ("call", "allin", "raise")
        return calls / 300

    assert call_rate(0.9) > call_rate(0.0) + 0.1


def _champion(rng):
    while True:
        p = ai.new_bot_player("pro", 1000, rng, set())
        if p.ai.champion:
            return p


def test_champion_only_at_pro_level():
    r = random.Random(1)
    for d in ("easy", "medium", "hard", "semipro"):
        assert all(ai.make_personality(d, r).archetype != "champion" for _ in range(3000))
    share = sum(ai.make_personality("pro", r).archetype == "champion" for _ in range(3000)) / 3000
    assert 0.02 < share < 0.12
    p = _champion(r)
    assert p.avatar == "👑" and p.ai.blunder_rate() == 0 and p.ai.pressure() == 0 and p.ai.p.skill > 0.98


def _champ_table(seed, hands=700):
    rng = random.Random(seed)

    def other():
        while True:
            q = ai.new_bot_player("pro", 1000, rng, set())
            if not q.ai.champion:
                return q

    t = T.Table([_champion(rng)] + [other() for _ in range(4)], 5, 10, rng)
    champ = rest = 0.0
    for _ in range(hands):
        for i, p in enumerate(t.players):
            if p.stack == 0:
                if i == 0:
                    p.stack, p.sitting_out = 1000, False
                else:
                    t.players[i] = other()
        t.start_hand()
        while not t.hand_over:
            d = t.players[t.to_act].ai.decide(t, t.to_act)
            t.act(d.action, d.amount_to)
        for i, p in enumerate(t.players):
            n = t.winners.get(i, 0) - p.total
            if i == 0:
                champ += n
            else:
                rest += n
            p.ai.after_hand(n, t.bb, False)
        for i, p in enumerate(t.players):
            p.ai.observe_hand(t, i)
    return champ / hands, rest / (4 * hands)


def test_champion_beats_a_table_of_pros():
    from multiprocessing import Pool
    with Pool() as pool:
        res = pool.map(_champ_table, range(1, 9))
    champ = sum(r[0] for r in res) / len(res)
    rest = sum(r[1] for r in res) / len(res)
    assert champ > 0 > rest
    # amostra pequena (5.600 mãos): só exige vantagem clara; em 36 mil mãos o Campeão faz ~+95 bb/100 e os pros ~−24
    assert champ / 10 * 100 > 40


def test_champion_is_balanced():
    """Tamanho da aposta não depende da força da mão; blefes perto da proporção equilibrada."""
    from collections import Counter
    rng = random.Random(5)
    champ = _champion(rng).ai
    sizes = {"value": Counter(), "bluff": Counter()}
    bets = Counter()
    for k in range(500):
        t = make([1000, 1000])
        t.rng = random.Random(1000 + k)       # uma mão diferente a cada vez
        t.start_hand()
        while t.street == "preflop":
            t.act("call")
        seat = t.to_act
        t.players[seat].ai = champ
        d = champ.decide(t, seat)
        if d.action in ("raise", "allin") and d.reason in ("value", "bluff"):   # semiblefes ficam de fora
            kind = d.reason
            frac = round((d.amount_to - t.current_bet) / t.pot, 1)
            sizes[kind][frac] += 1
            bets[kind] += 1
    assert bets["value"] > 20 and bets["bluff"] > 10
    share = {k: {f: c / bets[k] for f, c in sizes[k].items()} for k in sizes}
    for f in (0.3, 0.7):   # ⅓ e ⅔ do pote aparecem tanto em valor quanto em blefe, em proporções parecidas
        assert abs(share["value"].get(f, 0) - share["bluff"].get(f, 0)) < 0.25
    bluff_ratio = bets["bluff"] / (bets["value"] + bets["bluff"])
    assert 0.1 < bluff_ratio < 0.45        # perto da proporção equilibrada (~25–30% para ⅓–⅔ do pote)


def test_initial_perception_varies_by_bot_target_and_style():
    r = random.Random(4)
    targets = []
    for k in range(4):
        q = T.Player(f"Q{k}", 1000)
        q.uid = 500 + k
        targets.append(q)
    bots = [ai.Bot(ai.make_personality("medium", r), random.Random(k)) for k in range(40)]
    for b in bots:
        f = [b.fear(q) for q in targets]
        s_ = [b.suspicion(q) for q in targets]
        # cada bot vê cada jogador um pouco diferente (±5% individual)
        assert max(f) - min(f) <= 0.1 + 1e-9 and max(s_) - min(s_) <= 0.1 + 1e-9
        assert len({round(x, 4) for x in f}) > 1
    # bots diferentes têm impressões diferentes do mesmo jogador
    assert len({round(b.fear(targets[0]), 3) for b in bots}) > 10

    def avg(arch, kind):
        sel = []
        while len(sel) < 30:
            p = ai.make_personality("easy", r)
            if p.archetype == arch:
                sel.append(ai.Bot(p, random.Random(len(sel))))
        fn = (lambda b: b.fear(targets[0])) if kind == "fear" else (lambda b: b.suspicion(targets[0]))
        return sum(map(fn, sel)) / len(sel)

    # o estilo puxa a impressão inicial: o retranqueiro começa com mais medo, o maníaco com mais desconfiança
    assert avg("rock", "fear") > avg("maniac", "fear")
    assert avg("maniac", "susp") > avg("rock", "susp")


def test_initial_bias_fades_with_evidence():
    target = T.Player("X", 1000)
    target.uid = 77
    target.hands = 30
    target.vpip, target.calls, target.bets_raises = 9, 10, 10
    b = _bot("pro", 9)
    b.bias_fear = 0.1                       # impressão inicial forte
    rd = b.read_of(target)
    w0 = b._bias_weight(rd)
    for _ in range(20):
        b.observe_hand(_fake_showdown(target, "Ah Ad", "As Kh 9s 5c 3h"), 0)
    assert w0 == 1.0 and b._bias_weight(rd) < 0.5


def test_short_allin_raise_does_not_reopen_action():
    # 3 jogadores: A aposta, B vai all-in com pouco mais que a aposta (aumento incompleto), C paga.
    t = make([1000, 1000, 1000])
    t.start_hand()
    while t.street == "preflop":       # todos pagam e passam até o flop
        t.act("call") if not t.legal().can_check else t.act("check")
    first = t.to_act
    t.act("raise", 100)                # aposta 100
    second = t.to_act
    p = t.players[second]
    p.stack = 130                      # all-in de 130: aumento de 30 (< 100) = incompleto
    t.act("allin")
    third = t.to_act
    assert t.legal(third).can_raise    # ainda não tinha agido: pode aumentar
    t.act("call")
    # de volta a quem apostou primeiro: só paga ou larga
    assert t.to_act == first
    lg = t.legal(first)
    assert lg.to_call == 30 and not lg.can_raise


def test_big_blind_ante_goes_to_pot():
    t = T.Table([T.Player(f"P{i}", 1000, is_hero=i == 0) for i in range(4)], 50, 100, random.Random(5), ante=100)
    t.start_hand()
    assert t.pot == 50 + 100 + 100
    bb = [p for p in t.players if p.bet == 100][0]
    assert bb.total == 200 and bb.stack == 800
    lg = t.legal()
    assert lg.to_call == 100            # a ante não conta como aposta
    while not t.hand_over:
        t.act("fold")
    assert sum(p.stack for p in t.players) == 4000


def test_losers_can_muck_at_showdown():
    t = make([1000, 1000, 1000])
    t.start_hand()
    t.players[0].hole, t.players[1].hole, t.players[2].hole = cs("As Ah"), cs("7c 2d"), cs("Ks Kh")
    board = cs("Qd 9s 5c 3h 4d")
    used = set(cs("As Ah 7c 2d Ks Kh")) | set(board)
    burn = [c for c in range(52) if c not in used]
    # o baralho sai do fim: carta queimada antes de cada rua
    t.deck = burn[:-3] + [board[4], burn[-3], board[3], burn[-2], board[2], board[1], board[0], burn[-1]]
    while not t.hand_over:
        t.act("call") if not t.legal().can_check else t.act("check")
    assert set(t.showdown_hands) == {0, 1, 2}
    # quem mostrou: o primeiro na ordem e quem empata/vence; o 7-2 perde e descarta
    assert 0 in t.shown and 1 not in t.shown


def test_assistant_ranges_follow_the_action():
    from pokertrainer import ranges as R
    t = make([1000, 1000, 1000])
    t.start_hand()
    # quem age primeiro aumenta; a faixa dele fica mais forte do que a de quem só está no big blind
    while t.to_act != 0 and not t.hand_over:
        seat = t.to_act
        t.act("raise", 30) if t.players[seat].bets_raises == 0 and t.current_bet == 10 else t.act("call")
    if t.hand_over or t.to_act != 0:
        return
    ranges = R.table_ranges(t, 0)
    distinct = [len(set(r)) for r in ranges]
    raiser = next(i for i in t.seats_in_hand() if i != 0 and t.players[i]._pfr_hand)
    k = [i for i in t.seats_in_hand() if i != 0].index(raiser)
    # quem aumentou não tem qualquer mão: a faixa dele é bem menor que as 1326 combinações
    assert distinct[k] < 1326 * R.open_pct(t.position_of(raiser)) / 100 + 60
