import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from pokertrainer import settings as S


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("qs") / "s.ini")
    orig = S.app_settings
    S.app_settings = lambda: QSettings(path, QSettings.IniFormat)
    app = QApplication.instance() or QApplication([])
    from pokertrainer.gui.main_window import MainWindow
    w = MainWindow()
    w.show()
    yield w
    w.close()
    S.app_settings = orig


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(cond, timeout=10000):
    waited = 0
    while not cond() and waited < timeout:
        wait(50)
        waited += 50
    assert cond()


@pytest.mark.parametrize("mode_idx", [0, 1, 2])
@pytest.mark.parametrize("n_opp", [1, 9])
def test_full_round(win, mode_idx, n_opp):
    S.put("opponents", n_opp)
    S.put("animations", True)
    mode = S.MODES[mode_idx]
    win.start_mode(mode)
    g = win.game
    assert win.stack.currentWidget() is g
    assert len(g.seats) == n_opp
    # confirma imediatamente (antes do cálculo terminar) -> revela quando ficar pronto
    g.bar.setValue(40)
    g._on_action()
    wait_for(lambda: g.revealed)
    wait(1200)  # deixa as animações terminarem
    assert all(c._face_up for c in g.board_cards)
    assert all(c._face_up for s in g.seats for c in s.cards)
    st = S.load_stats(mode.key)
    assert st.rounds >= 1
    # próxima mão várias vezes rapidamente (cancela cálculos antigos)
    for _ in range(5):
        g._on_action() if g.revealed else g.new_round()
    wait_for(lambda: g.eq is not None)
    assert not g.revealed


def test_navigation(win):
    for k in ("table", "tips", "settings", "game", "home"):
        win.go(k)
    assert win.stack.currentWidget() is win.home
    win.go("game")  # sem jogo ativo volta ao início
    assert win.stack.currentWidget() is win.home


def test_random_opponents(win):
    S.put("random_opponents", False)
    S.put("opponents", 3)
    win.start_mode(S.MODES[0])
    g = win.game
    assert g.n_opp == 3 and not g.rand_btn.isChecked()
    g.rand_btn.setChecked(True)  # antes do palpite: já sorteia uma nova mão
    assert S.get("random_opponents")
    seen = set()
    for _ in range(60):
        g.new_round()
        assert 1 <= g.n_opp <= S.MAX_OPPONENTS and len(g.seats) == g.n_opp
        assert str(g.n_opp) in g.opp_btn.text()
        seen.add(g.n_opp)
    assert len(seen) >= 5
    g.set_opponents(2)  # escolher um número fixo desliga o aleatório
    assert g.n_opp == 2 and not g.rand_btn.isChecked() and not S.get("random_opponents")
    win.go("settings")
    assert win.settings_page.opp.value() == 2 and not win.settings_page.rand.isChecked()


def test_language_switch_keeps_hand(win):
    from pokertrainer import i18n
    S.put("random_opponents", False)
    S.put("opponents", 2)
    win.start_mode(S.MODES[1])
    g = win.game
    wait_for(lambda: g.eq is not None)
    g.bar.setValue(37)
    g._on_action()
    assert g.revealed
    rounds = S.load_stats("flop").rounds
    deal = g.deal
    win.set_language("en")
    g2 = win.game
    assert i18n.lang() == "en" and g2 is not g
    assert g2.deal is deal and g2.revealed and g2.bar.value() == 37
    assert S.load_stats("flop").rounds == rounds  # reexibir não conta de novo
    assert g2.action_btn.text().startswith("Next hand")
    assert win.stack.currentWidget() is g2
    assert "Settings" in win.sidebar.nav_buttons["settings"].text()
    win.set_language("pt")
    assert i18n.lang() == "pt" and win.game.deal is deal
    assert win.game.action_btn.text().startswith("Próxima")


