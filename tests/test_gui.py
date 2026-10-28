import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication

from pokertrainer import settings as S


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("qs") / "s.ini")
    os.environ["POKERTRAINER_DATA"] = str(tmp_path_factory.mktemp("data"))
    orig = S.app_settings
    S.app_settings = lambda: QSettings(path, QSettings.IniFormat)
    _app = QApplication.instance() or QApplication([])  # noqa: F841 (mantém a aplicação viva)
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


@pytest.mark.parametrize("mode_key", ["preflop", "flop", "turn", "river"])
@pytest.mark.parametrize("n_opp", [1, 9])
def test_full_round(win, mode_key, n_opp):
    S.put("random_opponents", False)
    S.put("opponents", n_opp)
    S.put("animations", True)
    mode = S.MODE_BY_KEY[mode_key]
    win.start_mode(mode)
    g = win.game
    assert win.stack.currentWidget() is g
    assert len(g.seats) == n_opp and g.deal.visible == mode.visible
    assert all(b.isVisible() for b in g.act_btns.values()) and not g.next_btn.isVisible()
    # sem aposta não dá para desistir
    assert g.act_btns["fold"].isEnabled() == g.spot.can_fold
    before = S.load_stats(mode.key).hands
    # decide imediatamente (antes do cálculo terminar) -> revela quando ficar pronto
    g._act("passive")
    wait_for(lambda: g.revealed)
    wait(1200)  # deixa as animações terminarem
    assert all(c._face_up for c in g.board_cards)
    assert all(c._face_up for s in g.seats for c in s.cards)
    assert g.next_btn.isVisible() and not any(b.isVisible() for b in g.act_btns.values())
    st = S.load_stats(mode.key)
    assert st.hands == before + 1 and 0 <= st.good <= st.hands
    assert "Melhor jogada" in win.sidebar.analysis.text()
    # o botão "Próxima mão" (clique de verdade) e o Enter dão uma nova mão
    old = g.deal
    g.next_btn.click()
    assert not g.revealed and g.deal is not old and g.next_btn.isHidden()
    g._act("passive")
    wait_for(lambda: g.revealed)
    g.keyPressEvent(_key("Return"))
    assert not g.revealed
    # próxima mão várias vezes rapidamente (cancela cálculos antigos)
    for _ in range(5):
        g.new_round()
    wait_for(lambda: g.eq is not None)
    assert not g.revealed


def test_navigation(win):
    for k in ("help", "table", "tips", "settings", "game", "home"):
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
    g.rand_btn.setChecked(True)  # antes da decisão: já sorteia uma nova mão
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
    g._act("aggressive")
    assert g.revealed
    action = g.action
    hands = S.load_stats("flop").hands
    deal = g.deal
    win.set_language("en")
    g2 = win.game
    assert i18n.lang() == "en" and g2 is not g
    assert g2.deal is deal and g2.revealed and g2.action == action
    assert S.load_stats("flop").hands == hands  # reexibir não conta de novo
    assert g2.next_btn.text().startswith("Next hand")
    assert win.stack.currentWidget() is g2
    assert "Settings" in win.sidebar.nav_buttons["settings"].text()
    win.set_language("pt")
    assert i18n.lang() == "pt" and win.game.deal is deal
    assert win.game.next_btn.text().startswith("Próxima")


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
    g._act("passive")
    assert g.deck_btn.remaining == 52 - 2 - 5 - 6
    g.show_deck()
    assert sum(w.dimmed for w in dv.cards.values()) == 13
    dv.hide()


