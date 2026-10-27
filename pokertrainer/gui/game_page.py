"""Tela do jogo: cartas, barra de palpite e revelação."""

from __future__ import annotations

import random
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QMenu, QScrollArea, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from pokertrainer import coach
from pokertrainer import engine as E
from pokertrainer import settings as S
from pokertrainer.i18n import tr
from pokertrainer.gui import sound
from pokertrainer.gui.widgets import CARD_RATIO, CardWidget, DeckButton, Glass, GuessBar, PillLabel


@dataclass
class RoundResult:
    mode: S.Mode
    deal: E.Deal
    guess: int
    eq: E.EquityResult
    error_pp: float
    rating: coach.Rating
    hero_score: int
    opp_scores: list[int]
    outcome: str          # "win" | "tie" | "lose"
    tips: list[tuple[str, list[str]]]   # (título da seção, dicas)
    n_opp: int
    replay: bool = False  # mão reexibida (ex.: troca de idioma): não conta nas estatísticas
    spot: coach.PotSpot | None = None     # modo pot odds
    called: bool | None = None
    good_decision: bool | None = None
    range_pct: int = 100
    hand_type: str = ""


def question() -> str:
    return tr("Qual a chance de a sua mão vencer?", "What is your hand's chance of winning?")


# ---------------------------------------------------------------- cálculo em segundo plano

class _Signals(QObject):
    done = Signal(int, object)