def test_deck_view(win):
    S.put("random_opponents", False)
    S.put("opponents", 3)
    win.start_mode(S.MODES[2])  # turn: 2 + 4 conhecidas
    g = win.game
    assert g.deck_btn.remaining == 46
    g.deck_btn.click()
    dv = g.deck_view
    assert dv.isVisible()
    dimmed = {c for c, w in dv.cards.items() if w.dimmed}
    assert dimmed == set(g.deal.hero + g.deal.visible_board)
    dv.hide()
    wait_for(lambda: g.eq is not None)
    g._on_action()
    assert g.deck_btn.remaining == 52 - 2 - 5 - 6
    g.show_deck()
    assert sum(w.dimmed for w in dv.cards.values()) == 13
    dv.hide()


def test_pot_odds_and_history(win):
    S.reset_stats()
    S.put("random_opponents", False)
    S.put("opponents", 2)
    S.put("opp_range", 100)
    win.start_mode(S.MODE_BY_KEY["potodds"])
    g = win.game
    assert g.spot is not None and g.deal.visible in (3, 4)
    assert g.call_btn.isVisible() and not g.action_btn.isVisible()
    g._on_action()  # Enter não decide no modo pot odds
    assert not g.revealed
    g._decide(True)
    wait_for(lambda: g.revealed)
    st = S.load_stats("potodds")
    assert st.decisions == 1 and st.good_decisions in (0, 1)
    h = S.load_history()
    assert len(h) == 1 and h[0]["pot"] and h[0]["called"] is True and h[0]["type"].startswith("pp_")
    # revisão reabre a mesma mão sem contar de novo
    win.go("stats")
    assert win.stats_page.hist.rowCount() == 1
    win.stats_page._review_row(0)
    assert win.game.revealed and win.game.deal.hero == h[0]["hero"] and win.game.spot.bet == h[0]["pot"][1]
    assert len(S.load_history()) == 1 and S.load_stats("potodds").decisions == 1


def test_ranges_and_focus(win):
    from pokertrainer import coach
    S.put("random_opponents", False)
    S.put("opponents", 3)
    win.start_mode(S.MODES[0])
    g = win.game
    g.set_range(8)
    labels = coach.range_labels(8)
    for _ in range(10):
        g.new_round()
        assert all(E_label(o) in labels for o in g.deal.opponents)
    wait_for(lambda: g.eq is not None and g.eq.vs_random is not None)
    g.set_range(100)
    win.focus_training("pf_pair_lo")
    for _ in range(5):
        assert coach.hand_type(win.game.deal) == "pf_pair_lo"
        win.game.new_round()
    win.focus_training("pp_draw")
    assert win.game.mode.key in ("flop", "turn", "potodds")
    assert coach.hand_type(win.game.deal) == "pp_draw"
    win.game.set_focus(None)


def E_label(cards):
    from pokertrainer import engine as E
    return E.starting_hand_label(*cards)


def _play_hand(pg, action="call", timeout=30000):
    """Joga uma mão inteira (o jogador sempre faz `action`) até a tela de fim de mão."""
    waited = 0
    while not (pg.table.hand_over and pg.next_btn.isVisible()):
        t = pg.table
        if t.to_act == 0 and not t.hand_over and not pg._queue and pg.call_btn.isEnabled():
            pg.hero_act(action)
        wait(20)
        waited += 20
        assert waited < timeout, "mão travou"