def test_decision_history_and_review(win):
    from pokertrainer import decision as D
    S.reset_stats()
    S.put("random_opponents", False)
    S.put("opponents", 2)
    S.put("opp_range", 100)
    win.start_mode(S.MODE_BY_KEY["flop"])
    g = win.game
    # força uma aposta para pagar
    g.new_round(spot=None)
    while not g.spot.facing_bet:
        g.new_round()
    assert g.act_btns["fold"].isEnabled() and "Pagar" in g.act_btns["passive"].text()
    assert all("passou" not in s.info.text() for s in g.seats)
    g.keyPressEvent(_key("Return"))   # Enter não decide
    assert not g.revealed
    g.keyPressEvent(_key("C"))        # C = pagar
    wait_for(lambda: g.revealed)
    assert g.action == D.CALL
    st = S.load_stats("flop")
    assert st.hands == 1 and st.points in (0, 50, 70, 100)
    h = S.load_history()
    assert len(h) == 1 and h[0]["act"] == "call" and h[0]["spot"][2] == g.spot.bet
    assert h[0]["type"].startswith("pp_") and h[0]["q"] in ("best", "ok", "mistake")
    # revisão reabre a mesma mão sem contar de novo
    win.go("stats")
    assert win.stats_page.hist.rowCount() == 1 and win.stats_page.t_hands[1].text() == "1"
    win.stats_page._review_row(0)
    assert win.game.revealed and win.game.deal.hero == h[0]["hero"] and win.game.spot.bet == h[0]["spot"][2]
    assert win.game.action == "call"
    assert len(S.load_history()) == 1 and S.load_stats("flop").hands == 1


def _key(name):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    return QKeyEvent(QEvent.KeyPress, getattr(Qt, f"Key_{name}"), Qt.NoModifier)


def test_home_has_no_mode_cards(win):
    from PySide6.QtWidgets import QPushButton
    win.go("home")
    assert not win.home.findChildren(QPushButton)


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
    assert win.game.mode.key in ("flop", "turn")
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
    assert pg.area.felt and pg.area.label == "CASH GAME"      # mesa verde também no cash game
    # o número de oponentes do jogo é separado do dos modos de treino
    S.put("opponents", 7)
    pg.next_hand()
    assert len(pg.seats) == 3
    for _ in range(5):
        _play_hand(pg)
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
    assert [m.key for m in S.MODES if not m.is_play] == ["preflop", "flop", "turn", "river"]
    assert [m.key for m in S.MODES if m.is_play] == ["play", "tournament"]
    assert set(sb.mode_buttons) == {m.key for m in S.MODES}
    # modos de jogo em cima, modos de treino embaixo, todos direto no menu
    keys = sorted(sb.mode_buttons, key=lambda k: sb.mode_buttons[k].y())
    assert keys == ["play", "tournament", "preflop", "flop", "turn", "river"]
    assert [ai.tournament_rounds(d) for d in ai.DIFFICULTIES] == [3, 3, 5, 5, 6]


def _knock_out_to(pg, survivors):
    """Tira as fichas de bots até sobrarem `survivors` jogadores (eles ficam de fora a partir da próxima mão)."""
    alive = [p for p in pg.table.players[1:] if p.stack > 0]
    for p in alive[:len(alive) + 1 - survivors]:
        p.stack = 0


def test_tournament_rounds(win):
    S.put("difficulty", "pro")          # a dificuldade do cash game não muda a do torneio
    S.put("play_opponents", 3)
    S.put("play_speed", "fast")
    S.put("animations", False)
    S.put("play_autonext", False)
    before = S.load_play_stats()
    before_easy = S.load_tourn_stats("easy")
    # entrar no torneio abre a escolha de dificuldade, com rodadas e títulos de cada uma
    win.sidebar.mode_buttons["tournament"].click()
    lobby = win.tourn_page
    assert not win.playing and win.stack.currentWidget() is lobby
    assert set(lobby.cards) == {"easy", "medium", "hard", "semipro", "pro"}
    assert "3 rodadas · 16 jogadores" in lobby.cards["easy"].rounds.text()
    assert "6 rodadas · 128 jogadores" in lobby.cards["pro"].rounds.text()
    lobby.cards["easy"].click()
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
        my_stack = pg.hero.stack
        hands = ss["hands"]
        pg._next_clicked()
        assert ss["round"] == rnd + 1 and not ss["round_done"] and ss["round_hands"] == 1
        # você leva as suas fichas; os adversários chegam com stacks em torno da média da fase
        assert pg.hero.stack + pg.hero.total == my_stack
        avg = 1000 * 2 ** rnd
        assert all(0.4 * avg <= p.stack + p.total <= 1.8 * avg for p in pg.table.players[1:])
        # o relógio dos blinds continua (mãos do torneio inteiro)
        sb, bb, ante, _left = __import__("pokertrainer.ai", fromlist=["x"]).blinds_for(hands)
        assert (pg.table.sb, pg.table.bb, pg.table.ante) == (sb, bb, ante)
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
    te = S.load_tourn_stats("easy")
    assert te["played"] == before_easy["played"] + 1 and te["wins"] == before_easy["wins"] + 1 and te["best"] == 1
    assert S.get("difficulty") == "pro"
    assert d["best_place"] == 1
    # fim do torneio: "Novo torneio" volta ao lobby, que mostra o título conquistado
    pg._next_clicked()
    lobby = win.tourn_page               # (a troca de idioma acima reconstruiu as telas)
    assert not win.playing and win.stack.currentWidget() is lobby
    assert "🏆" in lobby.cards["easy"].trophies.text() and "título" in lobby.cards["easy"].record.text()
    assert "título" in lobby.total.text()
    # novo torneio; eliminado na 1ª rodada em 4º da mesa = 13º de 16
    lobby.cards["easy"].click()
    pg = win.play
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


