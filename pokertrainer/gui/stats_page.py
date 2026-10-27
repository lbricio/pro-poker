"""Estatísticas e revisão: evolução do erro, erro por tipo de mão, histórico e treino focado."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy,
    QTabWidget, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)

from pokertrainer import coach
from pokertrainer import engine as E
from pokertrainer import profile as PF
from pokertrainer import settings as S
from pokertrainer.i18n import tr
from pokertrainer.gui.widgets import Glass

GOLD = QColor("#f5c542")
INK = QColor("#e9eef0")
MUTED = QColor("#9fb3ad")
WINDOW = 10            # média móvel de 10 mãos
MIN_FOR_FOCUS = 3      # mãos mínimas de um tipo para sugerir treino focado


def mode_name(key: str) -> str:
    m = S.MODE_BY_KEY.get(key)
    return m.title if m else key


def cards_text(cards: list[int]) -> str:
    return " ".join(E.card_pretty(c) for c in cards)


# ---------------------------------------------------------------- gráfico

class ErrorChart(QWidget):
    """Erro de cada mão (pontos cinza) e média móvel (linha dourada), com dica ao passar o mouse."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.errors: list[float] = []
        self.avg: list[float] = []
        self.hover: int | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, errors: list[float]) -> None:
        self.errors = errors
        self.avg = []
        for i in range(len(errors)):
            w = errors[max(0, i - WINDOW + 1):i + 1]
            self.avg.append(sum(w) / len(w))
        self.hover = None
        self.update()

    def _plot(self) -> QRectF:
        return QRectF(44, 30, self.width() - 60, self.height() - 58)

    def _ymax(self) -> float:
        top = max(self.errors) if self.errors else 10
        for step in (10, 20, 30, 40, 50, 60, 80, 100):
            if top <= step:
                return step
        return 100

    def _pt(self, i: int, v: float) -> QPointF:
        r = self._plot()
        n = max(1, len(self.errors) - 1)
        x = r.left() + (r.width() * i / n if len(self.errors) > 1 else r.width() / 2)
        return QPointF(x, r.bottom() - r.height() * min(v, self._ymax()) / self._ymax())

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        small = QFont(self.font())
        small.setPixelSize(11)
        p.setFont(small)
        # legenda (2 séries) + título do eixo
        p.setPen(GOLD)
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(r.left(), 10), QPointF(r.left() + 18, 10))
        p.setPen(MUTED)
        p.drawText(QRectF(r.left() + 24, 2, 260, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   tr(f"média das últimas {WINDOW} mãos", f"average of the last {WINDOW} hands"))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 90))
        p.drawEllipse(QPointF(r.left() + 250, 10), 4, 4)
        p.setPen(MUTED)
        p.drawText(QRectF(r.left() + 258, 2, 200, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   tr("erro de cada mão", "error per hand"))
        # grade recessiva e eixo y (pontos de erro)
        ymax = self._ymax()
        for k in range(5):
            v = ymax * k / 4
            y = r.bottom() - r.height() * k / 4
            p.setPen(QPen(QColor(255, 255, 255, 22 if k else 60), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(MUTED)
            p.drawText(QRectF(0, y - 8, r.left() - 8, 16), Qt.AlignRight | Qt.AlignVCenter, f"{v:.0f}")
        p.drawText(QRectF(r.left(), r.bottom() + 6, r.width(), 16), Qt.AlignCenter,
                   tr(f"últimas {len(self.errors)} mãos (erro em pontos)",
                      f"last {len(self.errors)} hands (error in points)"))
        if not self.errors:
            p.setPen(MUTED)
            p.drawText(r, Qt.AlignCenter, tr("Jogue algumas mãos para ver sua evolução.",
                                             "Play a few hands to see your progress."))
            return
        # pontos de cada mão
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 70))
        for i, v in enumerate(self.errors):
            p.drawEllipse(self._pt(i, v), 3, 3)
        # média móvel
        path = QPainterPath(self._pt(0, self.avg[0]))
        for i, v in enumerate(self.avg[1:], 1):
            path.lineTo(self._pt(i, v))
        p.setPen(QPen(GOLD, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        # rótulo direto no último valor
        last = self._pt(len(self.avg) - 1, self.avg[-1])
        p.setPen(INK)
        p.drawText(QRectF(last.x() - 64, last.y() - 22, 64, 16), Qt.AlignRight | Qt.AlignVCenter,
                   f"{self.avg[-1]:.1f}")
        # mira
        if self.hover is not None:
            hp = self._pt(self.hover, self.avg[self.hover])
            p.setPen(QPen(QColor(255, 255, 255, 80), 1))
            p.drawLine(QPointF(hp.x(), r.top()), QPointF(hp.x(), r.bottom()))
            p.setPen(QPen(QColor("#161d21"), 2))
            p.setBrush(GOLD)
            p.drawEllipse(hp, 5, 5)

    def mouseMoveEvent(self, e) -> None:
        if not self.errors:
            return
        r = self._plot()
        n = len(self.errors)
        x = e.position().x()
        i = 0 if n == 1 else round((x - r.left()) / r.width() * (n - 1))
        i = max(0, min(n - 1, i))
        self.hover = i
        self.update()
        QToolTip.showText(e.globalPosition().toPoint(), tr(
            f"Mão {i + 1}: erro {self.errors[i]:.1f} pts<br>Média até aqui: <b>{self.avg[i]:.1f}</b>",
            f"Hand {i + 1}: error {self.errors[i]:.1f} pts<br>Average so far: <b>{self.avg[i]:.1f}</b>"), self)

    def leaveEvent(self, _e) -> None:
        self.hover = None
        self.update()


# ---------------------------------------------------------------- página

def _tile(label: str) -> tuple[QFrame, QLabel]:
    f = QFrame()
    f.setObjectName("card")
    v = QVBoxLayout(f)
    v.setContentsMargins(14, 8, 14, 8)
    v.setSpacing(0)
    val = QLabel("–")
    val.setObjectName("statValue")
    lbl = QLabel(label)
    lbl.setObjectName("statLabel")
    v.addWidget(val)
    v.addWidget(lbl)
    return f, val


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setShowGrid(False)
    t.verticalHeader().setDefaultSectionSize(28)
    hh = t.horizontalHeader()
    hh.setHighlightSections(False)
    for c in range(len(headers)):
        hh.setSectionResizeMode(c, QHeaderView.Stretch if c == 0 else QHeaderView.ResizeToContents)
    return t


def _item(text: str, align=Qt.AlignCenter, color: str | None = None) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setTextAlignment(Qt.AlignVCenter | align)
    if color:
        it.setForeground(QColor(color))
    return it


class StatsPage(QWidget):
    reviewRequested = Signal(dict)   # entrada do histórico
    focusRequested = Signal(str)     # tipo de mão

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 12, 24, 20)
        panel = Glass(alpha=180)
        outer.addWidget(panel)
        v = QVBoxLayout(panel)
        v.setContentsMargins(26, 18, 26, 18)
        v.setSpacing(10)

        head = QHBoxLayout()
        t = QLabel(tr("Estatísticas e revisão", "Stats and review"))
        t.setObjectName("pageTitle")
        head.addWidget(t)
        head.addStretch(1)
        self.filter = QComboBox()
        self.filter.addItem(tr("Todos os modos", "All modes"), "")
        for m in S.MODES:
            if not m.is_play:
                self.filter.addItem(m.title, m.key)
        self.filter.currentIndexChanged.connect(self.refresh)
        head.addWidget(self.filter)
        v.addLayout(head)
        self.tabs = QTabWidget()
        train = QWidget()
        outer_v = v
        v = QVBoxLayout(train)
        v.setContentsMargins(0, 10, 0, 0)
        v.setSpacing(10)

        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.t_hands = _tile(tr("mãos jogadas", "hands played"))
        self.t_err = _tile(tr("erro médio (pts)", "average error (pts)"))
        self.t_bias = _tile(tr("tendência", "tendency"))
        self.t_hits = _tile(tr("acertos", "hits"))
        self.t_dec = _tile(tr("decisões certas (pot odds)", "right decisions (pot odds)"))
        self.t_ev = _tile(tr("EV total das decisões", "total EV of decisions"))
        for f, _ in (self.t_hands, self.t_err, self.t_bias, self.t_hits, self.t_dec, self.t_ev):
            tiles.addWidget(f, 1)
        v.addLayout(tiles)

        self.chart = ErrorChart()
        v.addWidget(self.chart, 2)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        left_head = QHBoxLayout()
        lt = QLabel(tr("ERRO POR TIPO DE MÃO", "ERROR BY HAND TYPE"))
        lt.setObjectName("section")
        left_head.addWidget(lt)
        left_head.addStretch(1)
        self.focus_btn = QPushButton(tr("🎯  Treinar meu ponto fraco", "🎯  Train my weak spot"))
        self.focus_btn.setObjectName("chip")
        self.focus_btn.setCursor(Qt.PointingHandCursor)
        self.focus_btn.clicked.connect(self._focus_weakest)
        left_head.addWidget(self.focus_btn)
        grid.addLayout(left_head, 0, 0)
        self.types = _table([tr("Tipo de mão", "Hand type"), tr("Mãos", "Hands"), tr("Erro médio", "Avg error"),
                             tr("Tendência", "Tendency")])
        self.types.setToolTip(tr("Dê dois cliques para treinar só esse tipo de mão.",
                                 "Double-click to train only this hand type."))
        self.types.cellDoubleClicked.connect(self._focus_row)
        grid.addWidget(self.types, 1, 0)

        right_head = QHBoxLayout()
        rt = QLabel(tr("ÚLTIMAS MÃOS", "RECENT HANDS"))
        rt.setObjectName("section")
        right_head.addWidget(rt)
        right_head.addStretch(1)
        self.review_btn = QPushButton(tr("↺  Rever mão", "↺  Review hand"))
        self.review_btn.setObjectName("chip")
        self.review_btn.setCursor(Qt.PointingHandCursor)
        self.review_btn.clicked.connect(self._review_selected)
        right_head.addWidget(self.review_btn)
        grid.addLayout(right_head, 0, 1)
        self.hist = _table([tr("Mão", "Hand"), tr("Modo", "Mode"), tr("Palpite", "Guess"), tr("Real", "Actual"),
                            tr("Erro", "Error")])
        self.hist.setToolTip(tr("Dê dois cliques para rever a mão na mesa.", "Double-click to review the hand."))
        self.hist.cellDoubleClicked.connect(lambda r, _c: self._review_row(r))
        grid.addWidget(self.hist, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid, 3)
        self.play_tab = PlayStatsTab()
        self.tabs.addTab(train, tr("Treino", "Training"))
        self.tabs.addTab(self.play_tab, tr("Jogo simulado", "Simulated game"))
        self.tabs.currentChanged.connect(lambda i: self.filter.setVisible(i == 0))
        outer_v.addWidget(self.tabs, 1)
        self._rows: list[dict] = []
        self._type_keys: list[str] = []

    # ------------------------------------------------------------ dados
    def refresh(self) -> None:
        self.play_tab.refresh()
        key = self.filter.currentData()
        hist = [h for h in S.load_history() if not key or h.get("mode") == key]
        n = len(hist)
        errs = [h["err"] for h in hist]
        bias = sum(h["guess"] - h["eq"] * 100 for h in hist) / n if n else 0.0
        self.t_hands[1].setText(str(n))
        self.t_err[1].setText(f"{sum(errs) / n:.1f}" if n else "–")
        if n:
            word = (tr("superestima", "overestimates") if bias > 1 else
                    tr("subestima", "underestimates") if bias < -1 else tr("equilibrado", "balanced"))
            self.t_bias[1].setText(f"{bias:+.1f} {word}" if abs(bias) > 1 else word)
        else:
            self.t_bias[1].setText("–")
        tol = S.get("tolerance")
        self.t_hits[1].setText(f"{sum(e <= tol for e in errs) / n:.0%}" if n else "–")
        dec = [h for h in hist if h.get("called") is not None]
        self.t_dec[1].setText(f"{sum(bool(h.get('good')) for h in dec) / len(dec):.0%}" if dec else "–")
        self.t_ev[1].setText(f"{sum(h.get('ev', 0.0) for h in dec):+.0f}" if dec else "–")
        self.chart.set_data(errs[-200:])

        # por tipo de mão, pior primeiro
        groups: dict[str, list[dict]] = {}
        for h in hist:
            groups.setdefault(h.get("type", ""), []).append(h)
        rows = sorted(((k, g) for k, g in groups.items() if k),
                      key=lambda kg: -sum(x["err"] for x in kg[1]) / len(kg[1]))
        self._type_keys = [k for k, _ in rows]
        self.types.setRowCount(len(rows))
        for r, (k, g) in enumerate(rows):
            e = sum(x["err"] for x in g) / len(g)
            b = sum(x["guess"] - x["eq"] * 100 for x in g) / len(g)
            self.types.setItem(r, 0, _item(coach.hand_type_name(k), Qt.AlignLeft))
            self.types.setItem(r, 1, _item(str(len(g))))
            self.types.setItem(r, 2, _item(f"{e:.1f}", color="#ff8a80" if e > 2 * tol else None))
            self.types.setItem(r, 3, _item(f"{b:+.1f}" + (" ▲" if b > 1 else " ▼" if b < -1 else "")))
        self.focus_btn.setEnabled(any(len(g) >= MIN_FOR_FOCUS for _, g in rows))

        # histórico, mais recente primeiro
        self._rows = list(reversed(hist[-100:]))
        self.hist.setRowCount(len(self._rows))
        for r, h in enumerate(self._rows):
            board = h["board"][:h["vis"]]
            hand = cards_text(h["hero"]) + ("   |   " + cards_text(board) if board else "")
            self.hist.setItem(r, 0, _item(hand, Qt.AlignLeft))
            self.hist.setItem(r, 1, _item(mode_name(h["mode"])))
            self.hist.setItem(r, 2, _item(f"{h['guess']}%"))
            self.hist.setItem(r, 3, _item(f"{h['eq'] * 100:.1f}%"))
            self.hist.setItem(r, 4, _item(f"{h['err']:.1f}", color="#ff8a80" if h["err"] > 2 * tol else None))
        self.review_btn.setEnabled(bool(self._rows))

    def weakest_type(self) -> str | None:
        key = self.filter.currentData()
        groups: dict[str, list[float]] = {}
        for h in S.load_history():
            if (not key or h.get("mode") == key) and h.get("type"):
                groups.setdefault(h["type"], []).append(h["err"])
        cand = [(sum(v) / len(v), k) for k, v in groups.items() if len(v) >= MIN_FOR_FOCUS]
        return max(cand)[1] if cand else None

    # ------------------------------------------------------------ ações
    def _focus_weakest(self) -> None:
        k = self.weakest_type()
        if k:
            self.focusRequested.emit(k)

    def _focus_row(self, r: int, _c: int) -> None:
        if 0 <= r < len(self._type_keys):
            self.focusRequested.emit(self._type_keys[r])

    def _review_selected(self) -> None:
        rows = self.hist.selectionModel().selectedRows()
        self._review_row(rows[0].row() if rows else 0)

    def _review_row(self, r: int) -> None:
        if 0 <= r < len(self._rows):
            self.reviewRequested.emit(self._rows[r])


# ---------------------------------------------------------------- jogo simulado (totais acumulados)

class ProfitChart(QWidget):
    """Lucro acumulado em big blinds, mão a mão (uma série; linha do zero destacada)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.cum: list[float] = []
        self.hover: int | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, per_hand: list[float]) -> None:
        acc, self.cum = 0.0, []
        for v in per_hand:
            acc += v
            self.cum.append(acc)
        self.hover = None
        self.update()

    def _plot(self) -> QRectF:
        return QRectF(52, 26, self.width() - 66, self.height() - 52)

    def _range(self) -> tuple[float, float, float]:
        lo, hi = min(self.cum + [0.0]), max(self.cum + [0.0])
        span = max(hi - lo, 10.0)
        raw = span / 4
        mag = 10 ** math.floor(math.log10(raw))
        step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
        return math.floor(lo / step) * step, math.ceil(hi / step) * step, step

    def _pt(self, i: int, v: float) -> QPointF:
        r = self._plot()
        lo, hi, _ = self._range()
        n = max(1, len(self.cum) - 1)
        x = r.left() + r.width() * i / n
        return QPointF(x, r.bottom() - r.height() * (v - lo) / (hi - lo))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        small = QFont(self.font())
        small.setPixelSize(11)
        p.setFont(small)
        p.setPen(MUTED)
        p.drawText(QRectF(r.left(), 2, r.width(), 18), Qt.AlignLeft | Qt.AlignVCenter,
                   tr("Lucro acumulado (big blinds)", "Cumulative profit (big blinds)"))
        if not self.cum:
            p.drawText(r, Qt.AlignCenter, tr("Jogue algumas mãos no modo Jogar para ver sua curva.",
                                             "Play a few hands in Play mode to see your curve."))
            return
        lo, hi, step = self._range()
        v = lo
        while v <= hi + 1e-9:
            y = self._pt(0, v).y()
            p.setPen(QPen(QColor(255, 255, 255, 70 if abs(v) < 1e-9 else 22), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(MUTED)
            p.drawText(QRectF(0, y - 8, r.left() - 8, 16), Qt.AlignRight | Qt.AlignVCenter, f"{v:+.0f}" if v else "0")
            v += step
        p.drawText(QRectF(r.left(), r.bottom() + 6, r.width(), 16), Qt.AlignCenter,
                   tr(f"{len(self.cum)} mãos", f"{len(self.cum)} hands"))
        path = QPainterPath(self._pt(0, self.cum[0]))
        for i, c in enumerate(self.cum[1:], 1):
            path.lineTo(self._pt(i, c))
        p.setPen(QPen(GOLD, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        last = self._pt(len(self.cum) - 1, self.cum[-1])
        p.setPen(INK)
        p.drawText(QRectF(last.x() - 80, last.y() - 22, 80, 16), Qt.AlignRight | Qt.AlignVCenter,
                   f"{self.cum[-1]:+.0f} bb")
        if self.hover is not None:
            hp = self._pt(self.hover, self.cum[self.hover])
            p.setPen(QPen(QColor(255, 255, 255, 80), 1))
            p.drawLine(QPointF(hp.x(), r.top()), QPointF(hp.x(), r.bottom()))
            p.setPen(QPen(QColor("#161d21"), 2))
            p.setBrush(GOLD)
            p.drawEllipse(hp, 5, 5)

    def mouseMoveEvent(self, e) -> None:
        if not self.cum:
            return
        r = self._plot()
        n = len(self.cum)
        i = 0 if n == 1 else round((e.position().x() - r.left()) / r.width() * (n - 1))
        i = max(0, min(n - 1, i))
        self.hover = i
        self.update()
        QToolTip.showText(e.globalPosition().toPoint(), tr(
            f"Mão {i + 1}: <b>{self.cum[i]:+.1f} bb</b> acumulados",
            f"Hand {i + 1}: <b>{self.cum[i]:+.1f} bb</b> cumulative"), self)

    def leaveEvent(self, _e) -> None:
        self.hover = None
        self.update()


class PlayStatsTab(QWidget):
    """Seu perfil de jogador acumulado em todas as partidas do modo Jogar."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 10, 0, 0)
        v.setSpacing(10)
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.t_hands = _tile(tr("mãos jogadas", "hands played"))
        self.t_net = _tile(tr("lucro total (fichas)", "total profit (chips)"))
        self.t_bb = _tile(tr("bb/100 (taxa de ganho)", "bb/100 (win rate)"))
        self.t_won = _tile(tr("mãos vencidas", "hands won"))
        self.t_dec = _tile(tr("decisões certas", "right decisions"))
        self.t_tour = _tile(tr("torneios (vitórias · melhor)", "tournaments (wins · best)"))
        for f, _ in (self.t_hands, self.t_net, self.t_bb, self.t_won, self.t_dec, self.t_tour):
            tiles.addWidget(f, 1)
        v.addLayout(tiles)
        row = QHBoxLayout()
        row.setSpacing(16)
        left = QVBoxLayout()
        self.chart = ProfitChart()
        left.addWidget(self.chart, 1)
        self.style_lbl = QLabel()
        self.style_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #f5c542;")
        self.style_lbl.setWordWrap(True)
        left.addWidget(self.style_lbl)
        self.advice = QLabel()
        self.advice.setWordWrap(True)
        self.advice.setTextFormat(Qt.RichText)
        self.advice.setObjectName("muted")
        left.addWidget(self.advice)
        row.addLayout(left, 1)
        right = QVBoxLayout()
        lt = QLabel(tr("SEU PERFIL (TODAS AS PARTIDAS)", "YOUR PROFILE (ALL GAMES)"))
        lt.setObjectName("section")
        right.addWidget(lt)
        self.table = _table([tr("Estatística", "Stat"), tr("Você", "You"), tr("Referência", "Reference"),
                             tr("Avaliação", "Verdict")])
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        right.addWidget(self.table, 1)
        note = QLabel(tr("Referência: faixas típicas de um jogador sólido em mesas de 6 a 9 jogadores. "
                         "Passe o mouse numa linha para ver o que a estatística mede.",
                         "Reference: typical ranges of a solid player at 6- to 9-handed tables. "
                         "Hover a row to see what the stat measures."))
        note.setWordWrap(True)
        note.setObjectName("muted")
        note.setStyleSheet("font-size: 11px;")
        right.addWidget(note)
        row.addLayout(right, 1)
        v.addLayout(row, 1)

    def refresh(self) -> None:
        d = S.load_play_stats()
        c = {k: d.get(k, 0) for k in PF.COUNTERS}
        n = d.get("hands", 0)
        self.t_hands[1].setText(str(n))
        self.t_net[1].setText(f"{d.get('net', 0):+d}" if n else "–")
        self.t_bb[1].setText(f"{d.get('net_bb', 0.0) / n * 100:+.1f}" if n else "–")
        self.t_won[1].setText(f"{d.get('won_hands', 0) / n:.0%}" if n else "–")
        dec = d.get("decisions", 0)
        self.t_dec[1].setText(f"{d.get('good_decisions', 0) / dec:.0%}" if dec else "–")
        tours = d.get("tournaments", 0)
        best = d.get("best_place", 0)
        self.t_tour[1].setText(f"{tours} ({d.get('tourn_wins', 0)} · {best}º)" if tours and best else
                               str(tours) if tours else "–")
        self.chart.set_data(S.load_play_curve())
        stats = PF.stats(c)
        self.table.setRowCount(len(stats))
        for r, st in enumerate(stats):
            verdict, color = st.verdict()
            items = [_item(st.short, Qt.AlignLeft), _item(st.fmt()), _item(st.ref()), _item(verdict, color=color)]
            for col, it in enumerate(items):
                it.setToolTip(f"<b>{st.name}</b><br>{st.help}" +
                              tr(f"<br>Amostra: {st.sample}", f"<br>Sample: {st.sample}"))
                self.table.setItem(r, col, it)
        self.style_lbl.setText(PF.style_text(c).capitalize() if n else "")
        tips = PF.advice(c)
        self.advice.setText("".join(f"• {t}<br>" for t in tips) if tips else
                            (tr("Suas estatísticas estão nas faixas de referência. 👍",
                                "Your stats are within the reference ranges. 👍") if n >= PF.MIN_HANDS else ""))
