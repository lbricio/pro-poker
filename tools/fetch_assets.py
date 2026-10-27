"""Baixa as imagens usadas pelo app e gera as PNGs das cartas em alta resolução.

Uso:  uv run python tools/fetch_assets.py

- Cartas: SVGs de https://github.com/hayeah/playing-cards-assets (licença MIT),
  renderizadas aqui para PNG (as PNGs do repositório são pequenas demais).
- Verso da carta: desenhado aqui mesmo (PNG).
- Fundo: "World Poker Tour table 3" (Wikimedia Commons, CC BY 3.0, World Poker Tour).
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parent.parent / "pokertrainer" / "assets"
CARDS = ASSETS / "cards"
CARD_REPO = "https://raw.githubusercontent.com/hayeah/playing-cards-assets/master/svg-cards"
BG_URL = "https://upload.wikimedia.org/wikipedia/commons/5/51/World_Poker_Tour_table_3.jpg"
UA = {"User-Agent": "pokertrainer/0.1 (asset fetcher)"}

RANKS = {"2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8", "9": "9", "10": "T",
         "jack": "J", "queen": "Q", "king": "K", "ace": "A"}
SUITS = ["clubs", "diamonds", "hearts", "spades"]
WIDTH = 480  # px; altura segue a proporção da carta (~1.45)


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read()


def render_svg(svg: bytes, out: Path) -> None:
    rend = QSvgRenderer(QByteArray(svg))
    size = rend.defaultSize()
    h = round(WIDTH * size.height() / size.width())
    img = QImage(WIDTH, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    rend.render(p, QRectF(0, 0, WIDTH, h))
    p.end()
    img.save(str(out), "PNG")


def draw_back(out: Path, w: int = WIDTH, h: int = 697) -> None:
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r = w * 0.06
    outer = QPainterPath()
    outer.addRoundedRect(QRectF(1, 1, w - 2, h - 2), r, r)
    p.fillPath(outer, QColor("#fbfbf8"))
    p.setPen(QPen(QColor("#888"), 2))
    p.drawPath(outer)
    m = w * 0.07
    inner_rect = QRectF(m, m, w - 2 * m, h - 2 * m)
    inner = QPainterPath()
    inner.addRoundedRect(inner_rect, r * 0.6, r * 0.6)
    g = QLinearGradient(inner_rect.topLeft(), inner_rect.bottomRight())
    g.setColorAt(0, QColor("#8e1b1b"))
    g.setColorAt(1, QColor("#5a0d0d"))
    p.fillPath(inner, QBrush(g))
    p.save()
    p.setClipPath(inner)
    p.setPen(QPen(QColor(255, 255, 255, 55), 3))
    step = w / 12
    i = -h
    while i < w + h:
        p.drawLine(QPointF(i, 0), QPointF(i + h, h))
        p.drawLine(QPointF(i + h, 0), QPointF(i, h))
        i += step
    p.restore()
    p.setPen(QPen(QColor(255, 255, 255, 200), 4))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(inner_rect.adjusted(10, 10, -10, -10), r * 0.4, r * 0.4)
    # losango central
    c = inner_rect.center()
    d = w * 0.18
    dia = QPainterPath()
    dia.moveTo(c.x(), c.y() - d * 1.3)
    dia.lineTo(c.x() + d, c.y())
    dia.lineTo(c.x(), c.y() + d * 1.3)
    dia.lineTo(c.x() - d, c.y())
    dia.closeSubpath()
    p.fillPath(dia, QColor("#f3e6c4"))
    p.setPen(QPen(QColor("#5a0d0d"), 3))
    p.drawPath(dia)
    p.end()
    img.save(str(out), "PNG")


def main() -> int:
    QGuiApplication(sys.argv)
    CARDS.mkdir(parents=True, exist_ok=True)
    for rname, r in RANKS.items():
        for s in SUITS:
            out = CARDS / f"{r}{s[0]}.png"
            print("carta", out.name)
            render_svg(fetch(f"{CARD_REPO}/{rname}_of_{s}.svg"), out)
    draw_back(CARDS / "back.png")
    print("fundo da mesa")
    (ASSETS / "table_bg.jpg").write_bytes(fetch(BG_URL))
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
