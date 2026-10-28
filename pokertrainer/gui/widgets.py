"""Componentes visuais: fundo borrado, carta animada, medidor da decisão e painel translúcido."""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import (
    Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSequentialAnimationGroup, QPauseAnimation, Qt,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
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
        self._font_px, self._color = font_px, None
        self.set_color(color)
        self.label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        h.addWidget(self.label, 0, Qt.AlignHCenter | Qt.AlignTop)
        self.setFixedHeight(self.label.fontMetrics().lineSpacing() * lines + 8)
        self.label.hide()

    def setText(self, text: str) -> None:
        self.label.setText(text)
        self.label.setVisible(bool(text.strip()))
        need = self.label.fontMetrics().horizontalAdvance(text) + 20
        if self.label.wordWrap():
            # quebra de linha só quando o texto não cabe numa linha
            self.label.setMinimumWidth(min(need, self.label.maximumWidth()))
        else:
            # linha única: largura certa para o texto (sem cortar), limitada à largura da etiqueta
            self.label.setFixedWidth(min(need, self.maximumWidth()) if self.maximumWidth() < 10000 else need)

    def text(self) -> str:
        return self.label.text()

    def set_color(self, color: str) -> None:
        """Cor do texto (ex.: verde para "passou")."""
        if color == self._color:
            return
        self._color = color
        self.label.setStyleSheet(f"QLabel {{ font-size: {self._font_px}px; color: {color}; font-weight: 600; "
                                 "background: rgba(8,12,14,0.78); border: 1px solid rgba(255,255,255,0.10); "
                                 "border-radius: 8px; padding: 2px 8px; }")

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


# ---------------------------------------------------------------- medidor da decisão

class DecisionMeter(QWidget):
    """Escala de 0 a 100% dividida nas faixas de cada jogada, com a sua chance marcada depois da decisão.

    Encarando aposta: desistir (abaixo das pot odds) · pagar · aumentar (acima do limite de valor).
    Sem aposta: passar · apostar. Antes da decisão mostra só um trilho neutro com uma legenda.
    """

    TRACK_Y, TRACK_H = 34, 16
    ZONE_COLORS = {"fold": QColor(255, 107, 107), "check": QColor(150, 170, 165), "call": QColor(245, 197, 66),
                   "bet": QColor(61, 220, 132), "raise": QColor(61, 220, 132)}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._zones: list[tuple[float, float, str, str]] = []   # (de, até, ação, rótulo)
        self._marks: list[tuple[float, str]] = []               # limites com legenda
        self._value: float | None = None
        self._best: str | None = None
        self._hint = ""
        self.setFixedHeight(92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def clear(self, hint: str = "") -> None:
        self._zones, self._marks, self._value, self._best, self._hint = [], [], None, None, hint
        self.update()

    def set_result(self, zones: list[tuple[float, float, str, str]], marks: list[tuple[float, str]],
                   value: float, best: str, caption: str | None = None) -> None:
        """Zonas e marcas em 0..1; `value` = o ponteiro (sua chance); `best` = ação da melhor jogada."""
        self._zones, self._marks, self._value, self._best, self._hint = zones, marks, value, best, ""
        self._caption = caption
        self.update()

    def _track(self) -> QRectF:
        m = 18
        return QRectF(m, self.TRACK_Y, self.width() - 2 * m, self.TRACK_H)

    def _x(self, v: float) -> float:
        t = self._track()
        return t.left() + max(0.0, min(1.0, v)) * t.width()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._track()
        r = t.height() / 2
        track = QPainterPath()
        track.addRoundedRect(t, r, r)
        p.fillPath(track, QColor(255, 255, 255, 26))
        small = QFont(self.font())
        small.setPixelSize(11)
        bold = QFont(small)
        bold.setBold(True)
        # escala
        p.setFont(small)
        for v in range(0, 101, 10):
            x = self._x(v / 100)
            p.setPen(QPen(QColor(255, 255, 255, 70), 1))
            p.drawLine(QPointF(x, t.bottom() + 3), QPointF(x, t.bottom() + 7))
            if v % 20 == 0:
                p.setPen(QColor(255, 255, 255, 110))
                p.drawText(QRectF(x - 20, t.bottom() + 8, 40, 14), Qt.AlignCenter, f"{v}%")
        if not self._zones:
            p.setPen(QColor(255, 255, 255, 120))
            p.drawText(QRectF(t.left(), 4, t.width(), 22), Qt.AlignCenter, self._hint)
            return
        # faixas de cada jogada (com 2 px de separação), rótulo dentro quando cabe
        p.save()
        p.setClipPath(track)
        for a, b, act, label in self._zones:
            x0, x1 = self._x(a), self._x(b)
            col = QColor(self.ZONE_COLORS.get(act, QColor(200, 200, 200)))
            col.setAlpha(150 if act == self._best else 70)
            p.fillRect(QRectF(x0 + 1, t.top(), max(0.0, x1 - x0 - 2), t.height()), col)
        p.restore()
        p.setFont(bold)
        for a, b, act, label in self._zones:
            x0, x1 = self._x(a), self._x(b)
            if x1 - x0 > p.fontMetrics().horizontalAdvance(label) + 10:
                p.setPen(QColor(15, 20, 22) if act == self._best else QColor(255, 255, 255, 200))
                p.drawText(QRectF(x0, t.top(), x1 - x0, t.height()), Qt.AlignCenter, label)
        # limites (pot odds / valor)
        p.setFont(small)
        for v, label in self._marks:
            x = self._x(v)
            p.setPen(QPen(QColor(255, 255, 255, 170), 1, Qt.DashLine))
            p.drawLine(QPointF(x, t.top() - 4), QPointF(x, t.bottom() + 4))
            w = p.fontMetrics().horizontalAdvance(label) + 8
            box = QRectF(min(max(x - w / 2, 0), self.width() - w), t.bottom() + 22, w, 14)
            p.setPen(QColor(255, 255, 255, 190))
            p.drawText(box, Qt.AlignCenter, label)
        # sua chance
        if self._value is not None:
            x = self._x(self._value)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("white"))
            tri = QPainterPath()
            tri.moveTo(x, t.top() - 1)
            tri.lineTo(x - 7, t.top() - 11)
            tri.lineTo(x + 7, t.top() - 11)
            tri.closeSubpath()
            p.drawPath(tri)
            p.setPen(QPen(QColor("white"), 3))
            p.drawLine(QPointF(x, t.top() - 1), QPointF(x, t.bottom() + 1))
            fb = QFont(self.font())
            fb.setPixelSize(13)
            fb.setBold(True)
            p.setFont(fb)
            txt = getattr(self, "_caption", None) or tr(f"Sua chance: {self._value * 100:.0f}%",
                                                         f"Your chance: {self._value * 100:.0f}%")
            w = p.fontMetrics().horizontalAdvance(txt) + 12
            p.drawText(QRectF(min(max(x - w / 2, 0), self.width() - w), 2, w, 18), Qt.AlignCenter, txt)
