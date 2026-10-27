"""Jogo simulado: mesa completa contra bots com personalidade.

A lógica do jogo (pokertrainer.table) anda na hora; a tela mostra o resultado por uma fila de passos animados
(fichas indo ao pote, cartas da mesa rua a rua, showdown, pote indo ao vencedor). Os bots só agem quando a fila
esvazia, então o ritmo é o de uma mesa de verdade.
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPoint, QPropertyAnimation, QEasingCurve, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from pokertrainer import ai
from pokertrainer import engine as E
from pokertrainer import profile as PF
from pokertrainer import settings as S
from pokertrainer import table as T
from pokertrainer.i18n import tr
from pokertrainer.gui import sound
from pokertrainer.gui.widgets import CARD_RATIO, CardWidget, Glass, PillLabel

START_STACK = 1000
SB, BB = 5, 10
SPEEDS = {"slow": 1200, "normal": 700, "fast": 300}
SPEED_ORDER = ["slow", "normal", "fast"]


def speed_names() -> list[tuple[str, str]]:
    return [(tr("Lenta", "Slow"), "slow"), (tr("Normal", "Normal"), "normal"), (tr("Rápida", "Fast"), "fast")]


def action_text(action: str, amount: int = 0) -> str:
    return {
        "fold": tr("desistiu", "folded"),
        "check": tr("passou", "checked"),
        "call": tr(f"pagou {amount}", f"called {amount}"),
        "bet": tr(f"apostou {amount}", f"bet {amount}"),
        "raise": tr(f"aumentou p/ {amount}", f"raised to {amount}"),
        "allin": tr(f"ALL-IN ({amount})", f"ALL-IN ({amount})"),
    }.get(action, action)


def street_name(s: str) -> str:
    return tr({"preflop": "Pré-flop", "flop": "Flop", "turn": "Turn", "river": "River"}[s],
              {"preflop": "Pre-flop", "flop": "Flop", "turn": "Turn", "river": "River"}[s])


REASONS = {"bluff": ("blefou", "bluffed"), "semibluff": ("semiblefe com projeto", "semi-bluffed with a draw"),
           "trap": ("fez slowplay (escondeu mão forte)", "slow-played (hid a strong hand)"),
           "steal": ("tentou roubar os blinds", "tried to steal the blinds")}


def _chip_color(amount: int) -> QColor:
    if amount >= 1000:
        return QColor("#2b2b2b")
    if amount >= 250:
        return QColor("#7b3fbf")
    if amount >= 100:
        return QColor("#1f8a4c")
    if amount >= 25:
        return QColor("#c0392b")
    return QColor("#2f6fc0")


# ---------------------------------------------------------------- fichas na mesa

class ChipStack(QWidget):
    """Pilha de fichas + valor (aposta na frente do jogador, ou o pote)."""

    def __init__(self, parent=None, prefix: str = "") -> None:
        super().__init__(parent)
        self.amount = 0
        self.prefix = prefix
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedSize(60, 26)
        self.hide()

    def _font(self) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(12)
        f.setBold(True)
        return f

    def set_amount(self, v: int) -> None:
        self.amount = v
        self.setVisible(v > 0)
        w = QFontMetrics(self._font()).horizontalAdvance(self._text()) + 46
        self.setFixedSize(max(60, w), 26)
        self.update()

    def _text(self) -> str:
        return f"{self.prefix}{self.amount}"

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = 1 if self.amount < 25 else 2 if self.amount < 200 else 3
        col = _chip_color(self.amount)
        for k in range(n):
            y = 15 - k * 4
            p.setPen(QPen(QColor(0, 0, 0, 120), 1))
            p.setBrush(col.darker(130))
            p.drawEllipse(QRectF(3, y - 4, 20, 10))
            p.setBrush(col)
            p.drawEllipse(QRectF(3, y - 6, 20, 10))
            p.setPen(QPen(QColor(255, 255, 255, 170), 1.2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(6, y - 4, 14, 6))
        p.setFont(self._font())
        r = QRectF(26, 3, self.width() - 28, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(8, 12, 14, 200))
        p.drawRoundedRect(r, 9, 9)
        p.setPen(QColor("#ffe7a3"))
        p.drawText(r, Qt.AlignCenter, self._text())


class Bubble(QLabel):
    """Balão de fala de um bot."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("QLabel { background: rgba(250,250,245,0.95); color: #1b1b1b; border-radius: 10px; "
                           "padding: 4px 9px; font-size: 12px; font-weight: 700; }")
        self.setWordWrap(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._token = 0
        self.hide()

    def say(self, text: str, anchor: QRectF, area_h: int, ms: int = 2600) -> None:
        self.setText(text)
        self.setFixedWidth(min(190, self.fontMetrics().horizontalAdvance(text) + 26))
        self.setFixedHeight(self.heightForWidth(self.width()))
        x = int(anchor.center().x() - self.width() / 2)
        y = int(anchor.top() - self.height() - 2)
        if y < 0:
            y = int(anchor.bottom() + 2)
        x = max(0, min(x, self.parentWidget().width() - self.width()))
        self.move(x, min(y, area_h - self.height()))
        self.show()
        self.raise_()
        self._token += 1
        tok = self._token
        # com o próprio balão como contexto: o timer é cancelado se a mesa for refeita (ex.: nova rodada)
        QTimer.singleShot(ms, self, lambda: self.hide() if tok == self._token else None)


# ---------------------------------------------------------------- assento

class PlaySeat(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("seat")
        self.compact = False
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(2)
        self.setFixedWidth(158)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.name = QLabel()
        self.badge = QLabel()
        self.badge.setStyleSheet("background: #f5c542; color: #1b1b1b; border-radius: 8px; padding: 0 5px; "
                                 "font-size: 10px; font-weight: 800;")
        top.addStretch(1)
        top.addWidget(self.name)
        top.addWidget(self.badge)
        top.addStretch(1)
        v.addLayout(top)
        h = QHBoxLayout()
        h.setSpacing(0)
        h.addStretch(1)
        self.cards = [CardWidget(), CardWidget()]
        for c in self.cards:
            h.addWidget(c)
        h.addStretch(1)
        v.addLayout(h)
        self.stack = QLabel()
        self.stack.setAlignment(Qt.AlignCenter)
        self.stack.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffe7a3; background: transparent;")
        v.addWidget(self.stack)
        self.action = PillLabel(lines=1, font_px=11)
        v.addWidget(self.action)
        self.hud = QLabel()
        self.hud.setAlignment(Qt.AlignCenter)
        self.hud.setWordWrap(False)
        self.hud.setStyleSheet("font-size: 10px; color: #9fb3ad; background: transparent;")
        v.addWidget(self.hud)
        self._style_key = None
        self.set_state()

    def set_state(self, active: bool = False, folded: bool = False, out: bool = False, winner: bool = False) -> None:
        key = (active, folded, out, winner)
        if key == self._style_key:
            return
        self._style_key = key
        if winner:
            border, bg = "rgba(61,220,132,0.9)", "rgba(61,220,132,0.14)"
        elif active:
            border, bg = "rgba(245,197,66,0.9)", "rgba(245,197,66,0.12)"
        else:
            border, bg = "rgba(255,255,255,0.08)", "rgba(0,0,0,0.10)" if out else "rgba(0,0,0,0.25)"
        self.setStyleSheet(f"QFrame#seat {{ background: {bg}; border: 1px solid {border}; border-radius: 12px; }}")
        for c in self.cards:
            c.set_dimmed(folded)
            c.setVisible(not out)
        self.name.setStyleSheet("font-weight: 700; font-size: 13px; background: transparent;"
                                + (" color: #6f817c;" if out else ""))

    def set_card_height(self, h: int) -> None:
        if self.cards[0].card_height() == max(40, int(h)) and self._sized == self.compact:
            return
        for c in self.cards:
            c.set_card_height(h)
        self.setFixedWidth(max(118 if self.compact else 140, 2 * self.cards[0].width() + 20))
        self.action.setFixedWidth(self.width() - 16)
        self.adjustSize()
        self._sized = self.compact

    _sized = None


class _Area(QWidget):
    """Área da mesa. No torneio desenha uma mesa de feltro verde atrás das cartas e dos assentos."""
    resized = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.felt = False
        self.table_rect = QRectF()

    def set_felt(self, on: bool) -> None:
        self.felt = on
        self.update()

    def set_table_rect(self, r: QRectF) -> None:
        if r != self.table_rect:
            self.table_rect = r
            self.update()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.resized.emit()

    @staticmethod
    def _stadium(r: QRectF) -> QPainterPath:
        path = QPainterPath()
        rad = min(r.width(), r.height()) / 2
        path.addRoundedRect(r, rad, rad)
        return path

    def paintEvent(self, _e) -> None:
        r = self.table_rect
        if not self.felt or r.width() < 120 or r.height() < 80:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rail = max(10.0, min(22.0, r.height() * 0.06))
        # sombra
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawPath(self._stadium(r.translated(0, 8).adjusted(-4, -2, 4, 6)))
        # borda acolchoada (couro escuro) com filete dourado
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0.0, QColor(58, 38, 26))
        g.setColorAt(0.5, QColor(34, 22, 15))
        g.setColorAt(1.0, QColor(20, 13, 9))
        p.setBrush(QBrush(g))
        p.setPen(QPen(QColor(0, 0, 0, 160), 1.5))
        p.drawPath(self._stadium(r))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(245, 197, 66, 70), 1.2))
        p.drawPath(self._stadium(r.adjusted(rail * 0.45, rail * 0.45, -rail * 0.45, -rail * 0.45)))
        # feltro verde, mais claro no centro
        felt = r.adjusted(rail, rail, -rail, -rail)
        rg = QRadialGradient(felt.center(), max(felt.width(), felt.height()) * 0.6)
        rg.setColorAt(0.0, QColor(36, 128, 76))
        rg.setColorAt(0.7, QColor(22, 96, 56))
        rg.setColorAt(1.0, QColor(12, 64, 38))
        p.setBrush(QBrush(rg))
        p.setPen(QPen(QColor(0, 0, 0, 120), 2))
        p.drawPath(self._stadium(felt))
        # linha de apostas
        inset = max(18.0, min(felt.height() * 0.13, 40.0))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 38), 1.5))
        p.drawPath(self._stadium(felt.adjusted(inset, inset, -inset, -inset)))
        # marca d'água no centro (as cartas da mesa a cobrem a partir do flop)
        f = QFont(self.font())
        f.setPixelSize(int(max(12, min(22, felt.height() * 0.06))))
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 34))
        band = QRectF(felt.left(), felt.center().y() - f.pixelSize(), felt.width(), f.pixelSize() * 2)
        p.drawText(band, Qt.AlignCenter, tr("♠  TORNEIO  ♠", "♠  TOURNAMENT  ♠"))
        p.end()


