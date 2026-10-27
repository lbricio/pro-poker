"""Menu lateral: modos de jogo (início) ou painel da partida, e navegação fixa embaixo."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)

from pokertrainer import ai
from pokertrainer import engine as E
from pokertrainer import profile as PF
from pokertrainer import settings as S
from pokertrainer.i18n import tr
from pokertrainer.gui.widgets import Glass

MODE_ICONS = {"preflop": "🂠🂠", "flop": "🂠🂠 + 3", "turn": "🂠🂠 + 4"}


def _line() -> QFrame:
    f = QFrame()
    f.setObjectName("line")
    return f


def _section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("section")
    return lbl


def tournament_rules(difficulty: str | None = None) -> str:
    d = difficulty or S.get("difficulty")
    n = ai.tournament_rounds(d)
    return tr(f"<b>Torneio em {n} rodadas</b> (dificuldade {ai.difficulty_name(d)}).<br><br>"
              "Cada rodada é uma mesa nova: todos começam com 1000 fichas, sem recompra, e os blinds sobem a cada "
              "10 mãos. Quando metade da mesa for eliminada, quem sobrou passa para a próxima rodada.<br><br>"
              "Na <b>mesa final</b> só há um vencedor: fique com todas as fichas para ganhar o título. 🏆",
              f"<b>{n}-round tournament</b> ({ai.difficulty_name(d)} difficulty).<br><br>"
              "Each round is a new table: everyone starts with 1000 chips, no rebuys, and the blinds go up every "
              "10 hands. Once half the table is knocked out, the survivors move on to the next round.<br><br>"
              "The <b>final table</b> has a single winner: take all the chips to win the title. 🏆")


class ModeButton(QPushButton):
    def __init__(self, mode: S.Mode, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("mode")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(54)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 6, 14, 6)
        v = QVBoxLayout()
        v.setSpacing(1)
        t = QLabel(mode.title)
        t.setStyleSheet("font-size: 16px; font-weight: 800; background: transparent;")
        s = QLabel(mode.subtitle)
        s.setStyleSheet("font-size: 12px; color: #9fb3ad; background: transparent;")
        for lbl in (t, s):
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        v.addWidget(t)
        v.addWidget(s)
        h.addLayout(v, 1)
        if mode.key == "tournament":
            dots = QLabel("🏆")
            dots.setToolTip(tr("Rodadas eliminatórias, sem recompra", "Knockout rounds, no rebuys"))
        elif mode.is_play:
            dots = QLabel("♠♥♦♣")
            dots.setToolTip(tr("Partida completa com apostas", "A full game with betting"))
        elif mode.visible < 0:
            dots = QLabel("●● 💰")
            dots.setToolTip(tr("Flop ou turn, com aposta para pagar", "Flop or turn, facing a bet"))
        else:
            n = 2 + mode.visible
            dots = QLabel("●" * 2 + (" " + "●" * mode.visible if mode.visible else ""))
            dots.setToolTip(tr(f"{n} cartas conhecidas", f"{n} known cards"))
        dots.setStyleSheet("color: #f5c542; font-size: 11px; letter-spacing: 2px; background: transparent;")
        dots.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(dots)


class Stat(QWidget):
    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.value = QLabel("–")
        self.value.setObjectName("statValue")
        self.lbl = lbl = QLabel(label)
        lbl.setObjectName("statLabel")
        v.addWidget(self.value)
        v.addWidget(lbl)


class Sidebar(Glass):
    modeChosen = Signal(object)        # S.Mode
    navigate = Signal(str)             # "game" | "table" | "tips" | "settings" | "home"
    newHand = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, alpha=190)
        self.setFixedWidth(300)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 20, 18, 16)
        root.setSpacing(10)

        title = QLabel("♠ Poker Trainer")
        title.setObjectName("appTitle")
        sub = QLabel(tr("Treine seu olho para probabilidades", "Train your eye for probabilities"))
        sub.setObjectName("appSubtitle")
        root.addWidget(title)
        root.addWidget(sub)
        root.addSpacing(6)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_menu())
        self.stack.addWidget(self._build_game())
        root.addWidget(self.stack, 1)

        root.addWidget(_line())
        nav = QVBoxLayout()
        nav.setSpacing(2)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text in [("game", tr("🃏   Mesa", "🃏   Table")),
                          ("table", tr("📊   Tabela de probabilidades", "📊   Probability charts")),
                          ("stats", tr("📈   Estatísticas e revisão", "📈   Stats and review")),
                          ("tips", tr("💡   Dicas", "💡   Tips")),
                          ("settings", tr("⚙   Configurações", "⚙   Settings"))]:
            b = QPushButton(text)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.navigate.emit(k))
            self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            nav.addWidget(b)
        self.nav_buttons["game"].hide()
        root.addLayout(nav)

    # ------------------------------------------------------------ menu inicial
    def _build_menu(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        groups = [
            (tr("Modos de treino", "Training modes"), [m for m in S.MODES if not m.is_play],
             tr("Adivinhe a chance de a mão vencer: quanto mais perto do valor real, mais pontos.",
                "Guess the hand's chance of winning: the closer to the actual value, the more points.")),
            (tr("Modos de jogo", "Game modes"), [m for m in S.MODES if m.is_play],
             tr("Jogue de verdade contra bots com personalidade. A dificuldade fica em Configurações.",
                "Play for real against bots with personalities. Difficulty is in Settings.")),
        ]
        self.mode_buttons: dict[str, ModeButton] = {}
        for k, (title, modes, help_text) in enumerate(groups):
            if k:
                v.addSpacing(8)
            sec = _section(title)
            sec.setToolTip(help_text)
            v.addWidget(sec)
            for m in modes:
                b = ModeButton(m)
                b.setToolTip(help_text if m.key != "tournament" else tr(
                    "Sem recompra; metade de cada mesa passa de rodada. 3 rodadas no Fácil e no Médio, 5 no Difícil "
                    "e no Semi-pro, 6 no Pro.",
                    "No rebuys; half of each table advances. 3 rounds on Easy and Medium, 5 on Hard and Semi-pro, "
                    "6 on Pro."))
                b.clicked.connect(lambda _=False, mode=m: self.modeChosen.emit(mode))
                self.mode_buttons[m.key] = b
                v.addWidget(b)
        v.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidget(w)
        return sc

    # ------------------------------------------------------------ painel de jogo
    def _build_game(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        head = QHBoxLayout()
        self.mode_title = QLabel("")
        self.mode_title.setStyleSheet("font-size: 18px; font-weight: 800;")
        self.round_lbl = QLabel("")
        self.round_lbl.setObjectName("muted")
        head.addWidget(self.mode_title)
        head.addStretch(1)
        head.addWidget(self.round_lbl)
        v.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.st_points, self.st_avg = Stat(tr("pontos", "points")), Stat(tr("erro médio", "average error"))
        self.st_hits, self.st_streak = Stat(tr("acertos", "hits")), Stat(tr("sequência (recorde)", "streak (best)"))
        grid.addWidget(self.st_points, 0, 0)
        grid.addWidget(self.st_avg, 0, 1)
        grid.addWidget(self.st_hits, 1, 0)
        grid.addWidget(self.st_streak, 1, 1)
        box = QFrame()
        box.setObjectName("card")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.addLayout(grid)
        v.addWidget(box)

        self.profile_box = QFrame()
        self.profile_box.setObjectName("card")
        pb = QVBoxLayout(self.profile_box)
        pb.setContentsMargins(12, 8, 12, 8)
        pb.setSpacing(2)
        ptitle = QLabel(tr("SEU PERFIL NESTA PARTIDA", "YOUR PROFILE THIS GAME"))
        ptitle.setObjectName("section")
        self.profile_lbl = QLabel()
        self.profile_lbl.setWordWrap(True)
        self.profile_lbl.setTextFormat(Qt.RichText)
        self.profile_lbl.setStyleSheet("font-size: 12px;")
        pb.addWidget(ptitle)
        pb.addWidget(self.profile_lbl)
        self.profile_box.hide()
        v.addWidget(self.profile_box)

        v.addWidget(_section(tr("Análise da mão", "Hand analysis")))
        self.analysis = QLabel("")
        self.analysis.setWordWrap(True)
        self.analysis.setTextFormat(Qt.RichText)
        self.analysis.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.analysis.setStyleSheet("font-size: 13px; line-height: 140%;")
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 6, 0)
        il.addWidget(self.analysis)
        il.addStretch(1)
        sc.setWidget(inner)
        v.addWidget(sc, 1)

        row = QHBoxLayout()
        self.new_btn = QPushButton(tr("↻  Nova mão", "↻  New hand"))
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.clicked.connect(self.newHand.emit)
        back = QPushButton(tr("←  Modos", "←  Modes"))
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self.navigate.emit("home"))
        row.addWidget(back)
        row.addWidget(self.new_btn, 1)
        v.addLayout(row)
        return w

    # ------------------------------------------------------------ API
    def show_menu(self) -> None:
        self.stack.setCurrentIndex(0)
        self.nav_buttons["game"].hide()

    def show_game(self, mode: S.Mode) -> None:
        self.stack.setCurrentIndex(1)
        self.mode_title.setText(mode.title if mode.is_play else tr(f"Modo {mode.title}", f"{mode.title} mode"))
        self.nav_buttons["game"].show()
        self.profile_box.setVisible(mode.is_play)
        if mode.is_play:
            self.new_btn.setText(tr("↻  Novo torneio", "↻  New tournament") if mode.key == "tournament" else
                                 tr("↻  Nova partida", "↻  New game"))
            self.set_play_stats({"hands": 0, "won": 0, "good": 0, "decisions": 0, "stack": 0, "profit": 0})
            if mode.key == "tournament":
                self.analysis.setText(tournament_rules())
                return
            self.analysis.setText(tr("Jogue contra os bots. Quando você enfrentar uma aposta, as dicas de pot odds "
                                     "aparecem aqui e no histórico da mão.",
                                     "Play against the bots. When you face a bet, pot-odds tips show up here and "
                                     "in the hand history."))
            return
        self.new_btn.setText(tr("↻  Nova mão", "↻  New hand"))
        self.refresh_stats(mode)
        self.analysis.setText(tr("Arraste a barra (ou use ← →) e confirme com Enter para ver a resposta e a "
                                 "explicação.",
                                 "Drag the bar (or use ← →) and confirm with Enter to see the answer and the "
                                 "explanation."))

    def set_play_stats(self, s: dict) -> None:
        n = s["hands"]
        self.round_lbl.setText(tr(f"{n} mão{'s' if n != 1 else ''}", f"{n} hand{'s' if n != 1 else ''}"))
        self.st_points.lbl.setText(tr("fichas", "chips"))
        self.st_points.value.setText(str(s["stack"]))
        if s.get("rounds"):
            self.st_avg.lbl.setText(tr("rodada", "round"))
            self.st_avg.value.setText(f"{s['round']}/{s['rounds']}")
        else:
            self.st_avg.lbl.setText(tr("lucro da sessão", "session profit"))
            self.st_avg.value.setText(f"{s['profit']:+d}" if s["hands"] else "–")
        self.st_hits.lbl.setText(tr("mãos vencidas", "hands won"))
        self.st_hits.value.setText(f"{s['won'] / s['hands']:.0%}" if s["hands"] else "–")
        self.st_streak.lbl.setText(tr("decisões certas", "right decisions"))
        self.st_streak.value.setText(f"{s['good'] / s['decisions']:.0%}" if s["decisions"] else "–")
        c = s.get("profile")
        if c is not None:
            rows = []
            for st in PF.stats(c)[:6]:
                verdict, color = st.verdict()
                rows.append(f"<tr><td>{st.short}</td><td align='right'><b>{st.fmt()}</b></td>"
                            f"<td align='right' style='color:{color}; font-size:11px'>&nbsp;{verdict}</td></tr>")
            self.profile_lbl.setText("<table width='100%' cellspacing='0' cellpadding='1'>" + "".join(rows) +
                                     "</table><p style='color:#9fb3ad; margin-top:4px'>" + PF.style_text(c) +
                                     (tr(f"<br>sua imagem: 😨 medo {s['image'][0]:.0%} · 🤨 desconfiança "
                                         f"{s['image'][1]:.0%}",
                                         f"<br>your image: 😨 fear {s['image'][0]:.0%} · 🤨 suspicion "
                                         f"{s['image'][1]:.0%}") if s.get("image") else "") + "</p>")
            self.profile_lbl.setToolTip(PF.tooltip(c, tr("Suas estatísticas nesta partida", "Your stats this game")))

    def show_coach(self, html: str) -> None:
        self.analysis.setText(html)

    def set_active(self, key: str | None) -> None:
        for k, b in self.nav_buttons.items():
            b.setChecked(k == key)
        if key is None or key == "home":
            checked = self.nav_group.checkedButton()
            if checked:
                self.nav_group.setExclusive(False)
                checked.setChecked(False)
                self.nav_group.setExclusive(True)

    def refresh_stats(self, mode: S.Mode) -> None:
        if mode.is_play:
            return
        self.st_points.lbl.setText(tr("pontos", "points"))
        self.st_avg.lbl.setText(tr("erro médio", "average error"))
        self.st_hits.lbl.setText(tr("acertos", "hits"))
        st = S.load_stats(mode.key)
        self.round_lbl.setText(tr(f"{st.rounds} mão{'s' if st.rounds != 1 else ''}",
                                   f"{st.rounds} hand{'s' if st.rounds != 1 else ''}"))
        self.st_points.value.setText(f"{st.points}")
        self.st_avg.value.setText(f"{st.avg_error:.1f} pts" if st.rounds else "–")
        self.st_hits.value.setText(f"{st.hit_rate:.0%}" if st.rounds else "–")
        if mode.key == "potodds":
            self.st_streak.lbl.setText(tr("decisões certas", "right decisions"))
            self.st_streak.value.setText(f"{st.good_decisions / st.decisions:.0%}" if st.decisions else "–")
        else:
            self.st_streak.lbl.setText(tr("sequência (recorde)", "streak (best)"))
            self.st_streak.value.setText(f"{st.streak} ({st.best_streak})")

    def round_started(self) -> None:
        self.analysis.setText("<span style='color:#9fb3ad'>" + tr(
            "Arraste a barra (ou use ← →) e confirme com Enter.",
            "Drag the bar (or use ← →) and confirm with Enter.") + "</span>")

    def show_result(self, res) -> None:
        r = res.eq
        sep = tr(".", ",")
        sims = f"{r.iterations:,}".replace(",", sep)
        lines = [
            f"<p><span style='font-size:22px; font-weight:800; color:{res.rating.color}'>{res.rating.label}</span>"
            f"&nbsp;&nbsp;<b>+{res.rating.points}</b> {tr('pontos', 'points')}</p>",
            "<table cellspacing='0' cellpadding='2' width='100%'>"
            f"<tr><td>{tr('Chance real (equidade)', 'Actual chance (equity)')}</td>"
            f"<td align='right'><b>{r.equity * 100:.1f}%</b></td></tr>"
            f"<tr><td style='color:#9fb3ad'>&nbsp;&nbsp;{tr('vitória', 'win')}</td>"
            f"<td align='right'>{r.win * 100:.1f}%</td></tr>"
            f"<tr><td style='color:#9fb3ad'>&nbsp;&nbsp;{tr('empate', 'tie')}</td>"
            f"<td align='right'>{r.tie * 100:.1f}%</td></tr>"
            f"<tr><td>{tr('Seu palpite', 'Your guess')}</td><td align='right'>{res.guess}%</td></tr>"
            f"<tr><td>{tr('Erro', 'Error')}</td><td align='right'>{res.error_pp:.1f} pts</td></tr>"
            "</table>",
            *([] if res.spot is None or res.called is None else [
                "<p style='margin-top:6px'>" + (tr("Você pagou", "You called") if res.called else
                                                tr("Você desistiu", "You folded")) + " — " +
                ("<b style='color:#3ddc84'>" + tr("decisão certa", "right decision") if res.good_decision else
                 "<b style='color:#ff6b6b'>" + tr("decisão errada", "wrong decision")) + "</b><br>" +
                tr(f"precisava de {res.spot.need:.0%} · EV de pagar {res.spot.ev_call(r.equity):+.0f} fichas",
                   f"needed {res.spot.need:.0%} · EV of calling {res.spot.ev_call(r.equity):+.0f} chips") +
                "</p>"]),
            f"<p style='color:#7f948e; font-size:11px'>{sims} {tr('simulações', 'simulations')} · "
            f"{tr('margem', 'margin')} ±{r.stderr * 196:.1f} pts</p>",
        ]
        # distribuição da mão final
        cats = [(E.category_name(i), p) for i, p in enumerate(r.final_categories) if p >= 0.005]
        if cats:
            rows = "".join(
                f"<tr><td>{name}</td><td><span style='color:#f5c542'>{'▮' * max(1, round(p * 20))}</span></td>"
                f"<td align='right'>{p * 100:.0f}%</td></tr>"
                for name, p in reversed(cats))
            lines.append(f"<p style='margin-top:8px'><b>{tr('Sua mão no river vai ser:', 'Your hand on the river will be:')}</b></p>"
                         f"<table cellspacing='0' cellpadding='1' width='100%'>{rows}</table>")
        lines.append("<p style='color:#9fb3ad; font-size:12px; margin-top:8px'>" + tr(
            "A chance é calculada contra mãos aleatórias. As dicas desta mão estão ao lado das cartas.",
            "The chance is computed against random hands. The tips for this hand are next to the cards.") + "</p>")
        self.analysis.setText("".join(lines))
