"""Janela principal: fundo borrado, menu lateral, seletor de idioma e área de conteúdo."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

import time

from pokertrainer import coach
from pokertrainer import engine as E
from pokertrainer import i18n
from pokertrainer import settings as S
from pokertrainer.gui.game_page import GamePage, RoundResult
from pokertrainer.gui.pages import HomePage, SettingsPage, TablePage, TipsPage
from pokertrainer.gui.sidebar import Sidebar
from pokertrainer.gui.play_page import PlayPage
from pokertrainer.gui.stats_page import StatsPage
from pokertrainer.gui.widgets import Background, flag_pixmap
from pokertrainer.i18n import tr


class LanguageSwitch(QWidget):
    """Botões de idioma (bandeira + sigla) no canto superior direito."""

    LABELS = {"pt": "PT/BR", "en": "ENG"}

    def __init__(self, on_change, parent=None) -> None:
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for code, name in i18n.LANGUAGES.items():
            b = QPushButton(self.LABELS[code])
            b.setIcon(QIcon(flag_pixmap(code)))
            b.setIconSize(QSize(24, 16))
            b.setToolTip(name)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(code == i18n.lang())
            b.clicked.connect(lambda _=False, c=code: on_change(c))
            self.group.addButton(b)
            self.buttons[code] = b
            h.addWidget(b)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        i18n.set_lang(S.get("language"))
        self.resize(1360, 860)
        self.setMinimumSize(1080, 720)

        self.bg = Background(S.get("blur"))
        self.setCentralWidget(self.bg)
        self._outer = QHBoxLayout(self.bg)
        self._outer.setContentsMargins(16, 10, 16, 16)
        self._outer.setSpacing(0)
        self.content: QWidget | None = None
        self.current = "home"
        self.playing = False   # jogo simulado ativo (a "Mesa" mostra a página de jogo)
        self._build()
        self.go("home")

    # ------------------------------------------------------------ construção (refeita ao trocar o idioma)
    def _build(self) -> None:
        self.setWindowTitle(tr("Poker Trainer — probabilidades de mãos", "Poker Trainer — hand probabilities"))
        self.content = QWidget()
        h = QHBoxLayout(self.content)
        h.setContentsMargins(0, 6, 0, 0)
        h.setSpacing(0)

        self.sidebar = Sidebar()
        h.addWidget(self.sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 8, 0)
        top.addStretch(1)
        self.lang_switch = LanguageSwitch(self.set_language)
        top.addWidget(self.lang_switch)
        right.addLayout(top)

        self.stack = QStackedWidget()
        self.home = HomePage()
        self.game = GamePage()
        self.table = TablePage()
        self.tips = TipsPage()
        self.settings_page = SettingsPage()
        self.stats_page = StatsPage()
        self.play = PlayPage()
        self.pages = {"home": self.home, "game": self.game, "table": self.table, "tips": self.tips,
                      "settings": self.settings_page, "stats": self.stats_page, "play": self.play}
        for w in self.pages.values():
            self.stack.addWidget(w)
        right.addWidget(self.stack, 1)
        h.addLayout(right, 1)

        self.sidebar.modeChosen.connect(self.start_mode)
        self.sidebar.navigate.connect(self.go)
        self.sidebar.newHand.connect(self._new_hand)
        self.game.roundStarted.connect(lambda _m: self.sidebar.round_started())
        self.game.roundFinished.connect(self._on_round)
        self.settings_page.blurChanged.connect(self.bg.set_blur)
        self.settings_page.statsReset.connect(self._stats_reset)
        self.stats_page.reviewRequested.connect(self.review)
        self.stats_page.focusRequested.connect(self.focus_training)
        self.play.statsChanged.connect(self.sidebar.set_play_stats)
        self.play.coachMessage.connect(self.sidebar.show_coach)
        self._outer.addWidget(self.content)
        self.content.show()

    def set_language(self, code: str) -> None:
        if code == i18n.lang():
            return
        S.put("language", code)
        i18n.set_lang(code)
        # guarda o estado da partida para reabrir a mesma mão no novo idioma
        g = self.game
        state = ((g.mode, g.deal, g.eq, g.bar.value(), g.revealed, g.spot, g.called, g.range_pct)
                 if g.mode and g.deal else None)
        focus = g.focus_type
        if g._job is not None:
            g._job.cancelled = True
        play_state = self.play.export_state() if self.playing and self.play.table else None
        self.play.stop()
        page = self.current
        old = self.content
        self._outer.removeWidget(old)
        old.hide()
        old.deleteLater()
        self._build()
        if state:
            mode, deal, eq, guess, revealed, spot, called, range_pct = state
            self.sidebar.show_game(mode)
            self.game.focus_type = None
            if focus:
                self.game.focus_type = focus
                self.game.focus_btn.setText(f"🎯  {coach.hand_type_name(focus)}  ✕")
                self.game.focus_btn.show()
            self.game.restore(mode, deal, eq, guess, revealed, spot, called, range_pct)
        if play_state:
            self.sidebar.show_game(S.MODE_BY_KEY["tournament" if play_state["tournament"] else "play"])
            self.play.adopt(play_state)
            self.play._emit_stats()
        self.go(page)

    # ------------------------------------------------------------ navegação
    def go(self, key: str) -> None:
        if key == "home":
            self.sidebar.show_menu()
            self.game.mode = None
            self.playing = False
            self.play.stop()
        if key == "game" and self.game.mode is None and not self.playing:
            key = "home"
        if key == "table":
            self.table.set_opponents(self.game.n_opp if self.game.mode else S.get("opponents"))
            d = self.game.deal
            self.table.grid.set_marked(E.starting_hand_label(*d.hero) if d and self.game.mode else None)
        if key == "settings":
            self.settings_page.refresh()
        if key == "stats":
            self.stats_page.refresh()
        self.current = key
        page = self.play if key == "game" and self.playing else self.pages[key]
        self.stack.setCurrentWidget(page)
        self.sidebar.set_active(key if key != "home" else None)
        if key == "game":
            (self.play if self.playing else self.game.bar).setFocus()

    def start_mode(self, mode: S.Mode) -> None:
        if mode.is_play:
            self.playing = True
            self.game.mode = None
            self.sidebar.show_game(mode)
            self.play.new_session(tournament=mode.key == "tournament")
            self.go("game")
            return
        self.playing = False
        self.play.stop()
        self.game.focus_type = None
        self.game.focus_btn.hide()
        self.sidebar.show_game(mode)
        self.game.start(mode)
        self.go("game")

    def review(self, h: dict) -> None:
        """Reabre uma mão do histórico na mesa, já revelada (não conta pontos)."""
        self.playing = False
        self.play.stop()
        mode = S.MODE_BY_KEY.get(h["mode"])
        if mode is None:
            return
        deal = E.Deal(hero=list(h["hero"]), board=list(h["board"]), opponents=[list(o) for o in h["opps"]],
                      visible=h["vis"])
        eq = E.EquityResult(equity=h["eq"], win=h.get("win", 0.0), tie=h.get("tie", 0.0), iterations=h.get("it", 0),
                            final_categories=h.get("cats", [0.0] * 9), stderr=h.get("se", 0.0),
                            vs_random=h.get("vr"))
        spot = coach.PotSpot(*h["pot"]) if h.get("pot") else None
        self.sidebar.show_game(mode)
        self.game.set_focus(None)
        self.game.restore(mode, deal, eq, h["guess"], True, spot, h.get("called"), h.get("range", 100))
        self.go("game")

    def focus_training(self, hand_type: str) -> None:
        """Treino focado num tipo de mão; escolhe um modo compatível."""
        self.playing = False
        self.play.stop()
        cur = self.game.mode
        if hand_type.startswith("pf_"):
            mode = S.MODE_BY_KEY["preflop"]
        else:
            mode = cur if cur is not None and cur.key in ("flop", "turn", "potodds") else S.MODE_BY_KEY["flop"]
        self.sidebar.show_game(mode)
        self.game.mode = mode
        self.game.revealed = False
        self.game.set_focus(hand_type)  # já distribui a primeira mão do tipo
        self.go("game")

    def _new_hand(self) -> None:
        if self.playing:
            self.sidebar.show_game(S.MODE_BY_KEY["tournament" if self.play.tournament else "play"])
            self.play.new_session()
            self.go("game")
            return
        self.go("game")
        self.game.new_round()

    def _on_round(self, res: RoundResult) -> None:
        if not res.replay:
            st = S.load_stats(res.mode.key)
            st.rounds += 1
            st.total_error += res.error_pp
            st.points += res.rating.points
            if res.rating.hit:
                st.hits += 1
                st.streak += 1
                st.best_streak = max(st.best_streak, st.streak)
            else:
                st.streak = 0
            if res.spot is not None and res.called is not None:
                st.decisions += 1
                st.good_decisions += bool(res.good_decision)
                st.ev += res.spot.ev_call(res.eq.equity) if res.called else 0.0
            S.save_stats(res.mode.key, st)
            S.append_history(self._history_entry(res))
            self.sidebar.refresh_stats(res.mode)
        self.sidebar.show_result(res)

    @staticmethod
    def _history_entry(res: RoundResult) -> dict:
        d, r = res.deal, res.eq
        e = {"t": int(time.time()), "mode": res.mode.key, "hero": d.hero, "board": d.board, "opps": d.opponents,
             "vis": d.visible, "guess": res.guess, "eq": round(r.equity, 4), "win": round(r.win, 4),
             "tie": round(r.tie, 4), "it": r.iterations, "cats": [round(c, 4) for c in r.final_categories],
             "se": round(r.stderr, 5), "err": round(res.error_pp, 2), "type": res.hand_type, "range": res.range_pct}
        if r.vs_random is not None:
            e["vr"] = round(r.vs_random, 4)
        if res.spot is not None:
            e["pot"] = res.spot.to_list()
            e["called"] = res.called
            e["good"] = res.good_decision
            e["ev"] = round(res.spot.ev_call(r.equity), 1) if res.called else 0.0
        return e

    def _stats_reset(self) -> None:
        if self.game.mode is not None:
            self.sidebar.refresh_stats(self.game.mode)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape and self.stack.currentWidget() is not self.home:
            self.go("game" if self.game.mode else "home")
            return
        super().keyPressEvent(e)
