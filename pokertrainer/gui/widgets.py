"""Componentes visuais: fundo borrado, carta animada, barra de palpite e painel translúcido."""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import (
    Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSequentialAnimationGroup, QPauseAnimation, Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame, QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QWidget,
)

from pokertrainer.engine import card_str
from pokertrainer.i18n import tr

ASSETS = Path(__file__).resolve().parent.parent / "assets"
CARD_RATIO = 1.45  # altura / largura

GOLD = QColor("#f5c542")
GREEN = QColor("#3ddc84")
RED = QColor("#ff5c5c")


# ---------------------------------------------------------------- imagens

_card_cache: dict[str, QPixmap] = {}


def card_pixmap(c: int | None) -> QPixmap:
    name = "back" if c is None else card_str(c)
    pm = _card_cache.get(name)
    if pm is None:
        pm = QPixmap(str(ASSETS / "cards" / f"{name}.png"))
        _card_cache[name] = pm
    return pm


def blur_image(img: QImage, radius: float) -> QImage:
    """Desfoque gaussiano (via QGraphicsBlurEffect), recortando as bordas que ficariam transparentes."""
    if radius <= 0:
        return img
    w, h = img.width(), img.height()
    m = radius * 2
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(img))
    eff = QGraphicsBlurEffect()
    eff.setBlurRadius(radius)
    eff.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(eff)
    scene.addItem(item)
    out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.black)
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    scene.render(p, QRectF(0, 0, w, h), QRectF(m, m, w - 2 * m, h - 2 * m))
    p.end()
    return out


# ---------------------------------------------------------------- fundo

class Background(QWidget):
    """Widget raiz: desenha a foto da mesa desfocada, escurecida, cobrindo toda a janela."""

    def __init__(self, blur: int, parent=None) -> None:
        super().__init__(parent)
        self._src = QImage(str(ASSETS / "table_bg.jpg"))
        if self._src.width() > 1280:
            self._src = self._src.scaledToWidth(1280, Qt.SmoothTransformation)
        self._pm = QPixmap()
        self.set_blur(blur)

    def set_blur(self, blur: int) -> None:
        self._pm = QPixmap.fromImage(blur_image(self._src, blur))
        self._scaled = None
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        if self._scaled is None or self._scaled.size() != self.size():
            pm = self._pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x, y = (pm.width() - w) // 2, (pm.height() - h) // 2
            self._scaled = pm.copy(x, y, w, h)
        p.drawPixmap(0, 0, self._scaled)
        p.fillRect(self.rect(), QColor(6, 12, 10, 120))
        vign = QRadialGradient(QPointF(w * 0.6, h * 0.45), max(w, h) * 0.75)
        vign.setColorAt(0.0, QColor(0, 0, 0, 0))
        vign.setColorAt(1.0, QColor(0, 0, 0, 170))
        p.fillRect(self.rect(), QBrush(vign))


class Glass(QFrame):
    """Painel translúcido de cantos arredondados."""

    def __init__(self, parent=None, alpha: int = 175, radius: int = 18) -> None:
        super().__init__(parent)
        self._alpha = alpha
        self._radius = radius
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)
        p.fillPath(path, QColor(12, 18, 22, self._alpha))
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.drawPath(path)


# ---------------------------------------------------------------- carta

