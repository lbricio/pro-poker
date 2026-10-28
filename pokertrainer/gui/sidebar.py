"""Menu lateral: modos de jogo (início) ou painel da partida, e navegação fixa embaixo."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)

from pokertrainer import ai
from pokertrainer import decision as D
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
              "Todos começam com 1000 fichas (100 big blinds), sem recompra. Os blinds sobem a cada 15 mãos, com "
              "ante do big blind a partir do 3º nível. Quando metade da mesa for eliminada, quem sobrou passa de "
              "rodada e <b>leva as suas fichas</b> para uma mesa nova.<br><br>"
              "Na <b>bolha</b> (falta uma eliminação) sobreviver vale mais que fichas. Na <b>mesa final</b> só há um "
              "vencedor: fique com todas as fichas para ganhar o título. 🏆",
              f"<b>{n}-round tournament</b> ({ai.difficulty_name(d)} difficulty).<br><br>"
              "Everyone starts with 1000 chips (100 big blinds), no rebuys. The blinds go up every 15 hands, with a "
              "big blind ante from level 3. Once half the table is knocked out, the survivors advance and <b>carry "
              "their chips</b> to a new table.<br><br>"
              "On the <b>bubble</b> (one knockout left) surviving is worth more than chips. The <b>final table</b> has "
              "a single winner: take all the chips to win the title. 🏆")


def training_help() -> str:
    return "<span style='color:#9fb3ad'>" + tr(
        "Escolha a jogada nos botões ou pelo teclado: <b>F</b> desistir, <b>C</b> passar/pagar, "
        "<b>R</b> apostar/aumentar. A análise aparece aqui.",
        "Pick your play with the buttons or the keyboard: <b>F</b> fold, <b>C</b> check/call, "
        "<b>R</b> bet/raise. The analysis shows up here.") + "</span>"


class MenuButton(QPushButton):
    """Botão grande do menu: título, subtítulo e um selo à direita."""

    def __init__(self, title: str, subtitle: str, badge: str, badge_tip: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("mode")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(48)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 4, 14, 4)
        v = QVBoxLayout()
        v.setSpacing(1)
        t = QLabel(title)
        t.setStyleSheet("font-size: 16px; font-weight: 800; background: transparent;")
        s = QLabel(subtitle)
        s.setStyleSheet("font-size: 12px; color: #9fb3ad; background: transparent;")
        for lbl in (t, s):
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        v.addWidget(t)
        v.addWidget(s)
        h.addLayout(v, 1)
        dots = QLabel(badge)
        dots.setToolTip(badge_tip)
        dots.setStyleSheet("color: #f5c542; font-size: 11px; letter-spacing: 2px; background: transparent;")
        dots.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(dots)


class ModeButton(MenuButton):
    def __init__(self, mode: S.Mode, parent=None) -> None:
        if mode.key == "tournament":
            badge, tip = "🏆", tr("Rodadas eliminatórias, sem recompra", "Knockout rounds, no rebuys")
        elif mode.is_play:
            badge, tip = "♠♥♦♣", tr("Partida completa com apostas", "A full game with betting")
        else:
            badge = "●" * 2 + (" " + "●" * mode.visible if mode.visible else "")
            tip = tr(f"{2 + mode.visible} cartas conhecidas", f"{2 + mode.visible} known cards")
        super().__init__(mode.title, mode.subtitle, badge, tip, parent)


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
    navigate = Signal(str)             # "game" | "help" | "table" | "stats" | "tips" | "settings" | "home"
    newHand = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, alpha=190)
        self.setFixedWidth(300)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 20, 18, 16)
        root.setSpacing(10)

        title = QLabel("♠ Pro Poker Trainer")
        title.setObjectName("appTitle")
        sub = QLabel(tr("Treino de decisões de Texas Hold'em", "Texas Hold'em decision training"))
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
                          ("help", tr("📖   Como jogar", "📖   How to play")),
                          ("table", tr("📊   Tabela de probabilidades", "📊   Probability charts")),
                          ("stats", tr("📈   Estatísticas e revisão", "📈   Stats and review")),
                          ("tips", tr("💡   Dicas", "💡   Tips")),
                          ("settings", tr("⚙️   Configurações", "⚙️   Settings"))]:
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
        """Menu inicial: modos de jogo em cima e os modos de treino embaixo."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        groups = [
            (tr("Modos de jogo", "Game modes"), [m for m in S.MODES if m.is_play],
             tr("Jogue de verdade contra bots com personalidade. A dificuldade fica em Configurações.",
                "Play for real against bots with personalities. Difficulty is in Settings.")),
            (tr("Modos de treino", "Training modes"), [m for m in S.MODES if not m.is_play],
             tr("Uma situação por mão: desista, passe/pague ou aposte/aumente e veja se foi a melhor jogada.",
                "One spot per hand: fold, check/call or bet/raise and see whether it was the best play.")),
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
        self.st_points, self.st_avg = Stat(tr("pontos", "points")), Stat(tr("melhor jogada", "best play"))
        self.st_hits, self.st_streak = Stat(tr("sem erro", "no mistake")), Stat(tr("sequência (recorde)",
                                                                                  "streak (best)"))
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

    def show_game(self, mode: S.Mode, difficulty: str | None = None) -> None:
        self.stack.setCurrentIndex(1)
        self.mode_title.setText(mode.title if mode.is_play else tr(f"Modo {mode.title}", f"{mode.title} mode"))
        self.nav_buttons["game"].show()
        self.profile_box.setVisible(mode.is_play)
        if mode.is_play:
            self.new_btn.setText(tr("↻  Novo torneio", "↻  New tournament") if mode.key == "tournament" else
                                 tr("↻  Nova partida", "↻  New game"))
            self.set_play_stats({"hands": 0, "won": 0, "good": 0, "decisions": 0, "stack": 0, "profit": 0})
            if mode.key == "tournament":
                self.analysis.setText(tournament_rules(difficulty))
                return
            self.analysis.setText(tr("Jogue contra os bots. Quando você enfrentar uma aposta, as dicas de pot odds "
                                     "aparecem aqui e no histórico da mão.",
                                     "Play against the bots. When you face a bet, pot-odds tips show up here and "
                                     "in the hand history."))
            return
        self.new_btn.setText(tr("↻  Nova mão", "↻  New hand"))
        self.refresh_stats(mode)
        self.analysis.setText(training_help())

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
        self.st_avg.lbl.setText(tr("melhor jogada", "best play"))
        self.st_hits.lbl.setText(tr("sem erro", "no mistake"))
        self.st_streak.lbl.setText(tr("sequência (recorde)", "streak (best)"))
        st = S.load_stats(mode.key)
        n = st.hands
        self.round_lbl.setText(tr(f"{n} decis{'ões' if n != 1 else 'ão'}", f"{n} decision{'s' if n != 1 else ''}"))
        self.st_points.value.setText(f"{st.points}")
        self.st_avg.value.setText(f"{st.best_rate:.0%}" if n else "–")
        self.st_hits.value.setText(f"{st.good_rate:.0%}" if n else "–")
        self.st_streak.value.setText(f"{st.streak} ({st.best_streak})")

    def round_started(self) -> None:
        self.analysis.setText(training_help())

    def show_result(self, res) -> None:
        r, v, sp = res.eq, res.verdict, res.spot
        sep = tr(".", ",")
        sims = f"{r.iterations:,}".replace(",", sep)
        label, color = D.quality_label(v.quality)
        rows = []
        if v.action:
            mine = D.action_name(v.action)
            if v.size and v.action in (D.BET, D.RAISE):
                mine += f" {D.bb(v.size)}"
            rows.append((tr("Sua jogada", "Your play"), mine))
        rows.append((tr("Melhor jogada", "Best play"), D.action_name(v.best)))
        if sp.hero_pos:
            rows.append((tr("Posição", "Position"), sp.hero_pos + ("" if sp.street == 0 else
                         tr(" (em posição)", " (in position)") if sp.in_position else tr(" (fora de posição)",
                                                                                         " (out of position)"))))
        if sp.kind == "open":
            rows.append((tr("Sua mão", "Your hand"), f"top {v.pct:.0f}%"))
            rows.append((tr("Abre-se até", "Open up to"), f"top {D.R.open_pct(sp.hero_pos)}%"))
        else:
            rows.append((tr("Chance contra a faixa", "Chance vs. their range"), f"{r.equity:.0%}"))
            if r.vs_random is not None:
                rows.append((tr("(contra mãos aleatórias)", "(vs. random hands)"), f"{r.vs_random:.0%}"))
        if sp.facing_bet and sp.kind != "open":
            rows.append((tr("Preço para pagar", "Price to call"), f"{v.need:.0%}" +
                         (f" → {v.need_eff:.0%}" if v.need_eff and abs(v.need_eff - v.need) > 0.005 else "")))
            rows.append((tr("EV de pagar", "EV of calling"), D.ev_bb(sp, r.equity)))
        if sp.street >= 3:
            rows.append((tr("Contra quem pagaria", "Vs. hands that call"), f"{v.value:.0%}"))
        rows.append((tr("Stack efetivo · SPR", "Eff. stack · SPR"), f"{D.bb(sp.stack)} · {D.num(sp.spr)}"))
        table = "".join(f"<tr><td>{a}</td><td align='right'><b>{b}</b></td></tr>" for a, b in rows)
        head = (f"<p><span style='font-size:22px; font-weight:800; color:{color}'>{label}</span>"
                f"&nbsp;&nbsp;<b>+{v.points}</b> {tr('pontos', 'points')}</p>" if v.action else "")
        lines = [head, f"<table cellspacing='0' cellpadding='2' width='100%'>{table}</table>",
                 f"<p style='color:#7f948e; font-size:11px'>{sims} {tr('simulações', 'simulations')} · "
                 f"{tr('margem', 'margin')} ±{r.stderr * 196:.1f} pts</p>"]
        cats = [(E.category_name(i), p) for i, p in enumerate(r.final_categories) if p >= 0.005]
        if cats and res.deal.visible < 5:
            bars = "".join(
                f"<tr><td>{name}</td><td><span style='color:#f5c542'>{'▮' * max(1, round(p * 20))}</span></td>"
                f"<td align='right'>{p * 100:.0f}%</td></tr>"
                for name, p in reversed(cats))
            lines.append(f"<p style='margin-top:8px'><b>{tr('Sua mão no river vai ser:', 'Your hand on the river will be:')}</b></p>"
                         f"<table cellspacing='0' cellpadding='1' width='100%'>{bars}</table>")
        if res.range_pct <= 0:
            vs = tr("as mãos com que os oponentes fariam o que fizeram (posição e ação)",
                    "the hands the opponents would play this way (position and action)")
        elif res.range_pct >= 100:
            vs = tr("mãos aleatórias", "random hands")
        else:
            vs = tr(f"o top {res.range_pct}% das mãos", f"the top {res.range_pct}% of hands")
        lines.append("<p style='color:#9fb3ad; font-size:12px; margin-top:8px'>" + tr(
            f"A chance é calculada contra {vs}, até o river. A análise completa está ao lado das cartas.",
            f"The chance is computed against {vs}, to the river. The full analysis is next to the cards.") + "</p>")
        self.analysis.setText("".join(lines))