class EquityJob(QRunnable):
    def __init__(self, token: int, hero, board, n_opp: int, iters: int, combos=None) -> None:
        super().__init__()
        self.token, self.hero, self.board, self.n_opp, self.iters = token, hero, board, n_opp, iters
        self.combos = combos
        self.signals = _Signals()
        self.cancelled = False

    def run(self) -> None:
        stop = lambda: self.cancelled  # noqa: E731
        r = E.equity(self.hero, self.board, self.n_opp, self.iters, cancel=stop, opp_combos=self.combos)
        if self.combos is not None and not self.cancelled:
            # para comparar: a mesma mão contra cartas aleatórias
            r.vs_random = E.equity(self.hero, self.board, self.n_opp, max(4000, self.iters // 4), cancel=stop).equity
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
            "Confirme seu palpite para ver as dicas sobre esta mão: onde você errou, o que aconteceu na mesa e "
            "como estimar melhor.",
            "Confirm your guess to see tips about this hand: where you went wrong, what happened on the board "
            "and how to estimate better.") + "</p>")

    def show_tips(self, rating, sections: list[tuple[str, list[str]]]) -> None:
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
        if hasattr(par, "bar"):
            par.bar.setFocus()


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
        self.revealed = False
        self._token = 0
        self._job: EquityJob | None = None
        self._pending_reveal = False
        self.rng = random.Random()
        self.spot: coach.PotSpot | None = None
        self.called: bool | None = None
        self.range_pct = 100
        self.focus_type: str | None = None
        self.n_opp = 1

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
        # pote (modo pot odds)
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

        # painel do palpite
        self.panel = Glass(alpha=165)
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(22, 14, 22, 16)
        pv.setSpacing(6)
        top = QHBoxLayout()
        self.q_title = q = QLabel(question())
        q.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.q_sub = QLabel("")
        self.q_sub.setObjectName("muted")
        self.q_sub.setWordWrap(True)
        qv = QVBoxLayout()
        qv.setSpacing(0)
        qv.addWidget(q)
        qv.addWidget(self.q_sub)
        top.addLayout(qv, 1)
        self.value_lbl = QLabel("50%")
        self.value_lbl.setObjectName("bigValue")
        top.addWidget(self.value_lbl)
        top.addSpacing(16)
        self.action_btn = QPushButton(tr("Confirmar", "Confirm"))
        self.action_btn.setObjectName("primary")
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.setMinimumWidth(170)
        self.action_btn.clicked.connect(self._on_action)
        top.addWidget(self.action_btn)
        self.fold_btn = QPushButton(tr("Desistir", "Fold"))
        self.fold_btn.setObjectName("fold")
        self.fold_btn.setCursor(Qt.PointingHandCursor)
        self.fold_btn.setMinimumWidth(120)
        self.fold_btn.setToolTip(tr("Desistir da mão (tecla F)", "Fold the hand (F key)"))
        self.fold_btn.clicked.connect(lambda: self._decide(False))
        self.call_btn = QPushButton()
        self.call_btn.setObjectName("primary")
        self.call_btn.setCursor(Qt.PointingHandCursor)
        self.call_btn.setMinimumWidth(150)
        self.call_btn.setToolTip(tr("Pagar a aposta (tecla C)", "Call the bet (C key)"))
        self.call_btn.clicked.connect(lambda: self._decide(True))
        top.addWidget(self.fold_btn)
        top.addWidget(self.call_btn)
        pv.addLayout(top)
        self.bar = GuessBar()
        self.bar.valueChanged.connect(lambda v: self.value_lbl.setText(f"{v}%"))
        pv.addWidget(self.bar)
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
        # se ainda não palpitou, já sorteia; depois da revelação vale a partir da próxima mão
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
    def pot_mode(self) -> bool:
        return self.mode is not None and self.mode.key == "potodds"

    def _deal_new(self, n_opp: int, combos) -> E.Deal:
        visible = self.mode.visible if self.mode.visible >= 0 else self.rng.choice([3, 4])
        if self.focus_type:
            want_pf = self.focus_type.startswith("pf_")
            if want_pf != (visible == 0):
                visible = 0 if want_pf else (visible if visible > 0 else 3)
            for _ in range(4000):
                d = E.deal(visible, n_opp, self.rng, combos)
                if coach.hand_type(d) == self.focus_type:
                    return d
        return E.deal(visible, n_opp, self.rng, combos)

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

    def new_round(self, deal: E.Deal | None = None, spot: coach.PotSpot | None = None,
                  range_pct: int | None = None) -> None:
        """Nova mão. `deal` (e `spot`/`range_pct`) retomam uma mão já distribuída: troca de idioma ou revisão."""
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
        self.range_pct = range_pct if range_pct is not None else (S.get("opp_range") if deal is None else 100)
        self.combos = coach.range_combos(self.range_pct)
        self.deal = d = deal or self._deal_new(n_opp, self.combos)
        self.spot = spot if spot is not None else (coach.make_spot(self.rng, n_opp) if self.pot_mode else None)
        self.called = None
        self.eq = None
        self.revealed = False
        self._pending_reveal = False
        self._build_seats(n_opp)
        self._update_opp_button()

        if deal is None:
            sound.play("deal")
        for i, c in enumerate(self.hero_cards):
            c.set_card(d.hero[i], True, animate=anim, delay_ms=80 + 140 * i)
        for i, c in enumerate(self.board_cards):
            c.set_card(d.board[i], i < d.visible, animate=anim, delay_ms=360 + 110 * i)
        for k, seat in enumerate(self.seats):
            for j, c in enumerate(seat.cards):
                c.set_card(d.opponents[k][j], False)
            seat.info.setText(" ")
            seat.name.setStyleSheet("")
        if self.spot:
            for k, seat in enumerate(self.seats):
                seat.info.setText(tr(f"apostou {self.spot.bet}", f"bet {self.spot.bet}") if k == 0 else
                                  tr(f"pagou {self.spot.bet}", f"called {self.spot.bet}"))

        show_name = S.get("show_hand_name")
        self.hand_name.setText(E.describe_cards(d.hero + d.visible_board) if show_name else " ")
        self.board_name.setText(" ")
        vis = tr({0: "antes do flop", 3: "após o flop", 4: "após o turn"}[d.visible],
                 {0: "before the flop", 3: "after the flop", 4: "after the turn"}[d.visible])
        street_key = {0: "preflop", 3: "flop", 4: "turn"}[d.visible]
        sc = coach.scenario(street_key, n_opp)
        rng_txt = ""
        if self.range_pct < 100:
            # a escala pré-calculada vale para mãos aleatórias; contra faixas usa a escala inteira
            sc = coach.Scenario(0, 100, sc.fair, [])
            rng_txt = tr(f" Oponentes jogam só o {coach.range_name(self.range_pct)}.",
                         f" Opponents only play the {coach.range_name(self.range_pct)}.")
        if self.spot:
            sp = self.spot
            callers = tr(f", {sp.callers} pagaram", f", {sp.callers} called") if sp.callers else ""
            self.pot_lbl.setText(tr(f"💰  Pote {sp.pot}  ·  Oponente 1 apostou {sp.bet}{callers}  ·  "
                                    f"pagar {sp.to_call} → pote final {sp.final_pot}",
                                    f"💰  Pot {sp.pot}  ·  Opponent 1 bet {sp.bet}{callers}  ·  "
                                    f"call {sp.to_call} → final pot {sp.final_pot}"))
            self.pot_lbl.show()
            self.q_sub.setText(tr(f"{n_opp + 1} jogadores ({vis}). Estime sua chance e decida: pagar {sp.to_call} "
                                  f"ou desistir?",
                                  f"{n_opp + 1} players ({vis}). Estimate your chance and decide: call "
                                  f"{sp.to_call} or fold?") + rng_txt)
        else:
            self.pot_lbl.hide()
            self.q_sub.setText(tr(f"{n_opp + 1} jogadores na mesa ({vis}): a chance média é {sc.fair:.0f}%. "
                                  "Sua mão está acima ou abaixo disso?",
                                  f"{n_opp + 1} players at the table ({vis}): the average chance is {sc.fair:.0f}%. "
                                  "Is your hand above or below that?") + rng_txt)
        self.bar.set_answer(None)
        self.bar.set_scale(sc.lo, sc.hi, sc.fair, sc.hist, captions=self.range_pct >= 100)
        self.bar.set_threshold(None)
        self.bar.setValue(sc.fair)
        self.value_lbl.setText(f"{self.bar.value()}%")
        self.q_title.setText(question())
        self.action_btn.setText(tr("Confirmar", "Confirm"))
        self.action_btn.setEnabled(True)
        self.action_btn.setVisible(self.spot is None)
        for b in (self.fold_btn, self.call_btn):
            b.setVisible(self.spot is not None)
            b.setEnabled(True)
        if self.spot:
            self.call_btn.setText(tr(f"Pagar {self.spot.to_call}", f"Call {self.spot.to_call}"))
            self.fold_btn.setText(tr("Desistir", "Fold"))
        self.bar.setFocus()
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
        self.deck_view.resize_to_parent()

    def restore(self, mode: S.Mode, deal: E.Deal, eq: E.EquityResult | None, guess: int, revealed: bool,
                spot: coach.PotSpot | None = None, called: bool | None = None, range_pct: int = 100) -> None:
        """Mostra de novo uma mão (mesmas cartas, palpite e resultado), sem animação nem contar pontos."""
        self.mode = mode
        self.new_round(deal, spot=spot, range_pct=range_pct)
        self.called = called
        if eq is not None:
            if self._job is not None:
                self._job.cancelled = True
                self._job = None
            self._token += 1
            self.eq = eq
        self.bar.setValue(guess)
        self.value_lbl.setText(f"{self.bar.value()}%")
        if revealed and eq is not None:
            self._reveal(replay=True)

    def _start_equity(self) -> None:
        if self._job is not None:
            self._job.cancelled = True
        self._token += 1
        d = self.deal
        job = EquityJob(self._token, d.hero, d.visible_board, self.n_opp, S.get("iterations"), self.combos)
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

    def _on_action(self) -> None:
        if self.revealed:
            self.new_round()
        elif self.spot is not None:
            return  # no modo pot odds a resposta é pagar ou desistir
        elif self.eq is None:
            self._pending_reveal = True
            self.action_btn.setText(tr("Calculando…", "Calculating…"))
            self.action_btn.setEnabled(False)
        else:
            self._reveal()

    def _decide(self, called: bool) -> None:
        if self.revealed or self.spot is None:
            return
        self.called = called
        if self.eq is None:
            self._pending_reveal = True
            for b in (self.fold_btn, self.call_btn):
                b.setEnabled(False)
            (self.call_btn if called else self.fold_btn).setText(tr("Calculando…", "Calculating…"))
        else:
            self._reveal()

    def _reveal(self, replay: bool = False) -> None:
        d, r = self.deal, self.eq
        self.revealed = True
        self._pending_reveal = False
        anim = S.get("animations") and not replay
        guess = self.bar.value()
        err = abs(guess - r.equity * 100)
        rating = coach.rate(err, S.get("tolerance"))

        # cartas
        delay = 0
        for k, seat in enumerate(self.seats):
            for c in seat.cards:
                c.flip_up(delay, animate=anim)
                delay += 70
        for i in range(d.visible, 5):
            self.board_cards[i].flip_up(delay + 150 * (i - d.visible), animate=anim)

        if not replay:
            sound.play("flip")
            if rating.hit:
                QTimer.singleShot(450, lambda: sound.play("win" if rating.points >= 90 else "chip"))
        hs, opp = E.showdown(d)
        best = max([hs] + opp)
        winners = (hs == best) + sum(o == best for o in opp)
        outcome = "win" if hs == best and winners == 1 else "tie" if hs == best else "lose"
        for k, seat in enumerate(self.seats):
            won = opp[k] == best
            seat.info.setText(E.describe(opp[k]))
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

        self.bar.set_answer(r.equity)
        self.value_lbl.setText(f"{guess}%")
        res_txt = tr({"win": "você venceu", "tie": "deu empate", "lose": "você perdeu"}[outcome],
                     {"win": "you won", "tie": "it was a tie", "lose": "you lost"}[outcome])
        head = f"<span style='color:{rating.color}'>{rating.label}</span> — "
        self.q_title.setText(head + tr(f"chance real {r.equity * 100:.1f}%, seu palpite {guess}% "
                                       f"(erro de {err:.1f} pontos)",
                                       f"actual chance {r.equity * 100:.1f}%, your guess {guess}% "
                                       f"(off by {err:.1f} points)"))
        self.q_sub.setText(tr(f"Nesta rodada {res_txt}. Uma mão isolada não muda a probabilidade — veja a análise "
                              "ao lado.",
                              f"This round {res_txt}. A single hand doesn't change the probability — see the "
                              "analysis on the side."))
        good = None
        tips = [(tr("Seu palpite", "Your guess"), coach.guess_feedback(d, r, self.n_opp, guess, S.get("tolerance"),
                                                                     self.range_pct))]
        if self.spot is not None and self.called is not None:
            sp = self.spot
            good = (r.equity >= sp.need) == self.called or abs(r.equity - sp.need) < 0.01
            self.bar.set_threshold(sp.need * 100)
            act = tr("pagou", "called") if self.called else tr("desistiu", "folded")
            mark = ("<span style='color:#3ddc84'>" + tr("✔ decisão certa", "✔ right decision") if good else
                    "<span style='color:#ff6b6b'>" + tr("✘ decisão errada", "✘ wrong decision")) + "</span>"
            self.q_sub.setText(tr(f"Você {act}: {mark}. Precisava de {sp.need:.0%} para pagar; pagar vale "
                                  f"{sp.ev_call(r.equity):+.0f} fichas em média. Nesta rodada {res_txt}.",
                                  f"You {act}: {mark}. You needed {sp.need:.0%} to call; calling is worth "
                                  f"{sp.ev_call(r.equity):+.0f} chips on average. This round {res_txt}."))
            tips.append((tr("Pot odds", "Pot odds"), coach.decision_tips(sp, r.equity, self.called)))
        tips += [
            (tr("O que aconteceu", "What happened"), coach.runout_story(d, r, hs, opp)),
            (tr("Por que esta mão vale isso", "Why this hand is worth that"),
             coach.range_tips(d, r, self.range_pct) + coach.explain(d, r, self.n_opp)),
        ]
        self.action_btn.setText(tr("Próxima mão  ▸", "Next hand  ▸"))
        self.action_btn.setEnabled(True)
        self.action_btn.show()
        self.fold_btn.hide()
        self.call_btn.hide()
        self.action_btn.setFocus()

        self.tips_panel.show_tips(rating, tips)
        self._update_deck()
        self.roundFinished.emit(RoundResult(
            mode=self.mode, deal=d, guess=guess, eq=r, error_pp=err, rating=rating, hero_score=hs,
            opp_scores=opp, outcome=outcome, tips=tips, n_opp=self.n_opp, replay=replay, spot=self.spot,
            called=self.called, good_decision=good, range_pct=self.range_pct, hand_type=coach.hand_type(d)))

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
        hero_h = min(hero_h, (w - 300) / 2.4 * CARD_RATIO, 340)
        opp_h = min(opp_h, (w - 18 * cols) / (cols * 2) * CARD_RATIO * 0.88, board_h * 0.85)
        for c in self.hero_cards:
            c.set_card_height(int(hero_h))
        self.deck_btn.set_card_height(int(hero_h * 0.5))
        self._deck_spacer.setFixedSize(self.deck_btn.width(), 1)
        for c in self.board_cards:
            c.set_card_height(int(board_h))
        for s in self.seats:
            s.set_height(int(max(44, opp_h)))

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if self.action_btn.isEnabled():
                self._on_action()
            return
        if self.spot is not None and not self.revealed and e.key() in (Qt.Key_F, Qt.Key_C):
            self._decide(e.key() == Qt.Key_C)
            return
        super().keyPressEvent(e)