class CardWidget(QWidget):
    """Carta de baralho com animação de virar e destaque (vencedora / apagada)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._card: int | None = None
        self._face_up = False
        self._shown_face = False   # face desenhada no momento (troca no meio do giro)
        self._flip = 0.0           # 0..1 (progresso do giro)
        self._lift = 0.0
        self.highlight = False
        self.dimmed = False
        self.dim_alpha = 120
        self._anim: QSequentialAnimationGroup | None = None
        self._scaled_key = None
        self._scaled_pm: QPixmap | None = None
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.set_card_height(160)

    # tamanho
    def set_card_height(self, h: int) -> None:
        h = max(40, int(h))
        w = round(h / CARD_RATIO)
        pad = max(4, h // 18)  # espaço para sombra / brilho
        self._pad = pad
        self.setFixedSize(w + 2 * pad, h + 2 * pad)
        self._scaled_key = None
        self.update()

    def card_height(self) -> int:
        return self.height() - 2 * self._pad

    # estado
    def set_card(self, c: int | None, face_up: bool, animate: bool = False, delay_ms: int = 0) -> None:
        self._stop()
        self._card = c
        self.highlight = False
        self.dimmed = False
        if animate:
            self._face_up = self._shown_face = False
            self._flip = 0.0
            if face_up:
                self.flip_up(delay_ms)
        else:
            self._face_up = self._shown_face = face_up
            self._flip = 0.0
        self._scaled_key = None
        self.update()

    def flip_up(self, delay_ms: int = 0, animate: bool = True) -> None:
        if self._face_up:
            return
        self._face_up = True
        if not animate:
            self._shown_face = True
            self.update()
            return
        self._stop()
        g = QSequentialAnimationGroup(self)
        if delay_ms:
            g.addAnimation(QPauseAnimation(delay_ms))
        a = QPropertyAnimation(self, b"flip")
        a.setDuration(420)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.InOutCubic)
        g.addAnimation(a)
        g.finished.connect(self._done)
        self._anim = g
        g.start()

    def _done(self) -> None:
        self._flip = 0.0
        self._shown_face = self._face_up
        self._scaled_key = None
        self.update()

    def _stop(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim = None

    def _get_flip(self) -> float:
        return self._flip

    def _set_flip(self, v: float) -> None:
        self._flip = v
        self._shown_face = self._face_up if v >= 0.5 else not self._face_up
        self._scaled_key = None
        self.update()

    flip = Property(float, _get_flip, _set_flip)

    def set_highlight(self, on: bool) -> None:
        self.highlight = on
        self.update()

    def set_dimmed(self, on: bool) -> None:
        self.dimmed = on
        self.update()

    # desenho
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pad = self._pad
        w, h = self.width() - 2 * pad, self.height() - 2 * pad
        sx = abs(math.cos(math.pi * self._flip)) if self._flip else 1.0
        sx = max(sx, 0.02)
        cw = w * sx
        x = pad + (w - cw) / 2
        rect = QRectF(x, pad, cw, h)
        radius = w * 0.07

        # sombra
        sh = QPainterPath()
        sh.addRoundedRect(rect.translated(0, pad * 0.45), radius, radius)
        p.fillPath(sh, QColor(0, 0, 0, 90))

        if self.highlight:
            glow = QPainterPath()
            glow.addRoundedRect(rect.adjusted(-pad * 0.7, -pad * 0.7, pad * 0.7, pad * 0.7), radius * 1.4, radius * 1.4)
            p.fillPath(glow, QColor(245, 197, 66, 150))

        key = (self._shown_face, int(cw), int(h))
        if self._scaled_key != key:
            src = card_pixmap(self._card if self._shown_face else None)
            dpr = self.devicePixelRatioF()
            pm = src.scaled(max(1, int(cw * dpr)), max(1, int(h * dpr)), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self._scaled_pm, self._scaled_key = pm, key
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        p.save()
        p.setClipPath(clip)
        p.drawPixmap(rect.topLeft(), self._scaled_pm)
        if self.dimmed:
            p.fillRect(rect, QColor(0, 0, 0, self.dim_alpha))
        p.restore()
        if self.highlight:
            p.setPen(QPen(GOLD, max(2.0, pad * 0.35)))
            p.drawPath(clip)


# ---------------------------------------------------------------- etiqueta com fundo escuro

class PillLabel(QWidget):
    """Texto curto sobre fundo escuro arredondado (legível sobre a mesa). Altura fixa; some quando vazio."""

    def __init__(self, lines: int = 2, font_px: int = 11, color: str = "#e3ece9", parent=None) -> None:
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setWordWrap(lines > 1)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet(f"QLabel {{ font-size: {font_px}px; color: {color}; font-weight: 600; "
                                 "background: rgba(8,12,14,0.78); border: 1px solid rgba(255,255,255,0.10); "
                                 "border-radius: 8px; padding: 2px 8px; }")
        self.label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        h.addWidget(self.label, 0, Qt.AlignHCenter | Qt.AlignTop)
        self.setFixedHeight(self.label.fontMetrics().lineSpacing() * lines + 8)
        self.label.hide()

    def setText(self, text: str) -> None:
        self.label.setText(text)
        self.label.setVisible(bool(text.strip()))
        if not self.label.wordWrap():
            # linha única: largura certa para o texto (sem cortar), limitada à largura da etiqueta
            need = self.label.fontMetrics().horizontalAdvance(text) + 20
            self.label.setFixedWidth(min(need, self.maximumWidth()) if self.maximumWidth() < 10000 else need)

    def text(self) -> str:
        return self.label.text()

    def setFixedWidth(self, w: int) -> None:
        super().setFixedWidth(w)
        self.label.setMaximumWidth(w)


# ---------------------------------------------------------------- bandeiras

def flag_pixmap(code: str, w: int = 24, h: int = 16, dpr: float = 2.0) -> QPixmap:
    """Bandeira desenhada (não depende de fontes de emoji): 'pt' = Brasil, 'en' = EUA."""
    pm = QPixmap(int(w * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, w, h), 2.5, 2.5)
    p.setClipPath(clip)
    if code == "pt":
        p.fillRect(QRectF(0, 0, w, h), QColor("#009c3b"))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffdf00"))
        mx, my = w * 0.09, h * 0.14
        p.drawPolygon(QPolygonF([QPointF(w / 2, my), QPointF(w - mx, h / 2), QPointF(w / 2, h - my),
                                 QPointF(mx, h / 2)]))
        p.setBrush(QColor("#002776"))
        r = h * 0.25
        p.drawEllipse(QPointF(w / 2, h / 2), r, r)
        p.setPen(QPen(QColor("white"), max(0.8, h * 0.05)))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(w / 2 - r * 1.6, h / 2 - r * 0.55, r * 3.2, r * 3.4), 62 * 16, 56 * 16)
    else:
        # EUA: 13 listras, cantão azul com estrelas (pontos)
        stripe = h / 13
        p.fillRect(QRectF(0, 0, w, h), QColor("white"))
        for i in range(0, 13, 2):
            p.fillRect(QRectF(0, i * stripe, w, stripe), QColor("#b22234"))
        cw, chh = w * 0.42, stripe * 7
        p.fillRect(QRectF(0, 0, cw, chh), QColor("#3c3b6e"))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("white"))
        rows, cols = 4, 5
        for r in range(rows):
            for c in range(cols - (r % 2)):
                x = cw * (c + 0.5 + (r % 2) * 0.5) / cols
                y = chh * (r + 0.5) / rows
                p.drawEllipse(QPointF(x, y), 0.55, 0.55)
    p.setClipping(False)
    p.setPen(QPen(QColor(255, 255, 255, 70), 0.8))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(0.4, 0.4, w - 0.8, h - 0.8), 2.5, 2.5)
    p.end()
    return pm


# ---------------------------------------------------------------- botão do baralho

class DeckButton(QPushButton):
    """Pilha de cartas com a quantidade de cartas que ainda podem sair."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.remaining = 52
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr("Ver as cartas que ainda podem aparecer", "See the cards that can still come"))
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self.set_card_height(100)

    def set_card_height(self, h: int) -> None:
        self._ch = max(40, int(h))
        cw = self._ch / CARD_RATIO
        self.setFixedSize(max(int(cw + 22), 118), int(self._ch + 14 + 34))

    def set_remaining(self, n: int) -> None:
        self.remaining = n
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        ch = self._ch
        cw = ch / CARD_RATIO
        hover = self.underMouse()
        back = card_pixmap(None)
        radius = cw * 0.07
        for i in range(3, -1, -1):
            r = QRectF(4 + i * 4, 4 + (3 - i) * 3 - (3 if hover else 0), cw, ch)
            sh = QPainterPath()
            sh.addRoundedRect(r.translated(0, 2), radius, radius)
            p.fillPath(sh, QColor(0, 0, 0, 70))
            clip = QPainterPath()
            clip.addRoundedRect(r, radius, radius)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(r, back, QRectF(back.rect()))
            p.restore()
            p.setPen(QPen(QColor(255, 255, 255, 60 if i else 120), 1))
            p.drawPath(clip)
        # selo com a quantidade
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(max(12, int(ch * 0.15)))
        p.setFont(f)
        txt = str(self.remaining)
        bw = max(28, p.fontMetrics().horizontalAdvance(txt) + 14)
        bh = p.fontMetrics().height() + 4
        badge = QRectF(4 + cw / 2 + 6 - bw / 2, 4 + 9 + ch / 2 - bh / 2, bw, bh)
        p.setPen(Qt.NoPen)
        p.setBrush(GOLD)
        p.drawRoundedRect(badge, bh / 2, bh / 2)
        p.setPen(QColor("#1b1b1b"))
        p.drawText(badge, Qt.AlignCenter, txt)
        small = QFont(self.font())
        small.setPixelSize(12)
        small.setBold(True)
        p.setFont(small)
        p.setPen(QColor("#ffe7a3") if hover else QColor(220, 230, 228))
        p.drawText(QRectF(0, ch + 16, self.width(), 18), Qt.AlignHCenter | Qt.AlignVCenter,
                   tr("Cartas restantes", "Remaining cards"))

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)


