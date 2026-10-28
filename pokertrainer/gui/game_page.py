"""Treino de decisões: cartas, a situação de aposta, os botões de ação e a análise da jogada."""

from __future__ import annotations

import random
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QMenu, QScrollArea, QPushButton, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from pokertrainer import coach
from pokertrainer import decision as D
from pokertrainer import engine as E
from pokertrainer import settings as S
from pokertrainer.i18n import tr
from pokertrainer.gui import sound
from pokertrainer.gui.widgets import CARD_RATIO, CardWidget, DecisionMeter, DeckButton, Glass, PillLabel


@dataclass
class RoundResult:
    mode: S.Mode
    deal: E.Deal
    eq: E.EquityResult
    spot: D.Spot
    verdict: D.Verdict
    hero_score: int
    opp_scores: list[int]
    outcome: str          # "win" | "tie" | "lose"
    tips: list[tuple[str, list[str]]]   # (título da seção, dicas)
    n_opp: int
    replay: bool = False  # mão reexibida (ex.: troca de idioma ou revisão): não conta nas estatísticas
    range_pct: int = 0
    hand_type: str = ""


# ---------------------------------------------------------------- cálculo em segundo plano

class _Signals(QObject):
    done = Signal(int, object)


class EquityJob(QRunnable):
    """Chance da sua mão contra as faixas dos oponentes (a atual e a de quem pagaria a sua aposta/aumento)."""

    def __init__(self, token: int, deal: E.Deal, spot: D.Spot, n_opp: int, iters: int,
                 fixed_pct: int | None) -> None:
        super().__init__()
        self.token, self.deal, self.spot, self.n_opp, self.iters = token, deal, spot, n_opp, iters
        self.fixed_pct = fixed_pct
        self.signals = _Signals()
        self.cancelled = False

    def run(self) -> None:
        stop = lambda: self.cancelled  # noqa: E731
        d, sp = self.deal, self.spot
        board = d.visible_board
        now = D.opponent_ranges(sp, d, fixed_pct=self.fixed_pct)[: self.n_opp]
        iters = max(8000, self.iters // max(1, self.n_opp // 2))   # multiway: cada simulação custa mais
        r = E.equity(d.hero, board, self.n_opp, iters, cancel=stop, opp_ranges=now)
        if self.cancelled:
            return
        # contra quem pagaria a sua aposta/aumento (só faz diferença depois do flop ou contra um aumento)
        after = "call_raise" if sp.facing_bet else "call"
        if sp.street == 0 and sp.kind == "vs_raise":
            call_ranges = [list(D.R.band_combos(0, max(D.R.THREEBET_PCT * 2, sp.pre[0][1] // 2)))] + now[1:]
        elif sp.street >= 3 and self.fixed_pct is None:
            call_ranges = D.opponent_ranges(sp, d, after=after)[: self.n_opp]
        else:
            call_ranges = now
        r.eq_call = E.equity(d.hero, board, self.n_opp, max(4000, self.iters // 3), cancel=stop,
                             opp_ranges=call_ranges).equity if call_ranges is not now else r.equity
        if not self.cancelled:
            r.vs_random = E.equity(d.hero, board, self.n_opp, max(4000, self.iters // 4), cancel=stop).equity
        if not self.cancelled:
            self.signals.done.emit(self.token, r)


# ---------------------------------------------------------------- assento de oponente

class Seat(QWidget):
    def __init__(self, idx: int, parent=None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        self.name = QLabel(tr(f"Oponente {idx + 1}", f"Opponent {idx + 1}"))
        self.name.setAlignment(Qt.AlignCenter)
        self.name.setObjectName("muted")
        h = QHBoxLayout()
        h.setSpacing(0)
        h.setContentsMargins(0, 0, 0, 0)
        self.cards = [CardWidget(), CardWidget()]
        h.addStretch(1)
        for c in self.cards:
            h.addWidget(c)
        h.addStretch(1)
        v.addWidget(self.name)
        v.addLayout(h)
        self.info = PillLabel()
        v.addWidget(self.info)

    def set_height(self, h: int) -> None:
        for c in self.cards:
            c.set_card_height(h)
        self.info.setFixedWidth(max(self.cards[0].width() * 2, 130))


# ---------------------------------------------------------------- página

class TipsPanel(Glass):
    """Painel com as dicas da rodada, mostrado ao lado das cartas depois da revelação."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, alpha=185)
        self.setFixedWidth(340)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 10, 14)
        v.setSpacing(6)
        title = QLabel(tr("💡  Dicas desta mão", "💡  Tips for this hand"))
        title.setStyleSheet("font-size: 17px; font-weight: 800; color: #f5c542;")
        v.addWidget(title)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.body.setStyleSheet("font-size: 13px;")
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 8, 0)
        il.addWidget(self.body)
        il.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(inner)
        v.addWidget(self.scroll, 1)

    def show_waiting(self) -> None:
        self.body.setText("<p style='color:#9fb3ad'>" + tr(
            "Escolha sua jogada para ver a análise: a sua chance real, o preço da aposta, a melhor jogada e o que "
            "aconteceu nas cartas seguintes.",
            "Make your play to see the analysis: your actual chance, the price of the bet, the best play and "
            "what happened on the next cards.") + "</p>")

    def show_tips(self, sections: list[tuple[str, list[str]]]) -> None:
        html = []
        for name, items in sections:
            if not items:
                continue
            html.append(f"<p style='margin-top:10px; margin-bottom:2px; color:#9fb3ad; font-size:11px; "
                        f"font-weight:700; letter-spacing:1px'>{name.upper()}</p>")
            html.append("".join(f"<p style='margin:0 0 6px 0'>• {t}</p>" for t in items))
        self.body.setText("".join(html))
        self.scroll.verticalScrollBar().setValue(0)
        self.show()


class DeckView(QWidget):
    """Sobreposição com as 52 cartas: as já conhecidas ficam apagadas, as demais ainda podem aparecer."""

    SUIT_ORDER = (3, 2, 1, 0)   # espadas, copas, ouros, paus

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("DeckView { background: rgba(0, 0, 0, 120); }")
        self.setFocusPolicy(Qt.StrongFocus)
        self.panel = Glass(self, alpha=242)
        v = QVBoxLayout(self.panel)
        v.setContentsMargins(26, 18, 26, 22)
        v.setSpacing(4)
        head = QHBoxLayout()
        title = QLabel(tr("Cartas que ainda podem aparecer", "Cards that can still come"))
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: white;")
        head.addWidget(title)
        head.addStretch(1)
        close = QPushButton("✕")
        close.setObjectName("chip")
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip(tr("Fechar (Esc)", "Close (Esc)"))
        close.clicked.connect(self.hide)
        head.addWidget(close)
        v.addLayout(head)
        self._head_h = max(title.sizeHint().height(), close.sizeHint().height())
        self.sub = QLabel()
        self.sub.setObjectName("muted")
        self.sub.setWordWrap(True)
        v.addWidget(self.sub)
        v.addSpacing(10)
        grid = QGridLayout()
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(6)
        self.cards: dict[int, CardWidget] = {}
        for row, suit in enumerate(self.SUIT_ORDER):
            for col, rank in enumerate(range(12, -1, -1)):
                c = rank * 4 + suit
                w = CardWidget()
                w.dim_alpha = 195
                w.set_card(c, True)
                self.cards[c] = w
                grid.addWidget(w, row, col)
        v.addLayout(grid)
        self.hide()

    def show_for(self, known: list[int], revealed: bool) -> None:
        known_set = set(known)
        for c, w in self.cards.items():
            w.set_dimmed(c in known_set)
        left = 52 - len(known_set)
        if revealed:
            what = tr("suas cartas, as da mesa e as dos oponentes", "your cards, the board and the opponents' cards")
            self.sub.setText(tr(f"<b>{left} cartas</b> não apareceram nesta mão. Apagadas: {what}.",
                                f"<b>{left} cards</b> did not show up in this hand. Dimmed: {what}."))
        else:
            what = tr("suas cartas e as da mesa", "your cards and the board")
            self.sub.setText(tr(f"<b>{left} cartas</b> ainda não vistas. Apagadas: as já conhecidas ({what}). "
                                "As cartas dos oponentes, que você não vê, também estão entre as restantes.",
                                f"<b>{left} cards</b> not seen yet. Dimmed: the ones already known ({what}). "
                                "The opponents' hidden cards are also among the remaining ones."))
        self._fit()
        self.show()
        self.raise_()
        self.setFocus()

    def _fit(self) -> None:
        par = self.parentWidget()
        self.setGeometry(par.rect())
        avail_w = self.width() - 80 - 52
        avail_h = self.height() - 80 - 150
        h = min(avail_w / 13 * CARD_RATIO * 0.9, avail_h / 4 * 0.9, 130)
        for w in self.cards.values():
            w.set_card_height(int(h))
        inner = 13 * self.cards[0].width() + 12 * 2
        self.sub.setFixedWidth(inner)
        lay = self.panel.layout()
        m = lay.contentsMargins()
        pw = inner + m.left() + m.right()
        ch = self.cards[0].height()
        ph = (m.top() + m.bottom() + self._head_h + 4 + self.sub.heightForWidth(inner) + 4 + 10
              + 4 * ch + 3 * 6)
        self.panel.setGeometry((self.width() - pw) // 2, (self.height() - ph) // 2, pw, ph)

    def resize_to_parent(self) -> None:
        if self.isVisible():
            self._fit()

    def mousePressEvent(self, e) -> None:
        if not self.panel.geometry().contains(e.position().toPoint()):
            self.hide()

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.hide()
            e.accept()
            return
        super().keyPressEvent(e)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        par = self.parentWidget()
        if hasattr(par, "panel"):
            par.setFocus()


class _CardArea(QWidget):
    resized = Signal()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.resized.emit()


class GamePage(QWidget):
    roundStarted = Signal(object)    # S.Mode
    roundFinished = Signal(object)   # RoundResult
    equityReady = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.mode: S.Mode | None = None
        self.deal: E.Deal | None = None
        self.eq: E.EquityResult | None = None
        self.spot: D.Spot | None = None
        self.action: str | None = None      # jogada escolhida (None = ainda não decidiu)
        self.revealed = False
        self._token = 0
        self._job: EquityJob | None = None
        self._pending_reveal = False
        self.rng = random.Random()
        self.range_pct = 100
        self.focus_type: str | None = None
        self.n_opp = 1
        self.setFocusPolicy(Qt.StrongFocus)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(10)

        # área das cartas: ocupa só o espaço acima do painel e dimensiona as cartas pela própria altura
        self.area = _CardArea()
        self.area.resized.connect(self._layout_cards)
        al = QVBoxLayout(self.area)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(6)
        al.setSizeConstraint(QLayout.SetNoConstraint)
        self.area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        # oponentes: botão com a quantidade (menu 1..9) + botão de quantidade aleatória a cada mão
        self.opp_row = QWidget()
        orow = QHBoxLayout(self.opp_row)
        orow.setContentsMargins(0, 0, 0, 0)
        orow.setSpacing(6)
        orow.addStretch(1)
        self.opp_btn = QPushButton()
        self.opp_btn.setObjectName("chip")
        self.opp_btn.setCursor(Qt.PointingHandCursor)
        self.opp_btn.setToolTip(tr("Escolher o número de oponentes", "Choose the number of opponents"))
        menu = QMenu(self.opp_btn)
        self.opp_actions = QActionGroup(menu)
        for n in range(1, S.MAX_OPPONENTS + 1):
            a = QAction(tr(f"{n} oponente{'s' if n > 1 else ''}", f"{n} opponent{'s' if n > 1 else ''}"), menu)
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, k=n: self.set_opponents(k))
            self.opp_actions.addAction(a)
            menu.addAction(a)
        self.opp_btn.setMenu(menu)
        orow.addWidget(self.opp_btn)
        self.rand_btn = QPushButton(tr("🎲  Aleatório", "🎲  Random"))
        self.rand_btn.setObjectName("chip")
        self.rand_btn.setCheckable(True)
        self.rand_btn.setCursor(Qt.PointingHandCursor)
        self.rand_btn.setToolTip(tr(f"Sortear de 1 a {S.MAX_OPPONENTS} oponentes a cada mão",
                                    f"Draw 1 to {S.MAX_OPPONENTS} opponents at random every hand"))
        self.rand_btn.setChecked(S.get("random_opponents"))
        self.rand_btn.toggled.connect(self.set_random_opponents)
        orow.addWidget(self.rand_btn)
        self.range_btn = QPushButton()
        self.range_btn.setObjectName("chip")
        self.range_btn.setCursor(Qt.PointingHandCursor)
        self.range_btn.setToolTip(tr("Que mãos os oponentes jogam (faixa / range)",
                                     "Which hands the opponents play (range)"))
        rmenu = QMenu(self.range_btn)
        self.range_actions = QActionGroup(rmenu)
        for pct in coach.RANGES:
            a = QAction(coach.range_name(pct), rmenu)
            a.setCheckable(True)
            a.setData(pct)
            a.triggered.connect(lambda _=False, k=pct: self.set_range(k))
            self.range_actions.addAction(a)
            rmenu.addAction(a)
        self.range_btn.setMenu(rmenu)
        orow.addWidget(self.range_btn)
        for b in (self.opp_btn, self.rand_btn, self.range_btn):
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.focus_btn = QPushButton()
        self.focus_btn.setObjectName("chip")
        self.focus_btn.setCheckable(True)
        self.focus_btn.setChecked(True)
        self.focus_btn.setCursor(Qt.PointingHandCursor)
        self.focus_btn.setToolTip(tr("Treino focado: só mãos deste tipo. Clique para sair.",
                                     "Focused training: only hands of this type. Click to stop."))
        self.focus_btn.clicked.connect(lambda: self.set_focus(None))
        self.focus_btn.hide()
        orow.addWidget(self.focus_btn)
        orow.addStretch(1)
        al.addWidget(self.opp_row)
        self.opp_box = QWidget()
        self.opp_grid = QGridLayout(self.opp_box)
        self.opp_grid.setContentsMargins(0, 0, 0, 0)
        self.opp_grid.setHorizontalSpacing(18)
        self.opp_grid.setVerticalSpacing(4)
        al.addWidget(self.opp_box, 0, Qt.AlignHCenter)
        self.seats: list[Seat] = []

        al.addStretch(1)
        # pote e aposta da situação
        self.pot_lbl = QLabel(" ")
        self.pot_lbl.setAlignment(Qt.AlignCenter)
        self.pot_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffe7a3;")
        al.addWidget(self.pot_lbl)
        # mesa
        self.board_lbl = QLabel(tr("MESA", "BOARD"))
        self.board_lbl.setObjectName("rowLabel")
        self.board_lbl.setAlignment(Qt.AlignCenter)
        al.addWidget(self.board_lbl)
        bh = QHBoxLayout()
        bh.setSpacing(6)
        bh.addStretch(1)
        self.board_cards = [CardWidget() for _ in range(5)]
        for i, c in enumerate(self.board_cards):
            bh.addWidget(c)
            if i == 2 or i == 3:
                bh.addSpacing(10)  # separa flop / turn / river
        bh.addStretch(1)
        al.addLayout(bh)
        self.board_name = QLabel(" ")
        self.board_name.setAlignment(Qt.AlignCenter)
        self.board_name.setObjectName("muted")
        al.addWidget(self.board_name)

        al.addStretch(1)
        # sua mão
        self.hero_lbl = QLabel(tr("SUA MÃO", "YOUR HAND"))
        self.hero_lbl.setObjectName("rowLabel")
        self.hero_lbl.setAlignment(Qt.AlignCenter)
        al.addWidget(self.hero_lbl)
        hh = QHBoxLayout()
        hh.setSpacing(4)
        hh.addStretch(1)
        self.deck_btn = DeckButton()
        self.deck_btn.clicked.connect(self.show_deck)
        self._deck_spacer = QWidget()  # mantém as cartas da mão centralizadas
        hh.addWidget(self._deck_spacer)
        hh.addSpacing(18)
        self.hero_cards = [CardWidget(), CardWidget()]
        for c in self.hero_cards:
            hh.addWidget(c)
        hh.addSpacing(18)
        hh.addWidget(self.deck_btn, 0, Qt.AlignBottom)
        hh.addStretch(1)
        al.addLayout(hh)
        self.hand_name = QLabel(" ")
        self.hand_name.setObjectName("handName")
        self.hand_name.setAlignment(Qt.AlignCenter)
        al.addWidget(self.hand_name)
        al.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(self.area, 1)
        self.tips_panel = TipsPanel()
        row.addWidget(self.tips_panel)
        root.addLayout(row, 1)

        # painel da decisão
        self.panel = Glass(alpha=165)
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(22, 14, 22, 12)
        pv.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        qv = QVBoxLayout()
        qv.setSpacing(2)
        self.q_title = QLabel(" ")
        self.q_title.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.q_title.setWordWrap(True)
        self.q_sub = QLabel(" ")
        self.q_sub.setObjectName("muted")
        self.q_sub.setWordWrap(True)
        qv.addWidget(self.q_title)
        qv.addWidget(self.q_sub)
        top.addLayout(qv, 1)
        top.addSpacing(10)
        self.act_btns: dict[str, QPushButton] = {}
        for key, obj, tip in ((D.FOLD, "fold", tr("Desistir da mão (F)", "Fold the hand (F)")),
                              ("passive", "secondary", tr("Passar ou pagar (C)", "Check or call (C)")),
                              ("aggressive", "primary", tr("Apostar ou aumentar (R)", "Bet or raise (R)"))):
            b = QPushButton()
            b.setObjectName(obj)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumWidth(150)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self._act(k))
            self.act_btns[key] = b
            top.addWidget(b)
        self.next_btn = QPushButton(tr("Próxima mão (Espaço)  ▸", "Next hand (Space)  ▸"))
        self.next_btn.setObjectName("primary")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.setMinimumWidth(190)
        self.next_btn.setToolTip(tr("Próxima mão (Espaço, Enter ou S)", "Next hand (Space, Enter or S)"))
        self.next_btn.clicked.connect(lambda: self.new_round())   # clicked passa "checked": não repassar
        top.addWidget(self.next_btn)
        pv.addLayout(top)
        # tamanho da aposta/aumento (a nota também avalia o tamanho)
        self.size_row = QWidget()
        sr = QHBoxLayout(self.size_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(6)
        sr.addStretch(1)
        self.size_lbl = QLabel(tr("Tamanho:", "Size:"))
        self.size_lbl.setObjectName("muted")
        sr.addWidget(self.size_lbl)
        self.size_btns: list[QPushButton] = []
        for _ in range(4):
            b = QPushButton()
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, bt=b: self._pick_size(self.size_btns.index(bt)))
            sr.addWidget(b)
            self.size_btns.append(b)
        self.size = 0
        self.meter = DecisionMeter()
        # antes da decisão: tamanhos; depois: o medidor (mesmo espaço, o painel não cresce)
        self.lower = QStackedWidget()
        self.lower.addWidget(self.size_row)
        self.lower.addWidget(self.meter)
        self.lower.setFixedHeight(36)
        pv.addWidget(self.lower)
        root.addWidget(self.panel)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.deck_view = DeckView(self)

    # ------------------------------------------------------------ fluxo
    def start(self, mode: S.Mode) -> None:
        self.mode = mode
        self.new_round()

    def set_opponents(self, n: int) -> None:
        """Número fixo de oponentes escolhido no botão: desliga o aleatório e dá uma nova mão."""
        S.put("opponents", n)
        self.rand_btn.blockSignals(True)
        self.rand_btn.setChecked(False)
        self.rand_btn.blockSignals(False)
        S.put("random_opponents", False)
        self.new_round()

    def set_random_opponents(self, on: bool) -> None:
        S.put("random_opponents", on)
        # antes da decisão já sorteia; depois dela vale a partir da próxima mão
        if on and not self.revealed:
            self.new_round()

    def set_range(self, pct: int) -> None:
        S.put("opp_range", pct)
        self.new_round()

    def set_focus(self, hand_type: str | None) -> None:
        """Treino focado: só distribui mãos de um tipo (ex.: pares baixos). None desliga."""
        self.focus_type = hand_type
        if hand_type is None:
            self.focus_btn.hide()
        else:
            self.focus_btn.setText(f"🎯  {coach.hand_type_name(hand_type)}  ✕")
            self.focus_btn.show()
        if self.mode is not None and not self.revealed:
            self.new_round()

    @property
    def fixed_pct(self) -> int | None:
        """Faixa fixa dos oponentes (top X%, ignorando a ação) ou None = realista (conforme a ação)."""
        return None if self.range_pct <= 0 else self.range_pct

    def _deal_new(self, n_opp: int) -> tuple[E.Deal, D.Spot]:
        """Situação e cartas coerentes: as dos oponentes saem das faixas de quem fez o que fez."""
        visible = self.mode.visible
        if self.focus_type:
            want_pf = self.focus_type.startswith("pf_")
            if want_pf != (visible == 0):
                visible = 0 if want_pf else 3
            elif self.focus_type == "pp_draw" and visible == 5:
                visible = 3          # no river não há projeto
        spot = D.make_spot(self.rng, visible, n_opp)
        hb = D.deal_hero_board(spot, self.rng, n_opp)
        if self.focus_type:
            for _ in range(4000):
                if coach.hand_type(E.Deal(hb.hero, hb.board, [], hb.visible)) == self.focus_type:
                    break
                spot.hero_pre = (0, 100)     # no treino focado, qualquer mão do tipo
                hb = D.deal_hero_board(spot, self.rng, n_opp)
        return D.deal_opponents(spot, hb, self.rng, n_opp, self.fixed_pct), spot

    def _update_opp_button(self) -> None:
        n = self.n_opp
        self.opp_btn.setText(tr(f"{n} OPONENTE{'S' if n > 1 else ''}", f"{n} OPPONENT{'S' if n > 1 else ''}"))
        for i, a in enumerate(self.opp_actions.actions()):
            a.setChecked(i + 1 == n)
        if self.rand_btn.isChecked() != S.get("random_opponents"):
            self.rand_btn.blockSignals(True)
            self.rand_btn.setChecked(S.get("random_opponents"))
            self.rand_btn.blockSignals(False)
        self.range_btn.setText(tr("Faixa: ", "Range: ") + coach.range_name(self.range_pct, short=True) + " ")
        for a in self.range_actions.actions():
            a.setChecked(a.data() == self.range_pct)

    def new_round(self, deal: E.Deal | None = None, spot: D.Spot | None = None,
                  range_pct: int | None = None) -> None:
        """Nova mão. `deal` e `spot` retomam uma mão já distribuída (troca de idioma ou revisão)."""
        if self.mode is None:
            return
        if deal is not None:
            n_opp = len(deal.opponents)
        elif S.get("random_opponents"):
            n_opp = self.rng.randint(1, S.MAX_OPPONENTS)
        else:
            n_opp = S.get("opponents")
        anim = S.get("animations") and deal is None
        self.n_opp = n_opp
        self.range_pct = range_pct if range_pct is not None else (S.get("opp_range") if deal is None else 0)
        if deal is not None:
            self.deal = d = deal
            self.spot = sp = spot if spot is not None else D.make_spot(self.rng, d.visible, n_opp)
        else:
            d, sp = self._deal_new(n_opp)
            self.deal, self.spot = d, sp
        self.action = None
        self.eq = None
        self.revealed = False
        self._pending_reveal = False
        self._build_seats(n_opp)
        self._update_opp_button()

        if deal is None:
            sound.play("deal")
        for i, c in enumerate(self.hero_cards):
            c.set_card(d.hero[i], True, animate=anim, delay_ms=80 + 140 * i)
            c.set_highlight(False)
            c.set_dimmed(False)
        for i, c in enumerate(self.board_cards):
            c.set_card(d.board[i], i < d.visible, animate=anim, delay_ms=360 + 110 * i)
            c.set_highlight(False)
        acts = D.seat_actions(sp, n_opp)
        for k, seat in enumerate(self.seats):
            for j, c in enumerate(seat.cards):
                c.set_card(d.opponents[k][j], False)
                c.set_highlight(False)
                c.set_dimmed(False)
            seat.info.setText(acts[k])
            seat.info.setToolTip("")
            seat.name.setStyleSheet("")

        show_name = S.get("show_hand_name")
        self.hand_name.setText(E.describe_cards(d.hero + d.visible_board) if show_name else " ")
        self.board_name.setText(" ")
        pos = tr(f"Você: {sp.hero_pos}", f"You: {sp.hero_pos}") if sp.hero_pos else ""
        pot_txt = tr(f"Pote {D.bb(sp.pot)}", f"Pot {D.bb(sp.pot)}")
        bet_txt = tr(f"  ·  aposta {D.bb(sp.bet)}", f"  ·  bet {D.bb(sp.bet)}") if sp.facing_bet and sp.street else ""
        self.pot_lbl.setText("💰  " + "  ·  ".join(x for x in (pos, pot_txt) if x) + bet_txt +
                             tr(f"  ·  stack {D.bb(sp.stack)}", f"  ·  stack {D.bb(sp.stack)}"))
        q, detail = D.situation(sp, n_opp)
        rng_txt = ""
        if self.fixed_pct is not None:
            rng_txt = tr(f" Oponentes jogam o {coach.range_name(self.range_pct)}, sem levar em conta a ação.",
                         f" Opponents play the {coach.range_name(self.range_pct)}, regardless of their action.")
        self.q_title.setText(q)
        self.q_sub.setText(detail + rng_txt)
        fold, passive, aggressive = sp.actions()
        self.act_btns[D.FOLD].setText(tr("Desistir", "Fold"))
        self.act_btns[D.FOLD].setEnabled(sp.can_fold)
        self.act_btns[D.FOLD].setToolTip(tr("Desistir da mão (F)", "Fold the hand (F)") if sp.can_fold else
                                         tr("Ninguém apostou: passar é de graça.", "Nobody bet: checking is free."))
        self.act_btns["passive"].setText(D.button_text(sp, passive))
        self._setup_sizes()
        self.act_btns["passive"].setEnabled(True)
        self.act_btns["aggressive"].setEnabled(True)
        for b in self.act_btns.values():
            b.show()
        self.next_btn.hide()
        self.meter.clear("")
        self.lower.setCurrentWidget(self.size_row)
        self.lower.setFixedHeight(36)
        self.setFocus()
        self.tips_panel.show_waiting()
        self.deck_view.hide()
        self._update_deck()
        self._layout_cards()
        self._start_equity()
        self.roundStarted.emit(self.mode)

    def known_cards(self) -> list[int]:
        d = self.deal
        if d is None:
            return []
        if self.revealed:
            return d.hero + d.board + [c for o in d.opponents for c in o]
        return d.hero + d.visible_board

    def show_deck(self) -> None:
        self.deck_view.show_for(self.known_cards(), self.revealed)

    def _update_deck(self) -> None:
        self.deck_btn.set_remaining(52 - len(self.known_cards()))
        if self.deck_view.isVisible():
            self.show_deck()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        wide = self.width() >= 980
        self.tips_panel.setFixedWidth(340 if wide else 280)
        for b in self.act_btns.values():
            b.setMinimumWidth(150 if wide else 112)
        self.deck_view.resize_to_parent()

    def restore(self, mode: S.Mode, deal: E.Deal, eq: E.EquityResult | None, spot: D.Spot, action: str | None,
                revealed: bool, range_pct: int = 0, size: int = 0) -> None:
        """Mostra de novo uma mão (mesmas cartas, situação e jogada), sem animação nem contar pontos."""
        self.mode = mode
        self.new_round(deal, spot=spot, range_pct=range_pct)
        if eq is not None:
            if self._job is not None:
                self._job.cancelled = True
                self._job = None
            self._token += 1
            self.eq = eq
        if revealed and eq is not None:
            self.action = action
            if size:
                self.size = size
            self._reveal(replay=True)

    def _setup_sizes(self) -> None:
        """Botões de tamanho da aposta/aumento (só aparecem quando há mais de uma opção)."""
        sp = self.spot
        sizes = sp.sizes or [("", sp.hero_bet)]
        many = len(sp.sizes) > 1
        self.size_lbl.setVisible(many)
        for i, b in enumerate(self.size_btns):
            label = sizes[i][0] if i < len(sizes) else ""
            if label and sp.street and label in ("⅓", "½", "⅔"):
                label += tr(" pote", " pot")
            b.setText(label)
            b.setVisible(many and bool(label))
        self.size_row.setEnabled(True)
        default = min(range(len(sizes)), key=lambda i: abs(sizes[i][1] - sp.hero_bet))
        self._pick_size(default)

    def _pick_size(self, i: int) -> None:
        sp = self.spot
        sizes = sp.sizes or [("", sp.hero_bet)]
        i = max(0, min(i, len(sizes) - 1))
        self.size = sizes[i][1]
        for k, b in enumerate(self.size_btns):
            b.setChecked(k == i)
        self.act_btns["aggressive"].setText(D.button_text(sp, sp.actions()[2], self.size))

    def _start_equity(self) -> None:
        if self._job is not None:
            self._job.cancelled = True
        self._token += 1
        d = self.deal
        job = EquityJob(self._token, d, self.spot, self.n_opp, S.get("iterations"), self.fixed_pct)
        job.signals.done.connect(self._on_equity)
        self._job = job
        QThreadPool.globalInstance().start(job)

    def _on_equity(self, token: int, r: E.EquityResult) -> None:
        if token != self._token:
            return
        self.eq = r
        self._job = None
        self.equityReady.emit()
        if self._pending_reveal:
            self._reveal()

    def _act(self, which: str) -> None:
        """`which`: "fold", "passive" (passar/pagar) ou "aggressive" (apostar/aumentar)."""
        if self.revealed or self.spot is None or self.action is not None:
            return
        fold, passive, aggressive = self.spot.actions()
        action = {"fold": fold, "passive": passive, "aggressive": aggressive}[which]
        if action == D.FOLD and not self.spot.can_fold:
            return
        self.size_row.setEnabled(False)
        self.action = action
        sound.play({D.FOLD: "fold", D.CHECK: "check", D.CALL: "call", D.BET: "bet", D.RAISE: "bet"}[action])
        if self.eq is None:
            self._pending_reveal = True
            for b in self.act_btns.values():
                b.setEnabled(False)
            self.act_btns[which].setText(tr("Calculando…", "Calculating…"))
        else:
            self._reveal()

    def _verdict(self) -> D.Verdict:
        d = self.deal
        outs = D.R.draw_outs(d.hero, d.visible_board)
        return D.evaluate(self.spot, self.eq.equity, self.n_opp, outs, self.action,
                          eq_call=getattr(self.eq, "eq_call", None), hero=d.hero, board=d.visible_board,
                          size=self.size if self.action in (D.BET, D.RAISE) else None)

    def _meter_result(self, v: D.Verdict) -> None:
        sp = self.spot
        if sp.kind == "open":
            lim = 1 - D.R.open_pct(sp.hero_pos) / 100
            zones = [(0.0, lim, D.FOLD, D.action_name(D.FOLD)), (lim, 1.0, D.RAISE, tr("Abrir", "Open"))]
            marks = [(lim, tr(f"abrir do {sp.hero_pos}: top {D.R.open_pct(sp.hero_pos)}%",
                              f"open from {sp.hero_pos}: top {D.R.open_pct(sp.hero_pos)}%"))]
            self.meter.set_result(zones, marks, 1 - v.pct / 100, v.best,
                                  tr(f"Sua mão: top {v.pct:.0f}%", f"Your hand: top {v.pct:.0f}%"))
            return
        if sp.kind == "limped":
            fair = 1 / (self.n_opp + 1)
            thr = fair + (1 - fair) * 0.2
            zones = [(0.0, thr, D.CHECK, D.action_name(D.CHECK)), (thr, 1.0, D.RAISE, D.action_name(D.RAISE))]
            marks = [(thr, tr(f"aumentar ≥ {thr:.0%}", f"raise ≥ {thr:.0%}"))]
            self.meter.set_result(zones, marks, v.equity, v.best)
            return
        if sp.facing_bet:
            need = max(0.0, v.need_eff or v.need)
            second = v.best if v.best in (D.CALL, D.RAISE) else D.CALL
            zones = [(0.0, need, D.FOLD, D.action_name(D.FOLD)), (need, 1.0, second, D.action_name(second))]
            marks = [(need, tr(f"pagar ≥ {need:.0%}", f"call ≥ {need:.0%}"))]
            self.meter.set_result(zones, marks, v.equity, v.best,
                                  tr(f"Sua chance contra a faixa deles: {v.equity:.0%}",
                                     f"Your chance vs their range: {v.equity:.0%}"))
            return
        thr = D.value_threshold(self.n_opp)
        zones = [(0.0, thr, D.CHECK, D.action_name(D.CHECK)), (thr, 1.0, D.BET, D.action_name(D.BET))]
        marks = [(thr, tr(f"apostar por valor ≥ {thr:.0%}", f"value bet ≥ {thr:.0%}"))]
        self.meter.set_result(zones, marks, v.value, v.best,
                              tr(f"Contra quem pagaria: {v.value:.0%}", f"Vs. hands that would call: {v.value:.0%}"))

    def _reveal(self, replay: bool = False) -> None:
        d, r, sp = self.deal, self.eq, self.spot
        self.revealed = True
        self._pending_reveal = False
        anim = S.get("animations") and not replay
        v = self._verdict()

        # cartas
        delay = 0
        for seat in self.seats:
            for c in seat.cards:
                c.flip_up(delay, animate=anim)
                delay += 70
        for i in range(d.visible, 5):
            self.board_cards[i].flip_up(delay + 150 * (i - d.visible), animate=anim)
        if not replay and self.action:
            sound.play("flip")
            if v.quality == "best":
                QTimer.singleShot(450, lambda: sound.play("win"))
        hs, opp = E.showdown(d)
        best = max([hs] + opp)
        winners = (hs == best) + sum(o == best for o in opp)
        outcome = "win" if hs == best and winners == 1 else "tie" if hs == best else "lose"
        for k, seat in enumerate(self.seats):
            won = opp[k] == best
            seat.info.setText(E.category_name(opp[k] >> 20))
            seat.info.setToolTip(E.describe(opp[k]))
            seat.name.setStyleSheet("color: #f5c542; font-weight: 700;" if won else "")
            for c in seat.cards:
                c.set_highlight(won)
                c.set_dimmed(not won)
        for c in self.hero_cards:
            c.set_highlight(hs == best)
            c.set_dimmed(False)
        self.hand_name.setText(E.describe(hs))
        board_cat = E.board_category(d.board)
        self.board_name.setText(tr("Na mesa: ", "On the board: ") + E.category_name(board_cat).lower()
                                if board_cat else " ")

        self._meter_result(v)
        label, color = D.quality_label(v.quality)
        best_txt = D.action_name(v.best).lower()
        if self.action:
            mine = D.action_name(self.action).lower()
            head = f"<span style='color:{color}'>{label}</span> — "
            self.q_title.setText(head + (tr(f"você escolheu {mine}.", f"you chose to {mine}.") if v.quality == "best"
                                         else tr(f"você escolheu {mine}; o melhor era {best_txt}.",
                                                 f"you chose to {mine}; the best play was to {best_txt}.")))
        else:
            self.q_title.setText(tr(f"Melhor jogada: {best_txt}.", f"Best play: {best_txt}."))
        res_txt = tr({"win": "você venceu", "tie": "deu empate", "lose": "você perdeu"}[outcome],
                     {"win": "you won", "tie": "it was a tie", "lose": "you lost"}[outcome])
        price = (tr(f" · preço para pagar {v.need:.0%}", f" · price to call {v.need:.0%}")
                 if sp.facing_bet and sp.kind != "open" else "")
        if sp.kind == "open":
            self.q_sub.setText(tr(f"Sua mão está no top {v.pct:.0f}%; do {sp.hero_pos} abre-se até o top "
                                  f"{D.R.open_pct(sp.hero_pos)}%. Nesta mão {res_txt}.",
                                  f"Your hand is in the top {v.pct:.0f}%; from {sp.hero_pos} you open up to the top "
                                  f"{D.R.open_pct(sp.hero_pos)}%. This hand {res_txt}."))
        else:
            self.q_sub.setText(tr(f"Sua chance contra a faixa deles: {r.equity:.0%}{price}. Nesta mão {res_txt} — o "
                                  "resultado de uma mão não muda a qualidade da decisão.",
                                  f"Your chance vs their range: {r.equity:.0%}{price}. This hand {res_txt} — one "
                                  "result doesn't change the quality of the decision."))
        why = coach.explain(d, r, self.n_opp)
        if self.fixed_pct is not None and self.fixed_pct < 100:
            why = coach.range_tips(d, r, self.fixed_pct) + why
        tips = [(tr("Sua decisão", "Your decision"),
                 D.feedback(sp, v, self.n_opp, None if self.fixed_pct else r.vs_random)),
                (tr("O que aconteceu", "What happened"), coach.runout_story(d, r, hs, opp)),
                (tr("Por que esta mão vale isso", "Why this hand is worth that"), why)]
        for b in self.act_btns.values():
            b.hide()
        self.lower.setCurrentWidget(self.meter)
        self.lower.setFixedHeight(self.meter.height())
        self.next_btn.show()
        self.setFocus()

        self.tips_panel.show_tips(tips)
        self._update_deck()
        self.roundFinished.emit(RoundResult(
            mode=self.mode, deal=d, eq=r, spot=sp, verdict=v, hero_score=hs, opp_scores=opp, outcome=outcome,
            tips=tips, n_opp=self.n_opp, replay=replay or not self.action, range_pct=self.range_pct,
            hand_type=coach.hand_type(d)))

    # ------------------------------------------------------------ layout
    def _build_seats(self, n: int) -> None:
        if len(self.seats) == n:
            return
        for s in self.seats:
            s.setParent(None)
            s.deleteLater()
        self.seats = [Seat(i) for i in range(n)]
        cols = n if n <= 5 else (n + 1) // 2
        for i, s in enumerate(self.seats):
            self.opp_grid.addWidget(s, i // cols, i % cols, Qt.AlignCenter)

    def _layout_cards(self) -> None:
        w = self.area.width()
        n = max(1, len(self.seats))
        rows = 1 if n <= 5 else 2
        cols = n if n <= 5 else (n + 1) // 2
        # espaço da área menos textos e espaçamentos
        labels = (self.opp_row, self.pot_lbl, self.board_lbl, self.board_name, self.hero_lbl, self.hand_name)
        texts = sum(x.sizeHint().height() for x in labels if not x.isHidden())
        if self.seats:
            st = self.seats[0]
            texts += rows * (st.name.sizeHint().height() + st.info.sizeHint().height() + 4) + (rows - 1) * 4
        free = self.area.height() - texts - 10 * 6 - 8
        free = max(160, free) / 1.12  # cada carta tem ~12% de margem para sombra/brilho
        hero_h = free * 0.49
        board_h = free * 0.31
        opp_h = free * 0.20 / rows
        # limites por largura
        board_h = min(board_h, (w - 60) / 5 * CARD_RATIO * 0.88)
        # linha da sua mão: [espaçador] 18 [carta] [carta] 18 [monte]; em áreas estreitas o espaçador some
        narrow = w < 640
        deck_w = 118
        side = deck_w + 36 + (0 if narrow else deck_w)
        hero_h = min(hero_h, (w - side - 20) / 2 / 1.06 * CARD_RATIO, 340)
        opp_h = min(opp_h, (w - 18 * cols) / (cols * 2) * CARD_RATIO * 0.88, board_h * 0.85)
        for c in self.hero_cards:
            c.set_card_height(int(hero_h))
        self.deck_btn.set_card_height(int(hero_h * 0.5))
        self._deck_spacer.setFixedSize(0 if narrow else self.deck_btn.width(), 1)
        for c in self.board_cards:
            c.set_card_height(int(board_h))
        for s in self.seats:
            s.set_height(int(max(44, opp_h)))

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, Qt.Key_S):
            if self.revealed:
                self.new_round()
            return
        if not self.revealed and self.action is None:
            which = {Qt.Key_F: "fold", Qt.Key_C: "passive", Qt.Key_K: "passive", Qt.Key_R: "aggressive",
                     Qt.Key_B: "aggressive"}.get(k)
            if which:
                self._act(which)
                return
        super().keyPressEvent(e)