def test_how_to_play_page(win):
    win.sidebar.nav_buttons["help"].click()
    assert win.stack.currentWidget() is win.help_page
    text = win.help_page.browser.toPlainText()
    for word in ("Ranking das mãos", "Straight flush", "Carta alta", "Torneio", "Cash game", "potes paralelos"):
        assert word in text
    win.go("home")


def test_action_colors_and_folded_names(win):
    from pokertrainer.gui import play_page as P
    S.put("play_opponents", 3)
    S.put("play_speed", "fast")
    S.put("animations", False)
    win.start_mode(S.MODE_BY_KEY["play"])
    pg = win.play
    _play_hand(pg, "fold")
    assert P.action_color("check") == "#3ddc84" and P.action_color("raise") == P.action_color("bet") == "#f5c542"
    assert P.action_color("fold") == "#7f8c88" and P.action_color("call") == P.DEFAULT_ACTION_COLOR
    t = pg.table
    for i, p in enumerate(t.players):
        sw = pg._seat_widget(i)
        if p.folded and not (i in t.showdown_hands):
            assert P.FADED in sw.name.styleSheet()
            assert sw.action._color == "#7f8c88"
        elif not p.folded:
            assert P.FADED not in sw.name.styleSheet()
        if p.last_action == "check" and i not in t.showdown_hands:
            assert sw.action._color == "#3ddc84"
    win.go("home")


def test_s_key_skips_bots_and_goes_to_next_hand(win):
    S.put("play_opponents", 5)
    S.put("play_speed", "slow")
    S.put("animations", False)
    win.start_mode(S.MODE_BY_KEY["play"])
    pg = win.play
    # desiste na primeira vez e aperta S: a mão termina sem esperar os bots
    wait_for(lambda: pg.table.to_act == 0 and not pg._queue and pg.call_btn.isEnabled() or pg.table.hand_over,
             timeout=30000)
    if not pg.table.hand_over:
        pg.hero_act("fold")
        wait_for(lambda: pg.skip_btn.isVisible() or pg.next_btn.isVisible(), timeout=10000)
        if pg.skip_btn.isVisible():
            pg.keyPressEvent(_key("S"))
    wait_for(lambda: pg.table.hand_over and pg.next_btn.isVisible(), timeout=5000)
    # S na tela de fim de mão = próxima mão
    hand = pg.table.hand_no
    pg.keyPressEvent(_key("S"))
    assert pg.table.hand_no == hand + 1
    S.put("play_speed", "fast")
    win.go("home")