# ---------------------------------------------------------------- barra de palpite

class GuessBar(QWidget):
    """Barra arrastável de palpite, na escala do cenário (pior → melhor mão possível).

    Mostra a chance média (fatia justa), um histograma de quão comum é cada chance e, depois da
    revelação, a resposta certa.
    """

    valueChanged = Signal(int)

    HIST_TOP, HIST_H = 22, 34
    TRACK_Y, TRACK_H = 60, 14

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lo, self._hi, self._fair = 0, 100, 50.0
        self._hist: list[float] = []
        self._value = 50
        self._answer: float | None = None
        self._threshold: float | None = None
        self._captions = True
        self._locked = False
        self._drag = False
        self.setFixedHeight(122)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(tr("As barrinhas claras mostram quão comum é cada chance neste cenário;\n"
                           "a linha dourada é a chance média (100% ÷ jogadores).",
                           "The light bars show how common each chance is in this scenario;\n"
                           "the gold line is the average chance (100% ÷ players)."))

    # escala
    def set_scale(self, lo: int, hi: int, fair: float, hist: list[float], captions: bool = True) -> None:
        """`captions`: rotula os extremos como pior/melhor mão possível (só quando a escala é a do cenário)."""
        self._lo, self._hi = int(lo), int(max(hi, lo + 1))
        self._fair = fair
        self._hist = hist
        self._captions = captions
        self.update()

    def set_threshold(self, pct: float | None) -> None:
        """Linha da chance mínima para pagar uma aposta (pot odds)."""
        self._threshold = pct
        self.update()

    def value(self) -> int:
        return self._value

    def setValue(self, v: float) -> None:
        v = max(self._lo, min(self._hi, int(round(v))))
        if v != self._value:
            self._value = v
            self.valueChanged.emit(v)
        self.update()

    def set_answer(self, a: float | None) -> None:
        self._answer = a
        self._locked = a is not None
        self.setCursor(Qt.ArrowCursor if self._locked else Qt.PointingHandCursor)
        self.update()

    # geometria
    def _track(self) -> QRectF:
        m = 26
        return QRectF(m, self.TRACK_Y, self.width() - 2 * m, self.TRACK_H)

    def _x(self, v: float) -> float:
        t = self._track()
        return t.left() + (v - self._lo) / (self._hi - self._lo) * t.width()

    def _x_to_value(self, x: float) -> float:
        t = self._track()
        return self._lo + (x - t.left()) / t.width() * (self._hi - self._lo)

    # interação
    def mousePressEvent(self, e) -> None:
        if self._locked or e.button() != Qt.LeftButton:
            return
        self._drag = True
        self.setValue(self._x_to_value(e.position().x()))

    def mouseMoveEvent(self, e) -> None:
        if self._drag and not self._locked:
            self.setValue(self._x_to_value(e.position().x()))

    def mouseReleaseEvent(self, _e) -> None:
        self._drag = False

    def wheelEvent(self, e) -> None:
        if not self._locked:
            self.setValue(self._value + (1 if e.angleDelta().y() > 0 else -1))

    def keyPressEvent(self, e) -> None:
        if self._locked:
            return super().keyPressEvent(e)
        step = 5 if e.modifiers() & Qt.ShiftModifier else 1
        if e.key() in (Qt.Key_Right, Qt.Key_Up):
            self.setValue(self._value + step)
        elif e.key() in (Qt.Key_Left, Qt.Key_Down):
            self.setValue(self._value - step)
        elif e.key() == Qt.Key_Home:
            self.setValue(self._lo)
        elif e.key() == Qt.Key_End:
            self.setValue(self._hi)
        else:
            super().keyPressEvent(e)

    # desenho
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._track()
        r = t.height() / 2
        lo, hi = self._lo, self._hi
        span = hi - lo

        # histograma: quão comum é cada chance
        if self._hist:
            vals = [self._hist[b] if b < len(self._hist) else 0.0 for b in range(lo, hi)]
            peak = max(vals) or 1.0
            base = self.HIST_TOP + self.HIST_H
            for b, h in zip(range(lo, hi), vals):
                if h <= 0:
                    continue
                hh = max(1.5, (h / peak) ** 0.75 * self.HIST_H)
                x0, x1 = self._x(b), self._x(b + 1)
                p.fillRect(QRectF(x0 + 0.5, base - hh, max(1.0, x1 - x0 - 1), hh), QColor(255, 255, 255, 46))

        # trilho: vermelho (pior) → amarelo (média) → verde (melhor)
        f = min(0.95, max(0.05, (self._fair - lo) / span))
        grad = QLinearGradient(t.topLeft(), t.topRight())
        grad.setColorAt(0.0, QColor("#c0392b"))
        grad.setColorAt(f, QColor("#e6b422"))
        grad.setColorAt(1.0, QColor("#27ae60"))
        track = QPainterPath()
        track.addRoundedRect(t, r, r)
        p.fillPath(track, QColor(255, 255, 255, 30))
        p.save()
        p.setClipPath(track)
        p.setOpacity(0.35)
        p.fillRect(t, QBrush(grad))
        p.setOpacity(1.0)
        gx = self._x(self._value)
        p.fillRect(QRectF(t.left(), t.top(), gx - t.left(), t.height()), QBrush(grad))
        p.restore()

        # marcas e números
        small = QFont(self.font())
        small.setPointSizeF(max(8.0, small.pointSizeF() * 0.85))
        p.setFont(small)
        step = 1 if span <= 12 else 5 if span <= 60 else 10
        label_every = step * (2 if span / step > 12 else 1)
        first = -(-lo // step) * step
        for v in range(first, hi + 1, step):
            x = self._x(v)
            major = v % label_every == 0
            p.setPen(QPen(QColor(255, 255, 255, 150 if major else 80), 1))
            p.drawLine(QPointF(x, t.bottom() + 4), QPointF(x, t.bottom() + (10 if major else 7)))
            if major and abs(x - self._x(lo)) > 30 and abs(x - self._x(hi)) > 30:
                p.setPen(QColor(255, 255, 255, 150))
                p.drawText(QRectF(x - 30, t.bottom() + 12, 60, 16), Qt.AlignCenter, f"{v}%")
        # extremos: pior e melhor mão possíveis
        bold = QFont(small)
        bold.setBold(True)
        for v, cap, align in ((lo, tr("pior mão possível", "worst possible hand"), Qt.AlignLeft),
                               (hi, tr("melhor mão possível", "best possible hand"), Qt.AlignRight)):
            x = self._x(v)
            box = QRectF(x - 4, t.bottom() + 12, 140, 16) if align == Qt.AlignLeft else QRectF(x - 136, t.bottom() + 12, 140, 16)
            p.setFont(bold)
            p.setPen(QColor("white"))
            p.drawText(box, align | Qt.AlignVCenter, f"{v}%")
            if self._captions:
                p.setFont(small)
                p.setPen(QColor(255, 255, 255, 120))
                p.drawText(box.translated(0, 15), align | Qt.AlignVCenter, cap)

        # chance mínima para pagar (pot odds)
        if self._threshold is not None:
            cyan = QColor("#5ec8ff")
            tx = self._x(max(lo, min(hi, self._threshold)))
            p.setPen(QPen(cyan, 2, Qt.DashDotLine))
            p.drawLine(QPointF(tx, self.HIST_TOP - 6), QPointF(tx, t.bottom() + 3))
            p.setFont(bold)
            p.setPen(cyan)
            label = tr(f"para pagar: {self._threshold:.0f}%", f"to call: {self._threshold:.0f}%")
            lw = p.fontMetrics().horizontalAdvance(label) + 4
            right_box = QRectF(tx + 6, 2, lw, 16)
            left_box = QRectF(tx - 6 - lw, 2, lw, 16)
            boxes = [right_box, left_box]
            if self._answer is not None:
                # não cobre o rótulo "Real: X%" (centralizado na resposta, 130 px)
                ax = self._x(max(lo, min(hi, self._answer * 100)))
                rx = min(max(ax - 65, 0), self.width() - 130)
                real = QRectF(rx, 0, 130, 18)
                boxes.sort(key=lambda b: b.intersects(real))
                if boxes[0].intersects(real):
                    boxes[0] = QRectF(tx - lw / 2, self.HIST_TOP + 2, lw, 16)
            box = boxes[0]
            box.moveLeft(max(0.0, min(box.left(), self.width() - lw)))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(12, 18, 22, 210))
            p.drawRoundedRect(box.adjusted(-4, -1, 4, 1), 6, 6)
            p.setPen(cyan)
            p.drawText(box, Qt.AlignCenter, label)

        # chance média
        fx = self._x(self._fair)
        p.setPen(QPen(GOLD, 2, Qt.DashLine))
        p.drawLine(QPointF(fx, self.HIST_TOP - 2), QPointF(fx, t.bottom() + 3))
        p.setFont(bold)
        p.setPen(GOLD)
        txt = tr(f"média {self._fair:.0f}%", f"average {self._fair:.0f}%")
        p.drawText(QRectF(fx - 60, t.bottom() + 26, 120, 16), Qt.AlignCenter, txt)

        # resposta certa
        if self._answer is not None:
            a = max(lo, min(hi, self._answer * 100))
            ax = self._x(a)
            band = QRectF(min(gx, ax), t.top() - 6, abs(ax - gx), t.height() + 12)
            p.fillRect(band, QColor(255, 255, 255, 40))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("white"))
            tri = QPainterPath()
            tri.moveTo(ax, t.top() - 2)
            tri.lineTo(ax - 8, t.top() - 14)
            tri.lineTo(ax + 8, t.top() - 14)
            tri.closeSubpath()
            p.drawPath(tri)
            p.setPen(QPen(QColor("white"), 3))
            p.drawLine(QPointF(ax, t.top() - 2), QPointF(ax, t.bottom() + 2))
            fb = QFont(self.font())
            fb.setBold(True)
            p.setFont(fb)
            tw = 130
            tx = min(max(ax - tw / 2, 0), self.width() - tw)
            p.drawText(QRectF(tx, 0, tw, 18), Qt.AlignHCenter | Qt.AlignVCenter, tr("Real", "Actual") + f": {self._answer * 100:.1f}%")

        # alça do palpite
        c = QPointF(gx, t.center().y())
        p.setPen(QPen(QColor(0, 0, 0, 80), 4))
        p.setBrush(QColor("white") if not self._locked else QColor(220, 220, 220))
        p.drawEllipse(c, 13, 13)
        p.setPen(Qt.NoPen)
        p.setBrush(GOLD if self.hasFocus() and not self._locked else QColor("#2b2f33"))
        p.drawEllipse(c, 5, 5)