def test_play_game(win):
    S.put("random_opponents", False)
    S.put("play_opponents", 3)
    S.put("play_speed", "fast")
    S.put("show_personality", True)
    S.put("play_assist", True)
    S.put("animations", False)
    S.put("play_autonext", False)
    win.start_mode(S.MODE_BY_KEY["play"])
    pg = win.play
    assert win.stack.currentWidget() is pg and len(pg.seats) == 3
    assert not pg.area.felt
    # o número de oponentes do jogo é separado do dos modos de treino
    S.put("opponents", 7)
    pg.next_hand()
    assert len(pg.seats) == 3
    for _ in range(5):
        _play_hand(pg)
        t = pg.table
        # depois da animação o pote foi pago: nenhuma ficha na mesa e stacks visíveis = stacks reais
        assert pg.paid and not pg.hidden_win and not pg.pot_chip.isVisible()
        assert all(not c.isVisible() for c in pg.chips)
        assert pg.session["hands"] >= 1 and pg.log_lines
        pg.next_hand()
    # pausa: nada anda enquanto pausado
    pg.toggle_pause()
    hand, n_log = pg.table.hand_no, len(pg.log_lines)
    wait(800)
    assert pg.table.hand_no == hand and len(pg.log_lines) == n_log
    pg.toggle_pause()
    # pré-ação "passar/desistir": o app age sozinho na vez do jogador
    _play_hand(pg, "fold")
    pg.next_hand()
    pg._clear_preaction()
    pg.pre_btns["checkfold"].setChecked(True)
    pg._set_preaction("checkfold")
    if pg.table.to_act == 0 and not pg._queue:
        pg._apply_preaction()   # a vez já era do jogador quando a pré-ação foi marcada
    waited = 0
    while not pg.table.hand_over and waited < 30000:
        if pg.table.to_act == 0 and not pg._queue and pg.call_btn.isEnabled():
            # a pré-ação já teria agido; ela vale só para a rua em que foi marcada
            assert pg.preaction is None
            pg.hero_act("fold")
        if not pg.hero.in_hand:
            pg.skip_hand()   # você saiu: pula o resto da mão
        wait(20)
        waited += 20
    wait_for(lambda: pg.next_btn.isVisible(), timeout=30000)
    # trocar o idioma mantém a partida
    hand = pg.table.hand_no
    win.set_language("en")
    assert win.playing and win.play.table.hand_no == hand
    win.set_language("pt")
    win.go("home")
    assert not win.playing


def test_menu_groups_training_and_game_modes(win):
    from pokertrainer import ai
    win.go("home")
    sb = win.sidebar
    assert [m.key for m in S.MODES if not m.is_play] == ["preflop", "flop", "turn", "potodds"]
    assert [m.key for m in S.MODES if m.is_play] == ["play", "tournament"]
    assert set(sb.mode_buttons) == {m.key for m in S.MODES}
    assert [ai.tournament_rounds(d) for d in ai.DIFFICULTIES] == [3, 3, 5, 5, 6]


def _knock_out_to(pg, survivors):
    """Tira as fichas de bots até sobrarem `survivors` jogadores (eles ficam de fora a partir da próxima mão)."""
    alive = [p for p in pg.table.players[1:] if p.stack > 0]
    for p in alive[:len(alive) + 1 - survivors]:
        p.stack = 0