# ---------------------------------------------------------------- página

class PlayPage(QWidget):
    statsChanged = Signal(dict)
    coachMessage = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rng = random.Random()
        self.table: T.Table | None = None
        self.log_lines: list[str] = []
        self.session = self._new_session_dict()
        self.tournament = False
        self.game_over = False
        self._reasons: list[tuple[int, str, str]] = []
        self._eq_cache: tuple | None = None
        # estado da exibição (atrasado em relação à lógica enquanto as animações rodam)
        self.shown_board = 0
        self.street_base: list[int] = []
        self.hidden_win: dict[int, int] = {}
        self.tabled: set[int] = set()
        self.winner_seats: set[int] = set()
        self.thinking: int | None = None
        self._dots = 0
        self.paused = False
        self.fast = False
        self.preaction: str | None = None
        self._queue: list[tuple] = []
        self._anims: list = []
        self._pending_bot: tuple | None = None
        self._countdown = 0
        self.paid = False          # pote já entregue ao vencedor (mesa vazia)
        self._snap: dict | None = None   # contadores do jogador antes da mão (para somar aos totais)

        self.q_timer = QTimer(self)
        self.q_timer.setSingleShot(True)
        self.q_timer.timeout.connect(self._run_queue)
        self.bot_timer = QTimer(self)
        self.bot_timer.setSingleShot(True)
        self.bot_timer.timeout.connect(self._bot_apply)
        self.dots_timer = QTimer(self)
        self.dots_timer.setInterval(330)
        self.dots_timer.timeout.connect(self._tick_dots)
        self.auto_timer = QTimer(self)
        self.auto_timer.setInterval(1000)
        self.auto_timer.timeout.connect(self._tick_auto)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 10, 24, 18)
        root.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(16)

        # mesa
        self.area = _Area()
        self.area.resized.connect(self._layout_cards)
        self.area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.info = QLabel(self.area)
        self.info.setAlignment(Qt.AlignCenter)
        self.info.setObjectName("rowLabel")
        self.seats: list[PlaySeat] = []
        self.chips: list[ChipStack] = []
        self.bubbles: list[Bubble] = []
        self.pot_chip = ChipStack(self.area, prefix=tr("Pote ", "Pot "))
        self.board_cards = [CardWidget(self.area) for _ in range(5)]
        self.banner = QLabel(" ", self.area)
        self.banner.setAlignment(Qt.AlignCenter)
        self.banner.setStyleSheet("color: #9fb3ad; font-weight: 600;")
        self.hero_seat = PlaySeat(self.area)
        self.hero_seat.hud.setWordWrap(True)
        self.hand_name = QLabel(" ", self.area)
        self.hand_name.setObjectName("handName")
        self.hand_name.setAlignment(Qt.AlignCenter)
        self.floater = QLabel(self.area)
        self.floater.setStyleSheet("color: #3ddc84; font-size: 22px; font-weight: 900; background: transparent;")
        self.floater.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.floater.hide()
        self._chip_pos: dict[int, QPoint] = {}
        self._pot_pos = QPoint(0, 0)
        row.addWidget(self.area, 1)

        # histórico
        self.log_panel = Glass(alpha=185)
        self.log_panel.setFixedWidth(290)
        lv = QVBoxLayout(self.log_panel)
        lv.setContentsMargins(16, 12, 8, 12)
        title = QLabel(tr("📜  Histórico", "📜  History"))
        title.setStyleSheet("font-size: 16px; font-weight: 800; color: #f5c542;")
        lv.addWidget(title)
        self.log = QLabel()
        self.log.setWordWrap(True)
        self.log.setTextFormat(Qt.RichText)
        self.log.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.log.setStyleSheet("font-size: 12px;")
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 8, 0)
        il.addWidget(self.log)
        il.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(inner)
        lv.addWidget(self.scroll, 1)
        row.addWidget(self.log_panel)
        root.addLayout(row, 1)

        # painel de ações
        self.panel = Glass(alpha=165)
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(20, 10, 20, 12)
        pv.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        txt = QVBoxLayout()
        txt.setSpacing(0)
        self.prompt = QLabel()
        self.prompt.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.prompt.setWordWrap(True)
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        txt.addWidget(self.prompt)
        txt.addWidget(self.hint)
        head.addLayout(txt, 1)
        self.pause_btn = self._chip(tr("⏸ Pausar", "⏸ Pause"), self.toggle_pause,
                                    tr("Pausar / continuar (P)", "Pause / resume (P)"))
        self.speed_btn = self._chip("", self.cycle_speed, tr("Velocidade dos bots", "Bot speed"))
        self.skip_btn = self._chip(tr("⏭ Pular mão", "⏭ Skip hand"), self.skip_hand,
                                   tr("Termina a mão na hora (você já saiu dela)", "Finish the hand now (you're out)"))
        self.auto_btn = self._chip(tr("🔁 Auto", "🔁 Auto"), self._toggle_auto,
                                   tr("Próxima mão automática", "Automatic next hand"), checkable=True)
        self.auto_btn.setChecked(S.get("play_autonext"))
        self.players_btn = self._chip("", lambda: None, tr("Oponentes na mesa (começa uma nova partida)",
                                                             "Opponents at the table (starts a new game)"))
        pmenu = QMenu(self.players_btn)
        for n in range(1, S.MAX_OPPONENTS + 1):
            a = pmenu.addAction(tr(f"{n} oponente{'s' if n > 1 else ''}", f"{n} opponent{'s' if n > 1 else ''}"))
            a.triggered.connect(lambda _=False, k=n: self.set_players(k))
        self.players_btn.setMenu(pmenu)
        self._update_players_btn()
        self.sound_btn = self._chip("", self.toggle_sound, tr("Sons ligados/desligados", "Sounds on/off"))
        self._update_sound_btn()
        for b in (self.players_btn, self.pause_btn, self.speed_btn, self.skip_btn, self.auto_btn, self.sound_btn):
            head.addWidget(b, 0, Qt.AlignTop)
        pv.addLayout(head)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.fold_btn = QPushButton(tr("Desistir (F)", "Fold (F)"))
        self.fold_btn.setObjectName("fold")
        self.call_btn = QPushButton()
        self.call_btn.setObjectName("primary")
        self.raise_btn = QPushButton()
        self.raise_btn.setObjectName("primary")
        self.next_btn = QPushButton(tr("Próxima mão  ▸", "Next hand  ▸"))
        self.next_btn.setObjectName("primary")
        for b in (self.fold_btn, self.call_btn, self.raise_btn, self.next_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumWidth(130)
            b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        for b in (self.call_btn, self.raise_btn):
            b.setMinimumWidth(190)
        self.fold_btn.clicked.connect(lambda: self.hero_act("fold"))
        self.call_btn.clicked.connect(lambda: self.hero_act("call"))
        self.raise_btn.clicked.connect(lambda: self.hero_act("raise"))
        self.next_btn.clicked.connect(self._next_clicked)
        btns.addWidget(self.fold_btn)
        btns.addWidget(self.call_btn)
        btns.addSpacing(10)
        size_box = QVBoxLayout()
        size_box.setContentsMargins(0, 0, 0, 0)
        size_box.setSpacing(4)
        quick = QHBoxLayout()
        quick.setSpacing(4)
        self.quick_btns = []
        for label, frac in (("⅓", 0.33), (tr("½ pote", "½ pot"), 0.5), (tr("¾ pote", "¾ pot"), 0.75),
                            (tr("Pote", "Pot"), 1.0), ("All-in", -1)):
            b = self._chip(label, lambda _=False, f=frac: self._quick(f), "")
            b.setStyleSheet("padding: 3px 6px;")
            quick.addWidget(b)
            self.quick_btns.append(b)
        size_box.addLayout(quick)
        srow = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimumWidth(160)
        self.amount = QSpinBox()
        self.amount.setSingleStep(5)
        self.slider.valueChanged.connect(self._slider_moved)
        self.amount.valueChanged.connect(self._amount_changed)
        srow.addWidget(self.slider, 1)
        srow.addWidget(self.amount)
        size_box.addLayout(srow)
        self.size_widget = QWidget()
        self.size_widget.setLayout(size_box)
        btns.addWidget(self.size_widget, 1)
        btns.addWidget(self.raise_btn)
        btns.addWidget(self.next_btn)
        # pré-ações (enquanto os outros jogam)
        self.pre_box = QWidget()
        pl = QHBoxLayout(self.pre_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(6)
        lbl = QLabel(tr("Pré-ação:", "Pre-action:"))
        lbl.setObjectName("muted")
        pl.addWidget(lbl)
        self.pre_group = QButtonGroup(self)
        self.pre_group.setExclusive(False)
        self.pre_btns: dict[str, QPushButton] = {}
        for key, label in (("checkfold", tr("Passar/Desistir", "Check/Fold")), ("check", tr("Passar", "Check")),
                           ("callany", tr("Pagar qualquer", "Call any"))):
            b = self._chip(label, lambda _=False, k=key: self._set_preaction(k), "", checkable=True)
            self.pre_group.addButton(b)
            self.pre_btns[key] = b
            pl.addWidget(b)
        pl.addStretch(1)
        btns.addWidget(self.pre_box, 1)
        pv.addLayout(btns)
        root.addWidget(self.panel)
        # altura fixa: a mesa não muda de tamanho quando os botões aparecem/somem
        self.panel.setFixedHeight(132)
        self._update_speed_btn()
        self._set_mode("wait")

    def _chip(self, text: str, slot, tip: str, checkable: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("chip")
        b.setCursor(Qt.PointingHandCursor)
        b.setCheckable(checkable)
        if tip:
            b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    @staticmethod
    def _new_session_dict() -> dict:
        return {"hands": 0, "won": 0, "good": 0, "decisions": 0, "rebuys": 0, "biggest": 0}

    # ------------------------------------------------------------ sessão
    def new_session(self, tournament: bool | None = None) -> None:
        """Nova partida: cash game ou torneio (None = o mesmo tipo da partida anterior)."""
        self.stop()
        if tournament is not None:
            self.tournament = tournament
        diff = S.get("difficulty")
        self._update_players_btn()
        hero = T.Player(name=tr("Você", "You"), stack=START_STACK, is_hero=True, avatar="⭐")
        self.session = self._new_session_dict()
        self.session["diff"] = diff
        self.area.set_felt(self.tournament)
        self.game_over = False
        self.paused = False
        self.pause_btn.setText(tr("⏸ Pausar", "⏸ Pause"))
        self.log_lines = []
        S.add_play_totals({"sessions": 1, "tournaments": int(self.tournament)})
        if self.tournament:
            n = ai.tournament_rounds(diff)
            self.session.update(round=0, rounds=n, round_hands=0, round_done=False, field=0)
            self._log(tr(f"<b>Novo torneio</b> — {n} rodadas, dificuldade {ai.difficulty_name(diff)}.",
                         f"<b>New tournament</b> — {n} rounds, {ai.difficulty_name(diff)} difficulty."))
            self._start_round(hero)
            return
        self._seat_table(hero)
        self._log(tr(f"<b>Nova partida</b> (cash game) — dificuldade {ai.difficulty_name(diff)}, {START_STACK} "
                     f"fichas cada.", f"<b>New game</b> (cash game) — {ai.difficulty_name(diff)} difficulty, "
                     f"{START_STACK} chips each."))
        self.next_hand()

    def _seat_table(self, hero: T.Player) -> None:
        """Mesa nova com o jogador e bots novos, todos com o stack inicial."""
        n_opp = max(1, min(S.MAX_OPPONENTS, S.get("play_opponents")))
        hero.stack, hero.sitting_out = START_STACK, False
        taken: set[str] = set()
        bots = []
        for _ in range(n_opp):
            b = ai.new_bot_player(self.session.get("diff", S.get("difficulty")), START_STACK, self.rng, taken)
            taken.add(b.name)
            bots.append(b)
        self.table = T.Table([hero] + bots, SB, BB, self.rng)
        self._build_seats()

    @property
    def final_table(self) -> bool:
        return self.tournament and self.session.get("round") == self.session.get("rounds")

    def _start_round(self, hero: T.Player | None = None) -> None:
        """Próxima rodada do torneio: mesa nova, stacks e blinds do começo."""
        self.stop()
        ss = self.session
        ss["round"] += 1
        ss["round_hands"] = 0
        ss["round_done"] = False
        self._seat_table(hero or self.hero)
        n = len(self.table.players)
        if not ss["field"]:
            ss["field"] = n * 2 ** (ss["rounds"] - 1)   # jogadores no torneio (metade passa a cada rodada)
        if self.final_table:
            self._log(tr(f"<hr>🏆 <b>Mesa final</b> (rodada {ss['round']} de {ss['rounds']}) — {n} jogadores, "
                         f"{START_STACK} fichas cada. Só o campeão sai daqui.",
                         f"<hr>🏆 <b>Final table</b> (round {ss['round']} of {ss['rounds']}) — {n} players, "
                         f"{START_STACK} chips each. Only the champion leaves."))
        else:
            q = ai.round_qualifiers(n, False)
            self._log(tr(f"<hr>🎟 <b>Rodada {ss['round']} de {ss['rounds']}</b> — mesa nova, {START_STACK} fichas "
                         f"cada. Passam {q} de {n} jogadores.",
                         f"<hr>🎟 <b>Round {ss['round']} of {ss['rounds']}</b> — new table, {START_STACK} chips each. "
                         f"{q} of {n} players advance."))
        self.next_hand()

    def export_state(self) -> dict:
        return {"table": self.table, "log": self.log_lines, "session": self.session, "tournament": self.tournament,
                "game_over": self.game_over, "snap": self._snap}

    def adopt(self, st: dict) -> None:
        """Continua uma partida existente (ex.: depois de trocar o idioma)."""
        self.table, self.log_lines, self.session = st["table"], st["log"], st["session"]
        self.tournament, self.game_over = st["tournament"], st["game_over"]
        self.area.set_felt(self.tournament)
        self._snap = st.get("snap")
        t = self.table
        t.players[0].name = tr("Você", "You")
        t.events = []
        self._build_seats()
        self.shown_board = len(t.board)
        self.street_base = [p.total - p.bet for p in t.players]
        self.hidden_win = {}
        self.tabled = set(t.showdown_hands)
        for i, c in enumerate(self.hero_seat.cards):
            c.set_card(self.hero.hole[i] if self.hero.hole else None, bool(self.hero.hole))
        for k, seat in enumerate(self.seats):
            p = t.players[k + 1]
            for j, c in enumerate(seat.cards):
                c.set_card(p.hole[j] if p.hole else None, (k + 1) in self.tabled)
        for i, c in enumerate(self.board_cards):
            if i < len(t.board):
                c.set_card(t.board[i], True)
                c.show()
            else:
                c.hide()
        self._render_log()
        if t.hand_over:
            self.paid = True
            self.winner_seats = set(t.winners)
            self._hand_end_ui(replay=True)
        else:
            self._refresh()
            self._schedule()

    def stop(self) -> None:
        for tm in (self.q_timer, self.bot_timer, self.dots_timer, self.auto_timer):
            tm.stop()
        self._queue = []
        self._pending_bot = None
        self.thinking = None
        for a in self._anims:
            a.stop()
        self._anims = []

    @property
    def hero(self) -> T.Player:
        return self.table.players[0]

    def _seat_widget(self, i: int) -> PlaySeat:
        return self.hero_seat if i == 0 else self.seats[i - 1]

    def _build_seats(self) -> None:
        for wlist in (self.seats, self.chips, self.bubbles):
            for s in wlist:
                s.setParent(None)
                s.deleteLater()
        n = len(self.table.players) - 1
        self.seats = [PlaySeat(self.area) for _ in range(n)]
        for s in self.seats:
            s.compact = n >= 7
            s.show()
        self.chips = [ChipStack(self.area) for _ in range(n + 1)]
        self.bubbles = [Bubble(self.area) for _ in range(n + 1)]
        self._layout_cards()

    # ------------------------------------------------------------ fluxo da mão
    def _next_clicked(self) -> None:
        self.auto_timer.stop()
        if self.game_over:
            self.new_session()
        elif self.tournament and self.session.get("round_done"):
            self._start_round()
        else:
            self.next_hand()

    def next_hand(self) -> None:
        t = self.table
        if t is None or self.game_over or (self.tournament and self.session.get("round_done")):
            return
        self.stop()
        self.fast = False
        self.preaction = None
        for b in self.pre_btns.values():
            b.setChecked(False)
        if not self.tournament:
            if self.hero.stack <= 0:
                self.hero.stack = START_STACK
                self.hero.sitting_out = False
                self.session["rebuys"] += 1
                self._log(tr(f"Você recomprou {START_STACK} fichas.", f"You rebought {START_STACK} chips."))
            taken = {p.name for p in t.players}
            for i, p in enumerate(t.players):
                if i and p.stack <= 0:
                    nb = ai.new_bot_player(self.session.get("diff", S.get("difficulty")), START_STACK, self.rng,
                                           taken)
                    taken.add(nb.name)
                    t.players[i] = nb
                    self._log(tr(f"{p.avatar} {p.name} quebrou e saiu; {nb.avatar} <b>{nb.name}</b> sentou-se.",
                                 f"{p.avatar} {p.name} went broke and left; {nb.avatar} <b>{nb.name}</b> sat down."))
        else:
            sb, bb, _left = ai.blinds_for(self.session["round_hands"])
            if (sb, bb) != (t.sb, t.bb):
                self._log(tr(f"⏫ <b>Blinds sobem para {sb}/{bb}</b>", f"⏫ <b>Blinds go up to {sb}/{bb}</b>"))
            t.sb, t.bb = sb, bb
        self._reasons = []
        self._eq_cache = None
        self._snap = PF.counters_of(self.hero)
        self._snap["decisions"] = self.session["decisions"]
        self._snap["good_decisions"] = self.session["good"]
        t.start_hand()
        self.session["hands"] += 1
        if self.tournament:
            self.session["round_hands"] += 1
        self._log(f"<hr><b>{tr('Mão', 'Hand')} #{t.hand_no}</b> — {tr('botão', 'button')}: "
                  f"{t.players[t.dealer].name}")
        self.shown_board = 0
        self.street_base = [0] * len(t.players)
        self.hidden_win = {}
        self.paid = False
        self.tabled = set()
        self.winner_seats = set()
        anim = S.get("animations")
        for i, c in enumerate(self.hero_seat.cards):
            c.set_card(self.hero.hole[i] if self.hero.hole else None, bool(self.hero.hole), animate=anim,
                       delay_ms=80 + 120 * i)
        for k, seat in enumerate(self.seats):
            p = t.players[k + 1]
            for j, c in enumerate(seat.cards):
                c.set_card(p.hole[j] if p.hole else None, False)
        for c in self.board_cards:
            c.set_card(None, False)
            c.hide()
        self.banner.setText(" ")
        self.floater.hide()
        sound.play("deal")
        self._log_events(t.events)
        t.events = []
        self._refresh()
        self._emit_stats()
        self._schedule()

    def _speed(self) -> int:
        d = SPEEDS.get(S.get("play_speed"), 700)
        if not self.hero.in_hand:
            d = int(d * 0.55)
        return d

    def _schedule(self) -> None:
        """Decide o próximo passo quando a fila de animações está vazia."""
        t = self.table
        if t is None or self.paused or self._queue or self.game_over or t.hand_over:
            return
        if self._pending_bot is not None:
            return
        if t.to_act == 0:
            if self._apply_preaction():
                return
            self._hero_turn()
            return
        self._bot_turn()

    def _bot_turn(self) -> None:
        t = self.table
        seat = t.to_act
        if seat is None:
            return
        p = t.players[seat]
        d = p.ai.decide(t, seat)
        lg = t.legal(seat)
        self._pending_bot = (seat, d)
        self.thinking = seat
        self._set_mode("wait")
        self._refresh()
        if self.fast:
            self._bot_apply()
            return
        self.dots_timer.start()
        self._tick_dots()
        self.bot_timer.start(ai.think_ms(d, lg.to_call, t.pot, p.ai.p, self._speed(), self.rng))

    def _bot_apply(self) -> None:
        self.dots_timer.stop()
        if self._pending_bot is None or self.paused:
            return
        seat, d = self._pending_bot
        self._pending_bot = None
        self.thinking = None
        t = self.table
        if t.to_act != seat or t.hand_over:
            self._schedule()
            return
        if d.reason in REASONS:
            self._reasons.append((seat, t.street, d.reason))
        lg = t.legal(seat)
        t.act(d.action, d.amount_to)
        self._after_act(seat, d, lg)

    def _tick_dots(self) -> None:
        self._dots = (self._dots + 1) % 4
        if self.thinking is not None and self.thinking > 0:
            self.seats[self.thinking - 1].action.setText(tr("pensando", "thinking") + "." * self._dots)

    # ------------------------------------------------------------ jogador
    def _apply_preaction(self) -> bool:
        pa = self.preaction
        if not pa:
            return False
        lg = self.table.legal(0)
        self._clear_preaction()
        if pa == "checkfold":
            self.hero_act("check" if lg.can_check else "fold")
            return True
        if pa == "check" and lg.can_check:
            self.hero_act("check")
            return True
        if pa == "callany":
            self.hero_act("call")
            return True
        return False   # "passar" com aposta na frente: a decisão volta para o jogador

    def _clear_preaction(self) -> None:
        self.preaction = None
        for b in self.pre_btns.values():
            b.setChecked(False)

    def _set_preaction(self, key: str) -> None:
        on = self.pre_btns[key].isChecked()
        for k, b in self.pre_btns.items():
            if k != key:
                b.setChecked(False)
        self.preaction = key if on else None

    def _hero_turn(self) -> None:
        t = self.table
        lg = t.legal(0)
        self._set_mode("act")
        sound.play("turn")
        pot = t.pot
        need = 0.0
        if lg.can_check:
            self.call_btn.setText(tr("Passar (C)", "Check (C)"))
            self.prompt.setText(tr("Sua vez: passar ou apostar?", "Your turn: check or bet?"))
        else:
            allin = lg.to_call >= self.hero.stack
            self.call_btn.setText(tr(f"Pagar ALL-IN {lg.to_call}", f"Call ALL-IN {lg.to_call}") if allin
                                  else tr(f"Pagar {lg.to_call} (C)", f"Call {lg.to_call} (C)"))
            need = lg.to_call / (pot + lg.to_call)
            self.prompt.setText(tr(f"Sua vez: pagar {lg.to_call} para um pote de {pot + lg.to_call}?",
                                   f"Your turn: call {lg.to_call} into a pot of {pot + lg.to_call}?"))
        hint = [tr(f"Posição: {t.position_of(0)}.", f"Position: {t.position_of(0)}.")]
        if not lg.can_check:
            hint.append(tr(f"Pot odds: precisa vencer {need:.0%} das vezes para pagar.",
                           f"Pot odds: you need to win {need:.0%} of the time to call."))
        if S.get("play_assist"):
            eq = self._hero_equity()
            hint.append(tr(f"Assistente: sua chance ~{eq:.0%} contra mãos aleatórias.",
                           f"Assistant: your chance ~{eq:.0%} vs random hands."))
        self.hint.setText("  ".join(hint))
        self.fold_btn.setEnabled(not lg.can_check)
        can_raise = lg.can_raise
        for w in (self.raise_btn, self.slider, self.amount, *self.quick_btns):
            w.setEnabled(can_raise)
        if can_raise:
            for w in (self.slider, self.amount):
                w.blockSignals(True)
                w.setRange(lg.min_raise_to, lg.max_raise_to)
                w.blockSignals(False)
            self.slider.setSingleStep(5)
            default = max(lg.min_raise_to, min(lg.max_raise_to, self._pot_size(0.66)))
            self.amount.setValue(default)
            self.slider.setValue(default)
            self._update_raise_text()
        else:
            self.raise_btn.setText(tr("Aumentar", "Raise"))
        self.call_btn.setFocus()

    def _pot_size(self, frac: float) -> int:
        t = self.table
        lg = t.legal(0)
        if frac < 0:
            return lg.max_raise_to
        amt = t.current_bet + frac * (t.pot + lg.to_call) if t.current_bet else frac * t.pot
        return int(round(amt / 5) * 5)

    def _quick(self, frac: float) -> None:
        lg = self.table.legal(0)
        self.amount.setValue(max(lg.min_raise_to, min(lg.max_raise_to, self._pot_size(frac))))

    def _slider_moved(self, v: int) -> None:
        self.amount.blockSignals(True)
        self.amount.setValue(v)
        self.amount.blockSignals(False)
        self._update_raise_text()

    def _amount_changed(self, v: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self._update_raise_text()

    def _update_raise_text(self) -> None:
        t = self.table
        if t is None or t.to_act != 0 or t.hand_over:
            return
        v = self.amount.value()
        if v >= t.legal(0).max_raise_to:
            self.raise_btn.setText(f"ALL-IN {v} (R)")
        elif t.current_bet == 0:
            self.raise_btn.setText(tr(f"Apostar {v} (R)", f"Bet {v} (R)"))
        else:
            self.raise_btn.setText(tr(f"Aumentar p/ {v} (R)", f"Raise to {v} (R)"))

    def _hero_equity(self) -> float:
        t = self.table
        n_opp = max(1, len(t.seats_in_hand()) - 1)
        key = (t.hand_no, len(t.board), n_opp)
        if self._eq_cache is None or self._eq_cache[0] != key:
            self._eq_cache = (key, E.equity(self.hero.hole, t.board, n_opp, 4000, self.rng).equity)
        return self._eq_cache[1]

    def hero_act(self, kind: str) -> None:
        t = self.table
        if t is None or t.hand_over or t.to_act != 0 or self._queue:
            return
        lg = t.legal(0)
        if kind == "fold" and lg.can_check:
            kind = "check"
        if kind == "call":
            kind = "check" if lg.can_check else "call"
        self._coach(kind, lg)
        if kind == "raise":
            amt = self.amount.value()
            t.act("allin" if amt >= lg.max_raise_to else "raise", amt)
        else:
            t.act(kind)
        self._after_act(0, None, lg)

    def _coach(self, kind: str, lg: T.Legal) -> None:
        """Comenta a decisão do jogador quando ele enfrenta uma aposta (pot odds × chance)."""
        if lg.can_check or kind == "raise":
            return
        t = self.table
        eq = self._hero_equity()
        need = lg.to_call / (t.pot + lg.to_call)
        self.session["decisions"] += 1
        if kind == "call" and eq < need - 0.06:
            msg = tr(f"Você pagou precisando de {need:.0%} com ~{eq:.0%} de chance: caro demais (e quem aposta "
                     f"costuma ter mão melhor).",
                     f"You called needing {need:.0%} with ~{eq:.0%} chance: too expensive (and bettors usually "
                     f"have better).")
            ok = False
        elif kind == "fold" and eq > need + 0.14:
            msg = tr(f"Você desistiu com ~{eq:.0%} de chance precisando só de {need:.0%}: pagar seria lucrativo "
                     f"contra a maioria das mãos.",
                     f"You folded with ~{eq:.0%} chance needing only {need:.0%}: calling would be profitable "
                     f"against most hands.")
            ok = False
        else:
            act = tr("pagar", "calling") if kind == "call" else tr("desistir", "folding")
            msg = tr(f"Boa: {act} faz sentido — precisava de {need:.0%}, sua chance ~{eq:.0%}.",
                     f"Good: {act} makes sense — you needed {need:.0%}, your chance ~{eq:.0%}.")
            ok = True
        self.session["good"] += ok
        color = "#3ddc84" if ok else "#ff8a80"
        self._log(f"<span style='color:{color}'>🎓 {msg}</span>")
        self.coachMessage.emit(f"<span style='color:{color}'>{msg}</span>")

    # ------------------------------------------------------------ depois de cada ação: monta a fila de animações
    def _after_act(self, seat: int, d, lg: T.Legal) -> None:
        t = self.table
        evs, t.events = t.events, []
        if not self.fast:
            la = t.players[seat].last_action
            sound.play({"fold": "fold", "check": "check", "call": "call", "bet": "bet", "raise": "bet",
                        "allin": "allin"}.get(la, "chip"))
        self._log_events([e for e in evs if e.kind in ("action", "blind")])
        p = t.players[seat]
        if p.ai is not None and d is not None:
            kind = {"allin": "allin", "raise": "raise", "bet": "raise", "call": "call", "fold": "fold"}.get(
                p.last_action)
            if kind == "fold" and lg.to_call < t.bb * 3:
                kind = None
            if kind:
                line = ai.chat(kind, p.ai.p, self.rng)
                if line:
                    self._say(seat, line)
        streets = [e for e in evs if e.kind == "street"]
        if streets or t.hand_over:
            self._enqueue(self._collect_chips, 450)
        if streets:
            runout = t.to_act is None   # ninguém mais pode apostar: mostra as mãos e corre as cartas
            if runout and len(t.seats_in_hand()) > 1:
                self._enqueue(self._table_hands, 900)
            for ev in streets:
                n = len(ev.data["board"])
                self._enqueue(lambda n=n, s=ev.text: self._reveal_board(n, s), 1300 if runout else 650)
        if t.hand_over:
            wins = [e for e in evs if e.kind == "win"]
            self.hidden_win = dict(t.winners)   # o stack só sobe quando as fichas chegam
            if t.showdown_hands:
                if len(t.board) > self.shown_board and not streets:
                    self._enqueue(lambda: self._reveal_board(5, "river"), 1200)
                self._enqueue(self._showdown_step, 1200)
            self._enqueue(lambda w=wins: self._payout_step(w), 1000)
            self._enqueue(self._hand_end_ui, 0)
        self._set_mode("wait")
        self._refresh()
        self._run_queue()

    def _enqueue(self, fn, delay: int) -> None:
        self._queue.append((fn, delay))

    def _run_queue(self) -> None:
        if self.paused:
            return
        if not self._queue:
            self._schedule()
            return
        fn, delay = self._queue.pop(0)
        fn()
        if self.fast:
            delay = 0
        elif not S.get("animations"):
            delay = min(delay, 150)
        self.q_timer.start(delay)

    # ------------------------------------------------------------ passos animados
    def _animate(self, w: QWidget, end: QPoint, ms: int, done=None) -> None:
        if self.fast or not S.get("animations"):
            w.move(end)
            if done:
                done()
            return
        a = QPropertyAnimation(w, b"pos", self)
        a.setDuration(ms)
        a.setStartValue(w.pos())
        a.setEndValue(end)
        a.setEasingCurve(QEasingCurve.InOutCubic)
        if done:
            a.finished.connect(done)
        a.finished.connect(lambda: self._anims.remove(a) if a in self._anims else None)
        self._anims.append(a)
        a.start()

    def _fly(self, amount: int, start: QPoint, end: QPoint, ms: int) -> None:
        fly = ChipStack(self.area)
        fly.set_amount(amount)
        fly.move(start)
        fly.show()
        fly.raise_()
        self._animate(fly, end, ms, fly.deleteLater)

    def _collect_chips(self) -> None:
        """As apostas da rua vão para o pote."""
        t = self.table
        if any(p.total - self.street_base[i] > 0 for i, p in enumerate(t.players)) and not self.fast:
            sound.play("collect")
        for i, p in enumerate(t.players):
            amt = p.total - self.street_base[i]
            if amt > 0:
                self.chips[i].hide()
                self._fly(amt, self._chip_pos.get(i, self._pot_pos), self._pot_pos, 380)
        self.street_base = [p.total for p in t.players]
        self._refresh()

    def _table_hands(self) -> None:
        """All-in sem mais apostas: todos mostram as cartas antes de correr a mesa."""
        t = self.table
        anim = S.get("animations") and not self.fast
        for i in t.seats_in_hand():
            if i == 0 or i in self.tabled:
                continue
            self.tabled.add(i)
            for k, c in enumerate(self.seats[i - 1].cards):
                c.flip_up(80 * k, animate=anim)
        self._log(tr("🃏 All-in: as cartas são mostradas.", "🃏 All-in: cards are tabled."))
        self.banner.setText(tr("<span style='color:#ffe7a3; font-weight:800'>ALL-IN! Correndo as cartas…</span>",
                               "<span style='color:#ffe7a3; font-weight:800'>ALL-IN! Running the board…</span>"))

    def _reveal_board(self, n: int, street: str) -> None:
        t = self.table
        anim = S.get("animations") and not self.fast
        start = self.shown_board
        end = min(n, len(t.board))
        if end <= start:
            return
        for i in range(start, end):
            c = self.board_cards[i]
            c.set_card(t.board[i], True, animate=anim, delay_ms=110 * (i - start))
            c.show()
        if not self.fast:
            sound.play("flip")
        self.shown_board = end
        cards = " ".join(E.card_pretty(c) for c in t.board[:end])
        self._log(f"<span style='color:#f5c542'><b>{street_name(street)}</b></span>  {cards}  "
                  f"<span style='color:#9fb3ad'>({tr('pote', 'pot')} {sum(self.street_base)})</span>")
        self._clear_preaction()
        self._refresh()

    def _showdown_step(self) -> None:
        t = self.table
        anim = S.get("animations") and not self.fast
        delay = 0
        for i in t.showdown_hands:
            if i == 0 or i in self.tabled:
                continue
            self.tabled.add(i)
            for c in self.seats[i - 1].cards:
                c.flip_up(delay, animate=anim)
                delay += 90
        if not self.fast:
            sound.play("flip")
        best = max(t.showdown_hands.values())
        winners = [i for i, s in t.showdown_hands.items() if s == best]
        five = set(E.best_five(t.players[winners[0]].hole + t.board))
        for i, c in enumerate(self.board_cards):
            if i < len(t.board):
                c.set_highlight(t.board[i] in five)
                c.set_dimmed(t.board[i] not in five)
        for i, sc in t.showdown_hands.items():
            sw = self._seat_widget(i)
            for c, card in zip(sw.cards, t.players[i].hole):
                c.set_highlight(i in winners and card in five)
                c.set_dimmed(i not in winners)
            if i:
                sw.action.setText(E.category_name(sc >> 20))
                sw.action.setToolTip(E.describe(sc))
        names = " & ".join(t.players[i].name for i in winners)
        self.banner.setText(f"<span style='color:#3ddc84; font-size:15px; font-weight:800'>🏆 {names} — "
                            f"{E.describe(best)}</span>")
        if 0 in t.showdown_hands:
            self.hand_name.setText(E.describe(t.showdown_hands[0]))

    def _payout_step(self, wins) -> None:
        t = self.table
        for ev in wins:
            p = t.players[ev.seat]
            how = f" — {ev.text}" if ev.text else ""
            self._log(f"🏆 <b>{p.name}</b> {tr('ganhou', 'won')} {ev.amount}{how}")
            self._fly(ev.amount, self._pot_pos, self._chip_pos.get(ev.seat, self._pot_pos), 650)
        self.winner_seats = {ev.seat for ev in wins}
        self.hidden_win = {}
        if not self.fast:
            sound.play("win" if 0 in self.winner_seats else "collect")
        if wins and not t.showdown_hands:
            w = t.players[wins[0].seat]
            self.banner.setText(f"<span style='color:#3ddc84; font-size:15px; font-weight:800'>🏆 {w.name} "
                                f"{tr('leva o pote', 'takes the pot')}</span>")
        self.paid = True
        if wins:
            top = max(wins, key=lambda e: e.amount)
            self._float(top.seat, f"+{top.amount}")
        self._refresh(final=True)

    def _float(self, seat: int, text: str) -> None:
        sw = self._seat_widget(seat)
        self.floater.setText(text)
        self.floater.adjustSize()
        start = QPoint(sw.x() + sw.width() // 2 - self.floater.width() // 2, sw.y() + sw.height() // 3)
        self.floater.move(start)
        self.floater.show()
        self.floater.raise_()
        if self.fast or not S.get("animations"):
            QTimer.singleShot(900, self.floater.hide)
            return
        eff = QGraphicsOpacityEffect(self.floater)
        self.floater.setGraphicsEffect(eff)
        a = QPropertyAnimation(self.floater, b"pos", self)
        a.setDuration(1400)
        a.setStartValue(start)
        a.setEndValue(start - QPoint(0, 46))
        b = QPropertyAnimation(eff, b"opacity", self)
        b.setDuration(1400)
        b.setStartValue(1.0)
        b.setKeyValueAt(0.6, 1.0)
        b.setEndValue(0.0)
        b.finished.connect(self.floater.hide)
        for x in (a, b):
            self._anims.append(x)
            x.start()

    def _hand_end_ui(self, replay: bool = False) -> None:
        t = self.table
        won = t.winners.get(0, 0)
        net = won - self.hero.total
        if not replay:
            self.session["won"] += won > 0
            self.session["biggest"] = max(self.session["biggest"], net)
            self._record_hand(won, net)
            self._update_moods()
            if S.get("show_personality") and self._reasons:
                for seat, street, reason in self._reasons:
                    p = t.players[seat]
                    self._log(f"<span style='color:#9fb3ad'>🔍 {p.name} {tr(*REASONS[reason])} "
                              f"({street_name(street).lower()})</span>")
        self._set_mode("end")
        if won:
            self.prompt.setText(tr(f"Você ganhou {won} fichas (+{net}).", f"You won {won} chips (+{net})."))
        elif self.hero.total:
            self.prompt.setText(tr(f"Você perdeu {self.hero.total} fichas nesta mão.",
                                   f"You lost {self.hero.total} chips this hand."))
        else:
            self.prompt.setText(tr("Mão encerrada.", "Hand over."))
        busted = self.hero.stack <= 0
        alive = [p for p in t.players[1:] if p.stack > 0]
        ss = self.session
        qualify = ai.round_qualifiers(len(t.players), self.final_table) if self.tournament else 0
        if self.tournament and (busted or 1 + len(alive) <= qualify):
            self._tournament_step(busted, len(alive), replay)
        elif busted:
            self.hint.setText(tr("Você quebrou! Clique para recomprar e continuar.", "You're broke! Click to rebuy."))
            self.next_btn.setText(tr(f"Recomprar {START_STACK}  ▸", f"Rebuy {START_STACK}  ▸"))
        else:
            extra = ""
            if self.tournament:
                _sb, _bb, left = ai.blinds_for(ss["round_hands"] - 1)
                extra = tr(f"  Blinds sobem em {left} mão(s).", f"  Blinds go up in {left} hand(s).") if left else ""
                need = 1 + len(alive) - qualify
                if not self.final_table and need > 0:
                    extra += tr(f"  Falta{'m' if need > 1 else ''} {need} eliminaç{'ões' if need > 1 else 'ão'} "
                                f"para passar de rodada.",
                                f"  {need} more knockout{'s' if need > 1 else ''} to advance.")
            self.hint.setText(tr("Enter para a próxima mão.", "Press Enter for the next hand.") + extra)
            self.next_btn.setText(tr("Próxima mão  ▸", "Next hand  ▸"))
            if self.auto_btn.isChecked() and not replay and not self.paused:
                self._countdown = 4
                self._tick_auto()
                self.auto_timer.start()
        self._refresh(final=True)
        self._emit_stats()

    def _tournament_step(self, busted: bool, others_alive: int, replay: bool) -> None:
        """Fim de rodada no torneio: eliminado, passou de rodada ou campeão."""
        ss = self.session
        r, n = ss["round"], ss["rounds"]
        if busted:
            self.game_over = True
            table_place = others_alive + 1
            tables = 2 ** (n - r)                          # mesas desta rodada no torneio
            place = (table_place - 1) * tables + 1         # colocação geral aproximada
            msg = tr(f"Você foi eliminado na rodada {r} de {n} — {place}º lugar de {ss['field']}.",
                     f"You were knocked out in round {r} of {n} — place #{place} of {ss['field']}.")
            if r == n:
                msg = tr(f"Você foi eliminado na mesa final em {place}º lugar.",
                         f"You were knocked out at the final table in place #{place}.")
        elif r == n:
            self.game_over = True
            place = 1
            msg = tr(f"🏆 Você é o campeão do torneio! ({ss['field']} jogadores)",
                     f"🏆 You are the tournament champion! ({ss['field']} players)")
        else:
            place = 0
            ss["round_done"] = True
            msg = (tr("✅ Você chegou à mesa final!", "✅ You made the final table!") if r + 1 == n else
                   tr(f"✅ Você passou para a rodada {r + 1} de {n}!", f"✅ You advanced to round {r + 1} of {n}!"))
        self.prompt.setText(msg)
        if not replay:
            self._log(f"<b>{msg}</b>")
            if place:
                S.add_play_totals({"tourn_wins": int(place == 1), "best_place": place})
        hands = tr(f"{ss['hands']} mãos jogadas.", f"{ss['hands']} hands played.")
        if self.game_over:
            self.hint.setText(hands)
            self.next_btn.setText(tr("Novo torneio  ▸", "New tournament  ▸"))
        else:
            self.hint.setText(tr(f"Rodada {r} concluída em {ss['round_hands']} mãos. A próxima mesa começa do zero, "
                                 f"com {START_STACK} fichas.",
                                 f"Round {r} done in {ss['round_hands']} hands. The next table starts fresh with "
                                 f"{START_STACK} chips."))
            self.next_btn.setText(tr("Mesa final  ▸", "Final table  ▸") if r + 1 == n else
                                  tr("Próxima rodada  ▸", "Next round  ▸"))

    def _record_hand(self, won: int, net: int) -> None:
        """Soma esta mão às estatísticas acumuladas do jogador (aba Jogo simulado em Estatísticas)."""
        if self._snap is None or not self.hero.hole:
            return
        now = PF.counters_of(self.hero)
        delta = {k: now[k] - self._snap.get(k, 0) for k in now}
        delta["decisions"] = self.session["decisions"] - self._snap["decisions"]
        delta["good_decisions"] = self.session["good"] - self._snap["good_decisions"]
        delta["won_hands"] = int(won > 0)
        delta["net"] = net
        delta["biggest_win"] = max(0, net)
        S.add_play_hand(delta, net / self.table.bb)
        self._snap = None

    def hero_counters(self) -> dict:
        """Contadores da partida atual (sem contar a mão em andamento como jogada)."""
        c = PF.counters_of(self.hero)
        if self.table is not None and not self.table.hand_over and self.hero.hole:
            c["hands"] = max(0, c["hands"] - 1)
        return c

    def _update_moods(self) -> None:
        t = self.table
        scores = t.showdown_hands
        learning = S.get("show_personality")
        for i, p in enumerate(t.players):
            if p.ai is None or p.sitting_out:
                continue
            # memória: o que este bot aprendeu sobre os outros nesta mão
            before = (p.ai.fear(self.hero), p.ai.suspicion(self.hero))
            notes = p.ai.observe_hand(t, i)
            after = (p.ai.fear(self.hero), p.ai.suspicion(self.hero))
            if learning:
                for target, kind in notes:
                    if target is not self.hero:
                        continue
                    if kind == "bluff":
                        self._log(tr(f"🤨 {p.name} viu seu blefe — desconfiança de você: {before[1]:.0%} → "
                                     f"{after[1]:.0%}",
                                     f"🤨 {p.name} saw your bluff — suspicion of you: {before[1]:.0%} → "
                                     f"{after[1]:.0%}"))
                    else:
                        self._log(tr(f"😨 {p.name} viu sua mão forte — medo de você: {before[0]:.0%} → "
                                     f"{after[0]:.0%}",
                                     f"😨 {p.name} saw your strong hand — fear of you: {before[0]:.0%} → "
                                     f"{after[0]:.0%}"))
            if not p.hole:
                continue
            net_i = t.winners.get(i, 0) - p.total
            bad_beat = bool(scores) and i in scores and i not in t.winners and p.total >= 10 * t.bb \
                and scores[i] >> 20 >= E.TWO_PAIR
            before = p.ai.p.mood_emoji()
            p.ai.after_hand(net_i, t.bb, bad_beat)
            after = p.ai.p.mood_emoji()
            if after != before and after:
                self._log(f"{p.avatar} {p.name} {tr('está', 'is')} {after} {p.ai.p.mood_text()}")
            kind = None
            if bad_beat:
                kind = "badbeat"
            elif net_i > 40 * t.bb:
                kind = "bigwin"
            elif net_i > 0 and scores:
                kind = "win"
            elif net_i < -20 * t.bb:
                kind = "lose"
            if kind:
                line = ai.chat(kind, p.ai.p, self.rng)
                if line:
                    self._say(i, line)

    def _tick_auto(self) -> None:
        if self.paused:
            return
        if self._countdown <= 0:
            self.auto_timer.stop()
            self.next_hand()
            return
        self.next_btn.setText(tr(f"Próxima mão ({self._countdown})  ▸", f"Next hand ({self._countdown})  ▸"))
        self._countdown -= 1

    # ------------------------------------------------------------ controles de ritmo
    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.pause_btn.setText(tr("▶ Continuar", "▶ Resume") if self.paused else tr("⏸ Pausar", "⏸ Pause"))
        if self.paused:
            for tm in (self.q_timer, self.bot_timer, self.dots_timer, self.auto_timer):
                tm.stop()
            self.prompt.setText(tr("⏸ Pausado — P para continuar", "⏸ Paused — P to resume"))
            return
        t = self.table
        if t is None:
            return
        if self._pending_bot is not None:
            self.dots_timer.start()
            self.bot_timer.start(300)
        elif self._queue:
            self._run_queue()
        elif t.hand_over:
            self._hand_end_ui(replay=True)
            if self.auto_btn.isChecked() and not self.game_over:
                self._countdown = 3
                self.auto_timer.start()
        else:
            self._schedule()

    def toggle_sound(self) -> None:
        S.put("sounds", not S.get("sounds"))
        self._update_sound_btn()
        sound.play("chip")

    def _update_sound_btn(self) -> None:
        self.sound_btn.setText("🔊" if S.get("sounds") else "🔇")

    def set_players(self, n: int) -> None:
        """Muda o número de oponentes do jogo simulado (separado dos modos de treino) e começa outra partida."""
        S.put("play_opponents", n)
        self._update_players_btn()
        self.new_session()

    def _update_players_btn(self) -> None:
        self.players_btn.setText(f"👥 {S.get('play_opponents')}")

    def cycle_speed(self) -> None:
        cur = S.get("play_speed")
        nxt = SPEED_ORDER[(SPEED_ORDER.index(cur) + 1) % 3] if cur in SPEED_ORDER else "normal"
        S.put("play_speed", nxt)
        self._update_speed_btn()

    def _update_speed_btn(self) -> None:
        icon = {"slow": "🐢", "normal": "▶", "fast": "⏩"}.get(S.get("play_speed"), "▶")
        name = {k: n for n, k in speed_names()}.get(S.get("play_speed"), "")
        self.speed_btn.setText(f"{icon} {name}")

    def _toggle_auto(self) -> None:
        S.put("play_autonext", self.auto_btn.isChecked())
        if not self.auto_btn.isChecked():
            self.auto_timer.stop()
            if self.table is not None and self.table.hand_over and not self.game_over:
                self.next_btn.setText(tr("Próxima mão  ▸", "Next hand  ▸"))

    def skip_hand(self) -> None:
        """Você já saiu da mão: termina na hora, sem esperar os bots."""
        if self.table is None or self.table.hand_over and not self._queue or self.hero.can_act:
            return
        self.fast = True
        if self._pending_bot is not None:
            self.bot_timer.stop()
            self._bot_apply()
        elif self._queue:
            self.q_timer.stop()
            self._run_queue()

    def _set_mode(self, mode: str) -> None:
        """'act' (sua vez), 'wait' (outros jogando / animações) ou 'end' (mão encerrada)."""
        acting = mode == "act"
        pre = mode == "wait" and self._pre_visible()
        for w in (self.fold_btn, self.call_btn, self.raise_btn, self.size_widget):
            w.setVisible(acting)
            w.setEnabled(acting)
        self.pre_box.setVisible(pre)
        self.next_btn.setVisible(mode == "end")
        self.next_btn.setEnabled(mode == "end")
        if mode == "end":
            self.next_btn.setFocus()
        t = self.table
        if t is None:
            self.skip_btn.hide()
            return
        hero = self.hero
        can_act = hero.can_act and not t.hand_over
        self.skip_btn.setVisible(mode == "wait" and not can_act and (not t.hand_over or bool(self._queue)))
        if mode != "wait":
            return
        p = t.players[self.thinking] if self.thinking is not None else None
        if p is not None and not p.is_hero:
            self.prompt.setText(tr(f"{p.avatar} {p.name} está pensando…", f"{p.avatar} {p.name} is thinking…"))
        elif hero.in_hand and hero.all_in:
            self.prompt.setText(tr("Você está all-in — torcendo 🤞", "You're all-in — fingers crossed 🤞"))
        elif self._queue:
            self.prompt.setText(tr("Dando as cartas…", "Dealing…"))
        if can_act:
            self.hint.setText(tr("Pré-ações: escolha agora e o app age por você quando chegar a sua vez.",
                                 "Pre-actions: choose now and the app acts for you when it's your turn."))
        elif hero.in_hand:
            self.hint.setText(tr("Sem mais decisões nesta mão: é só esperar as cartas.",
                                 "No more decisions this hand: just watch the cards."))
        else:
            self.hint.setText(tr("Você está fora desta mão.", "You're out of this hand."))

    def _pre_visible(self) -> bool:
        t = self.table
        return t is not None and not t.hand_over and self.hero.can_act and t.to_act != 0

    # ------------------------------------------------------------ desenho
    def _say(self, seat: int, text: str) -> None:
        if self.fast or seat == 0:
            return
        sw = self._seat_widget(seat)
        self.bubbles[seat].say(text, QRectF(sw.geometry()), self.area.height())
        self._log(f"<span style='color:#c8d6d1'>💬 {self.table.players[seat].name}: “{text}”</span>")

    def _refresh(self, final: bool = False) -> None:
        t = self.table
        if t is None:
            return
        show_pers = S.get("show_personality")
        for i, p in enumerate(t.players):
            sw = self._seat_widget(i)
            out = p.sitting_out or (p.stack <= 0 and not p.hole)
            pr = p.ai.p if p.ai else None
            mood = pr.mood_emoji() if pr else ""
            sw.name.setText(f"{p.avatar} {p.name} {mood}".strip())
            pos = t.position_of(i)
            sw.badge.setText("D" if pos == "BTN" else pos if pos in ("SB", "BB") else "")
            sw.badge.setVisible(sw.badge.text() != "")
            sw.stack.setText("" if out else f"💰 {p.stack - self.hidden_win.get(i, 0)}")
            if out:
                sw.action.setText(tr("eliminado", "eliminated") if self.tournament else tr("fora", "out"))
            elif i == self.thinking or (final and i in t.showdown_hands and i in self.tabled):
                pass
            else:
                la = p.last_action
                amt = p.total - self.street_base[i] if self.street_base else p.bet
                if la in ("call", "bet", "raise", "allin") and amt <= 0:
                    amt = p.total
                sw.action.setText(action_text(la, amt) if la and not la.startswith(("SB", "BB")) else la)
            sw.set_state(active=(t.to_act == i and not t.hand_over and not self._queue), folded=p.folded, out=out,
                         winner=final and i in self.winner_seats)
            if i:
                hud = ""
                done = max(1, p.hands - (0 if t.hand_over else 1))
                if p.hands >= 5:   # notação usual de HUD: VPIP/PFR
                    hud = f"{p.vpip / done * 100:.0f}/{p.pfr / done * 100:.0f}"
                if show_pers and pr:
                    hud = (hud + " · " if hud else "") + ai.archetype_short(pr.archetype)
                fm = sw.hud.fontMetrics()
                hud = fm.elidedText(hud, Qt.ElideRight, sw.width() - 12)
                if show_pers and p.ai and self.hero.hands:
                    me = f"{tr('você', 'you')}: 😨 {p.ai.fear(self.hero):.0%} · 🤨 {p.ai.suspicion(self.hero):.0%}"
                    hud = (hud + "\n" if hud else "") + fm.elidedText(me, Qt.ElideRight, sw.width() - 12)
                sw.hud.setText(hud)
                sw.hud.setVisible(bool(hud) and not sw.compact)
                sw.setToolTip(self._seat_tooltip(p))
            else:
                c = self.hero_counters()
                hud = PF.short_hud(c)
                sw.hud.setText(" · ".join(x for x in (pos, hud) if x))
                sw.hud.setVisible(True)
                sw.setToolTip(PF.tooltip(c, tr("Suas estatísticas nesta partida", "Your stats this game")))
            if self.street_base:
                self.chips[i].set_amount(0 if self.paid else max(0, p.total - self.street_base[i]))
        self.pot_chip.prefix = tr("Pote ", "Pot ")
        self.pot_chip.set_amount(0 if self.paid or not self.street_base else sum(self.street_base))
        if self.hero.hole and not final and S.get("show_hand_name"):
            self.hand_name.setText(E.describe_cards(self.hero.hole + t.board[:self.shown_board]))
        elif not final:
            self.hand_name.setText(" ")
        info = [f"{tr('MÃO', 'HAND')} #{t.hand_no}", street_name(self._shown_street()).upper(),
                f"BLINDS {t.sb}/{t.bb}"]
        if self.tournament:
            info.append(tr("MESA FINAL", "FINAL TABLE") if self.final_table else
                        tr(f"RODADA {self.session['round']}/{self.session['rounds']}",
                           f"ROUND {self.session['round']}/{self.session['rounds']}"))
        info.append(ai.difficulty_name(self.session.get("diff", S.get("difficulty"))).upper())
        self.info.setText("  ·  ".join(info))
        self._layout_cards()

    def _shown_street(self) -> str:
        return {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(self.shown_board, "preflop")

    def _seat_tooltip(self, p: T.Player) -> str:
        lines = [f"<b>{p.avatar} {p.name}</b>"]
        if p.hands >= 5:
            lines.append(tr("<span style='color:#9fb3ad'>Na mesa: VPIP/PFR · estilo</span>",
                            "<span style='color:#9fb3ad'>On the table: VPIP/PFR · style</span>"))
        if p.hands:
            af = p.bets_raises / max(1, p.calls)
            lines.append(tr(f"{p.hands} mãos observadas", f"{p.hands} hands observed"))
            lines.append(tr(f"VPIP {p.vpip / p.hands:.0%}: joga essa fração das mãos",
                            f"VPIP {p.vpip / p.hands:.0%}: plays this share of hands"))
            lines.append(tr(f"PFR {p.pfr / p.hands:.0%}: aumenta antes do flop",
                            f"PFR {p.pfr / p.hands:.0%}: raises before the flop"))
            lines.append(tr(f"AF {af:.1f}: apostas+aumentos ÷ pagamentos (alto = agressivo)",
                            f"AF {af:.1f}: bets+raises ÷ calls (high = aggressive)"))
            if p.faced_bets:
                lines.append(tr(f"Desiste diante de aposta {p.folds_to_bet / p.faced_bets:.0%} das vezes",
                                f"Folds to a bet {p.folds_to_bet / p.faced_bets:.0%} of the time"))
        if S.get("show_personality") and p.ai:
            pr = p.ai.p
            lines.append("<br>" + tr("<b>Personalidade</b> (modo aprendizado)", "<b>Personality</b> (learning mode)"))
            lines.append(ai.archetype_name(pr.archetype) + f" · {tr('habilidade', 'skill')} {pr.skill:.0%}")
            lines.append(f"<i>{ai.archetype_help(pr.archetype)}</i>")
            names = {"aggression": tr("agressividade", "aggression"), "tightness": tr("seletividade", "tightness"),
                     "bluff": tr("blefe", "bluff"), "shove": tr("all-in", "all-in"),
                     "sticky": tr("paga demais", "calls too much"), "trap": tr("slowplay", "slowplay"),
                     "tilt_prone": tr("propensão a tilt", "tilt-prone")}
            for k, nm in names.items():
                if k == "bluff" and pr.archetype == "champion":
                    lines.append(nm + tr(": equilibrado (~1/3 das apostas)", ": balanced (~1/3 of bets)"))
                    continue
                lines.append(f"{nm}: {pr.eff(k) if k != 'tilt_prone' else pr.base[k]:.0%}")
            lines.append(tr(f"humor: {pr.mood_text()} (tilt {pr.tilt:.0%})",
                            f"mood: {pr.mood_text()} (tilt {pr.tilt:.0%})"))
            mem = p.ai.memory_summary(self.table.players)
            if mem:
                lines.append("<br>" + tr(f"<b>O que {p.name} pensa dos outros</b> (😨 medo · 🤨 desconfiança)",
                                         f"<b>What {p.name} thinks of the others</b> (😨 fear · 🤨 suspicion)"))
                for q, f, su in mem:
                    who = tr("você", "you") if q.is_hero else q.name
                    lines.append(f"{q.avatar} {who}: 😨 {f:.0%} · 🤨 {su:.0%}")
                lines.append(tr(f"<span style='color:#9fb3ad'>A memória pesa até {pr.influence:.0%} nas decisões "
                                f"(o resto é o jogo e o acaso). Reage a mãos fortes ×{pr.fear_gain:.1f} e a blefes "
                                f"×{pr.susp_gain:.1f}; esquece ~{1 - pr.memory:.1%} por mão.</span>",
                                f"<span style='color:#9fb3ad'>Memory weighs up to {pr.influence:.0%} in decisions "
                                f"(the rest is the game and chance). Reacts to strong hands ×{pr.fear_gain:.1f} and "
                                f"to bluffs ×{pr.susp_gain:.1f}; forgets ~{1 - pr.memory:.1%} per hand.</span>"))
        return "<br>".join(lines)

    def _log_events(self, evs) -> None:
        t = self.table
        for ev in evs:
            p = t.players[ev.seat] if ev.seat >= 0 else None
            if ev.kind == "action":
                self._log(f"{p.avatar} <b>{p.name}</b> {action_text(ev.action, ev.amount)}")
            elif ev.kind == "blind":
                self._log(f"{p.avatar} {p.name}: {ev.text} {ev.amount}")

    def _log(self, html: str) -> None:
        self.log_lines.append(html)
        self.log_lines = self.log_lines[-500:]
        self._render_log()

    def _render_log(self) -> None:
        # a partida inteira fica no histórico (role para cima para ver mãos anteriores)
        self.log.setText("<br>".join(self.log_lines).replace("<hr>", "<br>"))
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def _emit_stats(self) -> None:
        s = dict(self.session)
        s["stack"] = self.hero.stack
        s["profit"] = self.hero.stack - START_STACK * (1 + s["rebuys"])
        s["profile"] = self.hero_counters()
        bots = [p for p in self.table.players if p.ai is not None and not p.sitting_out]
        if bots and self.hero.hands:
            s["image"] = (sum(b.ai.fear(self.hero) for b in bots) / len(bots),
                          sum(b.ai.suspicion(self.hero) for b in bots) / len(bots))
        self.statsChanged.emit(s)

    # ------------------------------------------------------------ layout
    def _layout_cards(self) -> None:
        """Mesa oval: oponentes num arco da sua esquerda, por cima, até a sua direita; mesa no centro; você embaixo."""
        if not self.seats or self.table is None:
            return
        w, h = self.area.width(), self.area.height()
        n = len(self.seats)
        info_h = 20
        self.info.setGeometry(0, 0, w, info_h)
        hero_card = int(max(56, min(120, h * 0.15)))
        self.hero_seat.set_card_height(hero_card)
        hero_h = self.hero_seat.sizeHint().height()
        name_h = 26
        top = info_h + 2
        cx, cy = w / 2, (top + h - name_h) / 2
        span = 280 if n >= 6 else 250 if n >= 5 else 200
        hero_rect = QRect(int(cx - self.hero_seat.width() / 2), int(h - hero_h - name_h),
                          self.hero_seat.width(), hero_h)

        def place(card_h: int) -> list[QRect]:
            for s in self.seats:
                s.set_card_height(card_h)
            seat_h = max(s.sizeHint().height() for s in self.seats)
            seat_w = max(s.width() for s in self.seats)
            rx = max(10.0, w / 2 - seat_w / 2 - 2)
            ry = max(10.0, (h - name_h - top) / 2 - seat_h / 2)
            rects = []
            for i, s in enumerate(self.seats):
                a = math.radians(90 + span / 2 - span * (i + 0.5) / n) if n > 1 else math.pi / 2
                x = cx + rx * math.cos(a) - seat_w / 2
                y = cy - ry * math.sin(a) - seat_h / 2
                rects.append(QRect(int(x), int(max(top, min(h - name_h - seat_h, y))), s.width(), seat_h))
            return rects

        def overlaps(rects: list[QRect]) -> bool:
            boxes = rects + [hero_rect]
            return any(boxes[a].adjusted(-2, -2, 2, 2).intersects(boxes[b])
                       for a in range(len(boxes)) for b in range(a + 1, len(boxes)))

        # cartas dos oponentes do maior tamanho que caiba sem sobrepor assentos; se nada couber, assento compacto
        start = int(max(32, min(64 if n <= 4 else 54 if n <= 6 else 36, h * 0.085)))
        rects = None
        for compact in ((False, True) if n < 7 else (True,)):
            for s in self.seats:
                s.compact = compact
                s.hud.setVisible(bool(s.hud.text()) and not compact)
            for card_h in range(start, 31, -4):
                rects = place(card_h)
                if not overlaps(rects):
                    break
            else:
                continue
            break
        for s, r in zip(self.seats, rects):
            s.setGeometry(r)
        seat_w = max(s.width() for s in self.seats)
        self.hero_seat.setGeometry(hero_rect)
        # mesa de feltro (torneio): a borda passa por baixo do meio dos assentos
        seat_h = max(s.height() for s in self.seats)
        t_top = min(r.top() for r in rects) + seat_h * 0.5
        t_bot = hero_rect.top() + min(60, hero_h * 0.4)
        t_left, t_right = seat_w * 0.45, w - seat_w * 0.45
        if n <= 2:   # poucos assentos: mesa não tão comprida
            t_left, t_right = max(t_left, w * 0.12), min(t_right, w * 0.88)
        self.area.set_table_rect(QRectF(t_left, t_top, max(0, t_right - t_left), max(0, t_bot - t_top)))
        self.hand_name.setGeometry(0, h - name_h, w, name_h)
        # cartas comunitárias no centro
        free_w = w - 2 * seat_w - 20 if n >= 3 else w - 40
        board_h = int(max(46, min(h * 0.15, (free_w / 5 - 6) * CARD_RATIO * 0.88, 130)))
        for c in self.board_cards:
            c.set_card_height(board_h)
        cw, ch = self.board_cards[0].width(), self.board_cards[0].height()
        total = 5 * cw + 4 * 4
        bx = cx - total / 2
        by = cy - ch / 2 - h * 0.02
        for i, c in enumerate(self.board_cards):
            c.move(int(bx + i * (cw + 4)), int(by))
        self._pot_pos = QPoint(int(cx - self.pot_chip.width() / 2), int(by - 30))
        self.pot_chip.move(self._pot_pos)
        self.banner.setGeometry(int(cx - 260), int(by + ch + 2), 520, 24)
        # fichas de cada jogador: na borda do assento voltada para o centro da mesa
        for i in range(len(self.table.players)):
            g = self._seat_widget(i).geometry()
            sx, sy = g.center().x(), g.center().y()
            chip = self.chips[i] if i < len(self.chips) else None
            cwid = chip.width() if chip else 60
            if i == 0:
                px, py = sx, g.top() - 16
            else:
                dx, dy = cx - sx, cy - sy
                dist = math.hypot(dx, dy) or 1.0
                ux, uy = dx / dist, dy / dist
                hw, hh = g.width() / 2, g.height() / 2
                ext = min(hw / abs(ux) if abs(ux) > 1e-6 else 1e9, hh / abs(uy) if abs(uy) > 1e-6 else 1e9)
                px, py = sx + ux * (ext + cwid / 2 * abs(ux) + 8), sy + uy * (ext + 16)
            pos = QPoint(int(px - cwid / 2), int(py - 13))
            pos.setX(max(0, min(w - cwid, pos.x())))
            pos.setY(max(0, min(h - 26, pos.y())))
            self._chip_pos[i] = pos
            if chip:
                chip.move(pos)
                chip.raise_()
        self.pot_chip.raise_()
        for b in self.bubbles:
            if b.isVisible():
                b.raise_()

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self.next_btn.isVisible():
            self._next_clicked()
            return
        if k == Qt.Key_P:
            self.toggle_pause()
            return
        if self.table is not None and self.table.to_act == 0 and not self.table.hand_over and not self._queue:
            if k == Qt.Key_F:
                self.hero_act("fold")
                return
            if k == Qt.Key_C:
                self.hero_act("call")
                return
            if k == Qt.Key_R and self.raise_btn.isEnabled():
                self.hero_act("raise")
                return
        super().keyPressEvent(e)