def test_support_pages_have_close_button(win):
    from PySide6.QtWidgets import QSlider
    # aberto a partir de um treino, Fechar volta para a mesa do treino
    win.start_mode(S.MODE_BY_KEY["flop"])
    pages = {"help": win.help_page, "table": win.table, "stats": win.stats_page, "tips": win.tips,
             "settings": win.settings_page}
    for key, page in pages.items():
        win.go(key)
        assert win.stack.currentWidget() is page
        from PySide6.QtWidgets import QPushButton
        assert any("Fechar" in b.text() and b.isVisible() for b in page.findChildren(QPushButton)), key
        page.closeRequested.emit()
        assert win.stack.currentWidget() is win.game, key
    # de uma página de apoio para outra: Fechar ainda volta para a mesa
    win.go("tips")
    win.go("settings")
    win.settings_page.closeRequested.emit()
    assert win.stack.currentWidget() is win.game
    # sem ajuste de desfoque nas configurações (o volume continua)
    assert len(win.settings_page.findChildren(QSlider)) == 1
    win.go("home")
    win.go("help")
    win.help_page.closeRequested.emit()
    assert win.stack.currentWidget() is win.home


def test_table_panels_collapse_and_space_for_next_hand(win):
    S.put("play_opponents", 2)
    S.put("play_speed", "fast")
    S.put("animations", False)
    S.put("play_sidebar", True)
    S.put("play_log", True)
    win.sidebar.mode_buttons["tournament"].click()
    win.tourn_page.cards["easy"].click()
    pg = win.play
    assert win.sidebar.isVisible() and pg.log_panel.isVisible()
    # fecha o histórico e o menu lateral para dar espaço à mesa
    area_w = pg.area.width()
    pg.log_btn.click()
    pg.menu_btn.click()
    wait(50)
    assert not pg.log_panel.isVisible() and not win.sidebar.isVisible()
    assert not S.get("play_log") and not S.get("play_sidebar")
    assert pg.area.width() > area_w
    # em outras telas o menu volta; na mesa continua recolhido
    win.go("settings")
    assert win.sidebar.isVisible()
    win.close_page()
    assert win.stack.currentWidget() is pg and not win.sidebar.isVisible()
    # reabre
    pg.menu_btn.click()
    pg.log_btn.click()
    assert win.sidebar.isVisible() and pg.log_panel.isVisible()
    # o Espaço vai para a próxima mão (os botões não roubam o foco)
    from PySide6.QtWidgets import QPushButton
    assert all(b.focusPolicy() == Qt.NoFocus for b in pg.findChildren(QPushButton))
    _play_hand(pg, "fold")
    if not pg.game_over and not pg.session.get("round_done"):
        assert "Espaço" in pg.next_btn.text()
        hand = pg.table.hand_no
        pg.keyPressEvent(_key("Space"))
        assert pg.table.hand_no == hand + 1
    win.go("home")


def test_home_welcome_text(win):
    from PySide6.QtWidgets import QLabel
    win.go("home")
    texts = " ".join(lb.text() for lb in win.home.findChildren(QLabel))
    assert "Bem-vindo ao Pro Poker Trainer" in texts and "se adaptam ao seu estilo" in texts


def test_preaction_shortcuts(win):
    S.put("play_opponents", 5)
    S.put("play_speed", "slow")
    S.put("animations", False)
    win.start_mode(S.MODE_BY_KEY["play"])
    pg = win.play
    wait_for(lambda: pg.pre_box.isVisible() or pg.table.hand_over, timeout=30000)
    if pg.pre_box.isVisible():
        pg.keyPressEvent(_key("A"))
        assert pg.preaction == "callany" and pg.pre_btns["callany"].isChecked()
        pg.keyPressEvent(_key("F"))
        assert pg.preaction == "checkfold" and not pg.pre_btns["callany"].isChecked()
        pg.keyPressEvent(_key("F"))           # de novo: desmarca
        assert pg.preaction is None
        pg.keyPressEvent(_key("C"))
        assert pg.preaction == "check"
    assert "Histórico" in pg.log_btn.text() and "📜" not in pg.log_btn.text()
    S.put("play_speed", "fast")
    win.go("home")