def test_tournament_rounds(win):
    S.put("difficulty", "easy")
    S.put("play_opponents", 3)
    S.put("play_speed", "fast")
    S.put("animations", False)
    S.put("play_autonext", False)
    before = S.load_play_stats()
    win.sidebar.mode_buttons["tournament"].click()
    pg = win.play
    ss = pg.session
    assert win.playing and pg.tournament and win.stack.currentWidget() is pg
    assert ss["round"] == 1 and ss["rounds"] == 3 and ss["field"] == 16 and pg.table.bb == 10
    assert "RODADA 1/3" in pg.info.text() and "3 rodadas" in win.sidebar.analysis.text()
    assert pg.area.felt and pg.area.table_rect.width() > 100     # mesa verde só no torneio
    # mesa de 4: passam 2. Duas eliminações e o jogador avança
    for rnd in (1, 2):
        _play_hand(pg, "fold")
        if not ss["round_done"]:   # (raro) a mesa pode ter se resolvido sozinha
            _knock_out_to(pg, 2)
            pg.next_hand()
            _play_hand(pg, "fold")
        assert ss["round_done"] and not pg.game_over
        assert ("mesa final" if rnd == 2 else "rodada 2") in pg.prompt.text()
        assert ("Mesa final" if rnd == 2 else "Próxima rodada") in pg.next_btn.text()
        pg.next_hand()             # Enter/auto não pulam a troca de mesa
        assert ss["round"] == rnd
        pg._next_clicked()
        assert ss["round"] == rnd + 1 and not ss["round_done"] and ss["round_hands"] == 1
        assert pg.table.bb == 10 and sum(p.stack + p.total for p in pg.table.players) == 4000
    assert pg.final_table and "MESA FINAL" in pg.info.text()
    # trocar o idioma mantém a rodada
    win.set_language("en")
    pg = win.play
    assert pg.session["round"] == 3 and "FINAL TABLE" in pg.info.text()
    win.set_language("pt")
    pg = win.play
    _play_hand(pg, "fold")
    pg._tournament_step(busted=False, others_alive=0, replay=False)
    assert pg.game_over and "campeão" in pg.prompt.text() and "Novo torneio" in pg.next_btn.text()
    d = S.load_play_stats()
    assert d["tournaments"] == before["tournaments"] + 1 and d["tourn_wins"] == before["tourn_wins"] + 1
    assert d["best_place"] == 1
    # novo torneio; eliminado na 1ª rodada em 4º da mesa = 13º de 16
    pg._next_clicked()
    assert pg.session["round"] == 1 and not pg.game_over
    pg._tournament_step(busted=True, others_alive=3, replay=False)
    assert pg.game_over and "13º lugar de 16" in pg.prompt.text()
    win.go("home")


def test_play_stats_accumulate(win):
    S.reset_stats()
    S.put("play_opponents", 2)
    S.put("play_speed", "fast")
    S.put("animations", False)
    win.start_mode(S.MODE_BY_KEY["play"])
    pg = win.play
    for _ in range(4):
        _play_hand(pg, "call")
        pg.next_hand()
    _play_hand(pg, "call")
    d = S.load_play_stats()
    assert d["hands"] == 5 and d["sessions"] == 1
    assert d["vpip"] == pg.hero.vpip and d["calls"] == pg.hero.calls
    assert len(S.load_play_curve()) == 5
    assert abs(sum(S.load_play_curve()) * 10 - d["net"]) < 1e-6   # blinds 5/10
    # HUD do jogador na mesa e no painel lateral
    assert "VPIP" in pg.hero_seat.hud.text()
    assert "VPIP" in win.sidebar.profile_lbl.text() and win.sidebar.profile_box.isVisible()
    # aba Jogo simulado em Estatísticas
    win.go("stats")
    tab = win.stats_page.play_tab
    assert tab.t_hands[1].text() == "5" and tab.table.rowCount() == 8
    assert tab.chart.cum and len(tab.chart.cum) == 5
    # nova partida soma às mesmas estatísticas
    win.start_mode(S.MODE_BY_KEY["play"])
    _play_hand(win.play, "fold")
    assert S.load_play_stats()["hands"] == 6 and S.load_play_stats()["sessions"] == 2
    win.go("home")


def test_play_players_menu(win):
    S.put("play_opponents", 2)
    S.put("opponents", 6)
    win.start_mode(S.MODE_BY_KEY["play"])
    pg = win.play
    assert len(pg.seats) == 2 and pg.players_btn.text().endswith("2")
    pg.set_players(5)
    assert len(pg.seats) == 5 and S.get("play_opponents") == 5 and S.get("opponents") == 6
    win.go("settings")
    assert win.settings_page.play_opp.value() == 5 and win.settings_page.opp.value() == 6
    win.go("home")


def test_play_sounds_are_triggered(win):
    from pokertrainer.gui import sound
    S.put("play_opponents", 2)
    S.put("play_speed", "fast")
    S.put("animations", False)
    sound.player.played.clear()
    win.start_mode(S.MODE_BY_KEY["play"])
    _play_hand(win.play, "call")
    played = set(sound.player.played)
    assert {"deal", "collect"} <= played
    assert played & {"call", "check", "bet", "fold", "allin"}
    assert sound.player.muted        # testes ficam sempre mudos
    win.go("home")