def test_table_ratio_and_folded_look(win):
    from pokertrainer.gui import play_page as P
    S.put("play_opponents", 5)
    S.put("play_speed", "fast")
    S.put("animations", False)
    win.start_mode(S.MODE_BY_KEY["play"])
    pg = win.play
    for size in ((1360, 860), (1900, 1000), (1080, 720)):
        win.resize(*size)
        wait(100)
        r = pg.area.table_rect
        assert r.width() / (r.height() - P.TABLE_PAD_H) <= P.TABLE_RATIO + 0.01
    win.resize(1360, 860)
    _play_hand(pg, "fold")
    t = pg.table
    for i, p in enumerate(t.players):
        sw = pg._seat_widget(i)
        assert "255,255,255,0.75" not in sw.styleSheet()      # sem borda branca: só a amarela de quem joga
        if p.folded:
            assert all(c.dimmed and c.dim_alpha == 205 for c in sw.cards)   # cartas quase pretas
            assert P.FADED in sw.stack.styleSheet()        # fichas também apagadas
    win.go("home")


def test_hand_history_export_pokerstars(win, tmp_path):
    from pokertrainer import handhistory as HH
    S.put("play_opponents", 2)
    S.put("play_speed", "fast")
    S.put("animations", False)
    if HH.history_path().exists():
        HH.history_path().unlink()
    win.start_mode(S.MODE_BY_KEY["play"])
    pg = win.play
    for _ in range(3):
        _play_hand(pg, "call")
        pg.next_hand()
    text = HH.history_path().read_text(encoding="utf-8")
    assert text.count("PokerStars Hand #") == 3
    for part in ("Hold'em No Limit (5/10)", "is the button", "posts small blind 5", "posts big blind 10",
                 "*** HOLE CARDS ***", "Dealt to Você [", "*** SUMMARY ***", "collected"):
        assert part in text, part
    win.go("stats")
    out = tmp_path / "maos.txt"
    win.stats_page.play_tab._export(str(out))
    assert out.read_text(encoding="utf-8") == text and "3 mãos" in win.stats_page.play_tab.export_info.text()
    win.go("home")


def test_show_amounts_in_big_blinds(win):
    from pokertrainer.gui import play_page as P
    S.put("play_opponents", 2)
    S.put("play_speed", "fast")
    S.put("animations", False)
    S.put("show_bb", False)
    win.start_mode(S.MODE_BY_KEY["play"])
    pg = win.play
    assert "bb" not in pg.hero_seat.stack.text()
    pg.bb_btn.click()
    assert S.get("show_bb") and pg.hero_seat.stack.text().endswith("bb")
    assert P.fmt_amount(25) == "2,5 bb" and P.fmt_amount(1000) == "100 bb"
    pg.bb_btn.click()
    assert not S.get("show_bb") and "bb" not in pg.hero_seat.stack.text()
    win.go("home")


def test_mucked_hands_stay_hidden(win):
    S.put("play_opponents", 3)
    S.put("play_speed", "fast")
    S.put("animations", False)
    S.put("show_mucked", False)
    win.start_mode(S.MODE_BY_KEY["play"])
    pg = win.play
    found = False
    for _ in range(40):
        _play_hand(pg, "call")
        t = pg.table
        mucked = [i for i in t.showdown_hands if i not in t.shown and i != 0 and not t.runout]
        if mucked:
            i = mucked[0]
            sw = pg._seat_widget(i)
            assert not any(c._face_up for c in sw.cards)
            assert "descartou" in sw.action.text()
            found = True
            break
        pg.next_hand()
    assert found
    win.go("home")


def test_tournament_bubble_and_ante(win):
    from pokertrainer import ai
    S.put("play_opponents", 3)
    S.put("play_speed", "fast")
    S.put("animations", False)
    win.sidebar.mode_buttons["tournament"].click()
    win.tourn_page.cards["easy"].click()
    pg = win.play
    _play_hand(pg, "fold")
    _knock_out_to(pg, 3)                  # mesa de 4, passam 2: com 3 vivos é a bolha
    pg.session["hands"] = ai.HANDS_PER_LEVEL * 2      # nível 3: ante do big blind
    pg.next_hand()
    t = pg.table
    assert t.bubble and "BOLHA" in pg.info.text() and "ANTE" in pg.info.text()
    assert any("Bolha" in line for line in pg.log_lines)
    assert t.ante == ai.BLIND_LEVELS[2][2] > 0
    win.go("home")
