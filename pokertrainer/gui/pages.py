"""Páginas de conteúdo: início, tabela de probabilidades, dicas e configurações."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
    QMessageBox, QTextBrowser, QToolTip, QVBoxLayout, QWidget,
)

from pokertrainer import ai
from pokertrainer import coach
from pokertrainer import engine as E
from pokertrainer import settings as S
from pokertrainer.i18n import pick, tr
from pokertrainer.gui.play_page import speed_names as play_speeds
from pokertrainer.gui.widgets import CardWidget, Glass


def close_button(on_close) -> QPushButton:
    """Botão "Fechar" no canto das páginas de apoio: volta para onde você estava (Esc também)."""
    b = QPushButton(tr("✕  Fechar", "✕  Close"))
    b.setObjectName("chip")
    b.setCursor(Qt.PointingHandCursor)
    b.setToolTip(tr("Voltar (Esc)", "Go back (Esc)"))
    b.clicked.connect(on_close)
    return b


def _page_shell(title: str, subtitle: str = "", on_close=None) -> tuple[QWidget, QVBoxLayout]:
    """Página com painel translúcido; devolve (página, layout interno). `on_close` põe um botão Fechar no título."""
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(24, 20, 24, 20)
    panel = Glass(alpha=180)
    outer.addWidget(panel)
    v = QVBoxLayout(panel)
    v.setContentsMargins(28, 22, 28, 22)
    v.setSpacing(10)
    head = QHBoxLayout()
    t = QLabel(title)
    t.setObjectName("pageTitle")
    head.addWidget(t)
    head.addStretch(1)
    if on_close is not None:
        page.close_btn = close_button(on_close)
        head.addWidget(page.close_btn, 0, Qt.AlignTop)
    v.addLayout(head)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("muted")
        s.setWordWrap(True)
        v.addWidget(s)
    return page, v


# ---------------------------------------------------------------- início

class HomePage(QWidget):
    """Tela inicial: o que o app faz; os modos ficam no menu lateral."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(40, 20, 40, 40)
        v.addStretch(1)
        t = QLabel(tr("Bem-vindo ao Pro Poker Trainer", "Welcome to Pro Poker Trainer"))
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet("font-size: 34px; font-weight: 800; color: white;")
        v.addWidget(t)
        s = QLabel(tr("Pratique contra bots fortes que se adaptam ao seu estilo de jogo, ou treine mãos individuais "
                      "com a matemática por trás de cada decisão. Escolha um modo no menu à esquerda.",
                      "Practice against strong bots that adapt to your playing style, or train individual hands "
                      "with the math behind every decision. Pick a mode in the menu on the left."))
        s.setAlignment(Qt.AlignCenter)
        s.setWordWrap(True)
        s.setObjectName("muted")
        s.setStyleSheet("font-size: 15px;")
        s.setMaximumWidth(640)
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(s)
        h.addStretch(1)
        v.addLayout(h)
        v.addStretch(1)


# ---------------------------------------------------------------- grade 13x13

class HandGrid(QWidget):
    """Grade das 169 mãos iniciais colorida pela equidade."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.n_opp = 1
        self.marked: str | None = None
        self.setMouseTracking(True)
        self.setMinimumSize(420, 420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_opponents(self, n: int) -> None:
        self.n_opp = n
        self.update()

    def set_marked(self, label: str | None) -> None:
        self.marked = label
        self.update()

    def _geom(self) -> tuple[float, float, float]:
        side = min(self.width(), self.height()) - 2
        cell = side / 13
        x0 = (self.width() - side) / 2
        return x0, 1, cell

    @staticmethod
    def label_at(i: int, j: int) -> str:
        a, b = E.RANK_CHARS[12 - i], E.RANK_CHARS[12 - j]
        if i == j:
            return a + b
        return (a + b + "s") if i < j else (b + a + "o")

    def _color(self, eq: float) -> QColor:
        fair = 1 / (self.n_opp + 1)
        rel = eq / fair
        if rel >= 1:
            t = min(1.0, (rel - 1) / 1.2)
            c0, c1 = QColor("#3b4a45"), QColor("#1fa463")
        else:
            t = min(1.0, (1 - rel) / 0.6)
            c0, c1 = QColor("#3b4a45"), QColor("#c0392b")
        return QColor(int(c0.red() + (c1.red() - c0.red()) * t), int(c0.green() + (c1.green() - c0.green()) * t),
                      int(c0.blue() + (c1.blue() - c0.blue()) * t))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        table = coach.preflop_table()
        x0, y0, cell = self._geom()
        f = QFont(self.font())
        f.setPixelSize(max(9, int(cell * 0.27)))
        f.setBold(True)
        small = QFont(self.font())
        small.setPixelSize(max(8, int(cell * 0.21)))
        for i in range(13):
            for j in range(13):
                lab = self.label_at(i, j)
                r = QRectF(x0 + j * cell + 1, y0 + i * cell + 1, cell - 2, cell - 2)
                eq = table[self.n_opp].get(lab) if table else None
                p.setPen(Qt.NoPen)
                p.setBrush(self._color(eq) if eq is not None else QColor("#333"))
                p.drawRoundedRect(r, 4, 4)
                if lab == self.marked:
                    p.setPen(QPen(QColor("#f5c542"), 3))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 4, 4)
                p.setPen(QColor("white"))
                p.setFont(f)
                p.drawText(r.adjusted(0, 2, 0, -cell * 0.38), Qt.AlignHCenter | Qt.AlignBottom, lab)
                if eq is not None:
                    p.setFont(small)
                    p.setPen(QColor(255, 255, 255, 200))
                    p.drawText(r.adjusted(0, cell * 0.55, 0, -2), Qt.AlignHCenter | Qt.AlignTop, f"{eq * 100:.0f}")

    def mouseMoveEvent(self, e) -> None:
        x0, y0, cell = self._geom()
        j = int((e.position().x() - x0) // cell)
        i = int((e.position().y() - y0) // cell)
        table = coach.preflop_table()
        if 0 <= i < 13 and 0 <= j < 13 and table:
            lab = self.label_at(i, j)
            eq = table[self.n_opp][lab]
            rank = coach.preflop_rank(lab, self.n_opp)
            kind = (tr("par", "pair") if i == j else
                    tr("mesmo naipe", "suited") if i < j else tr("naipes diferentes", "offsuit"))
            combos = 6 if i == j else (4 if i < j else 12)
            QToolTip.showText(e.globalPosition().toPoint(), tr(
                f"<b>{lab}</b> ({kind}, {combos} combinações)<br>"
                f"Equidade: <b>{eq * 100:.1f}%</b> contra {self.n_opp} oponente(s)<br>"
                f"Posição: {rank}ª de 169",
                f"<b>{lab}</b> ({kind}, {combos} combos)<br>"
                f"Equity: <b>{eq * 100:.1f}%</b> against {self.n_opp} opponent(s)<br>"
                f"Rank: #{rank} of 169"), self)
        else:
            QToolTip.hideText()


def _table(headers: list[str], rows: list[list[str]], stretch_first: bool = True) -> QTableWidget:
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionMode(QAbstractItemView.NoSelection)
    t.setFocusPolicy(Qt.NoFocus)
    t.setShowGrid(False)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            it = QTableWidgetItem(val)
            it.setTextAlignment(Qt.AlignVCenter | (Qt.AlignLeft if c == 0 else Qt.AlignCenter))
            t.setItem(r, c, it)
    hh = t.horizontalHeader()
    for c in range(len(headers)):
        hh.setSectionResizeMode(c, QHeaderView.Stretch if (c == 0 and stretch_first) else
                                QHeaderView.ResizeToContents)
    t.verticalHeader().setDefaultSectionSize(30)
    return t


class TablePage(QWidget):
    closeRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        page, v = _page_shell(tr("Tabela de probabilidades", "Probability charts"), on_close=self.closeRequested.emit)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page)
        tabs = QTabWidget()
        tabs.addTab(self._preflop_tab(), tr("Mãos iniciais", "Starting hands"))
        tabs.addTab(self._outs_tab(), "Outs")
        tabs.addTab(self._ranking_tab(), tr("Ranking de mãos", "Hand rankings"))
        v.addWidget(tabs, 1)

    def _preflop_tab(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 12, 0, 0)
        self.grid = HandGrid()
        h.addWidget(self.grid, 3)
        side = QVBoxLayout()
        side.setSpacing(8)
        lbl = QLabel(tr("Oponentes", "Opponents"))
        lbl.setObjectName("section")
        side.addWidget(lbl)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.opp_group = QButtonGroup(self)
        for n in range(1, 10):
            b = QPushButton(str(n))
            b.setCheckable(True)
            b.setFixedWidth(34)
            b.setStyleSheet("text-align: center; padding: 6px 0;")
            b.setChecked(n == 1)
            self.opp_group.addButton(b, n)
            row.addWidget(b)
        row.addStretch(1)
        self.opp_group.idClicked.connect(self.grid.set_opponents)
        side.addLayout(row)
        info = QLabel(tr(
            "Cada célula mostra a <b>chance (%) de vencer até o river</b> contra oponentes com cartas aleatórias, "
            "antes do flop.<br><br>"
            "• <b>Diagonal</b>: pares (AA, KK…)<br>"
            "• <b>Acima</b> da diagonal: mesmo naipe (s)<br>"
            "• <b>Abaixo</b>: naipes diferentes (o)<br><br>"
            "<span style='color:#1fa463'>Verde</span> = acima da fatia justa (100% ÷ jogadores); "
            "<span style='color:#e0675b'>vermelho</span> = abaixo.<br><br>"
            "Passe o mouse para ver detalhes. A mão atual do jogo aparece com borda dourada.",
            "Each cell shows the <b>chance (%) of winning by the river</b> against opponents with random cards, "
            "before the flop.<br><br>"
            "• <b>Diagonal</b>: pairs (AA, KK…)<br>"
            "• <b>Above</b> the diagonal: suited (s)<br>"
            "• <b>Below</b>: offsuit (o)<br><br>"
            "<span style='color:#1fa463'>Green</span> = above the fair share (100% ÷ players); "
            "<span style='color:#e0675b'>red</span> = below.<br><br>"
            "Hover for details. The current hand in the game has a gold border."))
        info.setWordWrap(True)
        info.setObjectName("muted")
        side.addWidget(info)
        if coach.preflop_table() is None:
            warn = QLabel(tr("Tabela não encontrada.", "Table not found.") + " " + tr("Gere com:", "Build it with:") + "<br><code>uv run python tools/build_preflop_table.py</code>")
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #ff8a80;")
            side.addWidget(warn)
        side.addStretch(1)
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(270)
        h.addWidget(sw)
        return w

    def set_opponents(self, n: int) -> None:
        b = self.opp_group.button(n)
        if b:
            b.setChecked(True)
        self.grid.set_opponents(n)

    def _outs_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        intro = QLabel(tr("<b>Outs</b> são as cartas que ainda faltam sair e que melhoram sua mão. "
                          "Atalho: no flop, multiplique os outs por <b>4</b> (duas cartas a vir); no turn, por "
                          "<b>2</b> (uma carta). A tabela mostra os valores exatos.",
                          "<b>Outs</b> are the unseen cards that improve your hand. "
                          "Shortcut: on the flop, multiply the outs by <b>4</b> (two cards to come); on the turn, "
                          "by <b>2</b> (one card). The table shows the exact values."))
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        v.addWidget(intro)
        h = QHBoxLayout()
        rows = []
        for o in range(1, 21):
            rows.append([f"{o}", f"{coach.hit_chance(o, 47, 1) * 100:.1f}%", f"{coach.hit_chance(o, 46, 1) * 100:.1f}%",
                         f"{coach.hit_chance(o, 47, 2) * 100:.1f}%", f"{o * 4}%"])
        h.addWidget(_table(["Outs", "Flop→Turn", "Turn→River", "Flop→River", tr("Regra do 4", "Rule of 4")], rows,
                           stretch_first=False), 3)
        draws = [[name, str(o), f"{coach.hit_chance(o, 47, 2) * 100:.0f}%", f"{coach.hit_chance(o, 46, 1) * 100:.0f}%"]
                 for name, o in coach.common_draws()]
        right = QVBoxLayout()
        lbl = QLabel(tr("Projetos comuns", "Common draws"))
        lbl.setObjectName("section")
        right.addWidget(lbl)
        right.addWidget(_table([tr("Situação", "Situation"), "Outs", tr("do flop", "from flop"), tr("do turn", "from turn")], draws), 1)
        h.addLayout(right, 4)
        v.addLayout(h, 1)
        return w

    def _ranking_tab(self) -> QWidget:
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 12, 8, 0)
        v.setSpacing(6)
        intro = QLabel(tr("Da mais forte para a mais fraca. A coluna da direita é a chance de terminar com essa "
                          "mão usando 7 cartas (2 suas + 5 da mesa).",
                          "From strongest to weakest. The right column is the chance of ending up with that hand "
                          "using 7 cards (your 2 + 5 on the board)."))
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        v.addWidget(intro)
        for cat in range(8, -1, -1):
            row = QFrame()
            row.setObjectName("card")
            h = QHBoxLayout(row)
            h.setContentsMargins(12, 6, 12, 6)
            num = QLabel(f"{9 - cat}")
            num.setStyleSheet("font-size: 20px; font-weight: 800; color: #f5c542;")
            num.setFixedWidth(26)
            h.addWidget(num)
            tv = QVBoxLayout()
            tv.setSpacing(0)
            name = QLabel(E.category_name(cat))
            name.setStyleSheet("font-size: 16px; font-weight: 800;")
            desc = QLabel(coach.category_help(cat))
            desc.setObjectName("muted")
            desc.setWordWrap(True)
            tv.addWidget(name)
            tv.addWidget(desc)
            h.addLayout(tv, 1)
            for c in coach.CATEGORY_EXAMPLE[cat].split():
                cw = CardWidget()
                cw.set_card(E.card(c), True)
                cw.set_card_height(64)
                h.addWidget(cw)
            h.addSpacing(12)
            pct = QLabel(f"{coach.CATEGORY_ODDS_7[cat] * 100:.2f}%" if cat >= 7 else
                         f"{coach.CATEGORY_ODDS_7[cat] * 100:.1f}%")
            pct.setStyleSheet("font-size: 16px; font-weight: 700;")
            pct.setFixedWidth(70)
            pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            h.addWidget(pct)
            v.addWidget(row)
        v.addStretch(1)
        sc.setWidget(inner)
        return sc


# ---------------------------------------------------------------- dicas

TIPS_CSS = """
<style>
h3 { color: #f5c542; margin-top: 18px; margin-bottom: 4px; }
p, li { color: #dfe8e5; line-height: 150%; }
.k { color: #ffffff; font-weight: bold; }
</style>
"""

TIPS_HTML_PT = """
<h3>1. Decida em três passos</h3>
<ol>
<li><span class='k'>Estime sua chance</span> (equidade) contra as <span class='k'>mãos com que o oponente jogaria
assim</span>: ninguém aumenta ou aposta com qualquer mão. Antes do flop, a posição define a faixa (do UTG ~14% das mãos,
do botão ~40%).</li>
<li><span class='k'>Compare com o preço</span> (pot odds): se alguém apostou, pagar só vale se sua chance for maior
que o preço.</li>
<li><span class='k'>Veja se é forte o bastante para apostar</span>: mãos bem acima da média ganham mais apostando ou
aumentando do que só passando ou pagando.</li>
</ol>

<h3>2. Pot odds: o preço de pagar</h3>
<p>Preço = <span class='k'>aposta ÷ pote final</span> (o pote depois que você paga). Contra 1 oponente:</p>
<ul>
<li>Aposta de ⅓ do pote → precisa de <span class='k'>20%</span> · ½ pote → <span class='k'>25%</span> ·
⅔ do pote → <span class='k'>29%</span> · pote inteiro → <span class='k'>33%</span>.</li>
<li>Quando outros jogadores já pagaram, o pote final cresce e o preço cai — mas há mais mãos para vencer.</li>
<li>O valor esperado de pagar é <span class='k'>chance × pote final − aposta</span>. Desistir vale zero.</li>
</ul>

<h3>3. Aposta por valor</h3>
<p>Aposte (ou aumente) por valor quando estiver <span class='k'>à frente das mãos que pagam</span> — mais de 50% contra
elas. Não basta estar à frente da faixa inteira: quem paga uma aposta costuma ter mão melhor do que quem desiste. Com
mão muito forte, aposte grande (⅔ do pote ou mais); com valor fino (par alto), ⅓ a ⅔ do pote.</p>

<h3>4. Semiblefe</h3>
<p>No flop e no turn, projetos fortes (<span class='k'>8 ou mais outs</span>, como flush draw ou sequência aberta)
podem apostar mesmo sem mão feita: às vezes ganham o pote na hora e, se pagarem, ainda podem completar.</p>

<h3>5. Passar não custa nada</h3>
<p>Se ninguém apostou, nunca desista: passar é de graça e você vê a próxima carta.</p>

<h3>6. Referências pré-flop (contra 1 oponente)</h3>
<ul>
<li><span class='k'>AA</span> ≈ 85% · <span class='k'>KK</span> ≈ 82% · <span class='k'>QQ</span> ≈ 80% · <span class='k'>JJ</span> ≈ 77%</li>
<li><span class='k'>AKs</span> ≈ 67% · <span class='k'>AKo</span> ≈ 65% · <span class='k'>AQo</span> ≈ 64%</li>
<li><span class='k'>22</span> ≈ 50% — até o menor par é levemente favorito contra uma mão aleatória.</li>
<li>Pior mão: <span class='k'>32o</span> ≈ 32%. Mesmo naipe acrescenta só ~2–4 pontos; cartas conectadas, ~1–2.</li>
</ul>

<h3>7. Mais oponentes, menos chance</h3>
<p>AA cai de ~85% (1 oponente) para ~73% (2), ~64% (3) e ~56% (4). Mãos especulativas (pares baixos, conectores do
mesmo naipe) perdem menos valor relativo, porque quando acertam costumam ganhar potes grandes.</p>

<h3>8. Depois do flop: conte os outs</h3>
<ul>
<li>No <span class='k'>flop</span> (2 cartas a vir): outs × 4 ≈ % de acertar até o river.</li>
<li>No <span class='k'>turn</span> (1 carta a vir): outs × 2 ≈ % de acertar no river.</li>
<li>Flush draw = 9 outs (~35% do flop) · sequência aberta = 8 (~31%) · gutshot = 4 (~16%).</li>
</ul>

<h3>9. Leia a textura da mesa</h3>
<ul>
<li>3 cartas do mesmo naipe na mesa: flush possível — mãos como trinca valem menos.</li>
<li>Mesa com par: full house aparece; seu flush ou sequência fica menos seguro.</li>
<li>Com o mesmo par, o kicker desempata: A-K num flop com Ás domina A-7.</li>
</ul>

<h3>10. Resultado ≠ decisão</h3>
<p>Uma mão de 80% perde 1 em cada 5 vezes. Uma boa decisão é a que ganha mais <i>em média</i>: julgue suas jogadas
pela nota ao longo de muitas mãos, não pelo resultado de uma.</p>

<h3>Atalhos de teclado</h3>
<ul>
<li><span class='k'>F</span> desistir · <span class='k'>C</span> passar/pagar · <span class='k'>R</span>
apostar/aumentar · <span class='k'>Enter</span> ou <span class='k'>S</span> próxima mão.</li>
<li>No cash game e no torneio: <span class='k'>P</span> pausa; <span class='k'>S</span> pula o resto da jogada dos bots
quando você já desistiu.</li>
</ul>
"""

TIPS_HTML_EN = """
<h3>1. Decide in three steps</h3>
<ol>
<li><span class='k'>Estimate your chance</span> (equity) against the <span class='k'>hands your opponent would play
this way</span>: nobody raises or bets with any two cards. Pre-flop, position sets the range (~14% of hands from UTG,
~40% from the button).</li>
<li><span class='k'>Compare it with the price</span> (pot odds): if someone bet, calling only pays off when your
chance is higher than the price.</li>
<li><span class='k'>Check whether it's strong enough to bet</span>: hands well above average win more by betting or
raising than by just checking or calling.</li>
</ol>

<h3>2. Pot odds: the price of calling</h3>
<p>Price = <span class='k'>bet ÷ final pot</span> (the pot after you call). Heads-up:</p>
<ul>
<li>A ⅓-pot bet → you need <span class='k'>20%</span> · ½ pot → <span class='k'>25%</span> ·
⅔ pot → <span class='k'>29%</span> · full pot → <span class='k'>33%</span>.</li>
<li>When other players have already called, the final pot grows and the price drops — but there are more hands
to beat.</li>
<li>The expected value of calling is <span class='k'>chance × final pot − bet</span>. Folding is worth zero.</li>
</ul>

<h3>3. Value betting</h3>
<p>Bet (or raise) for value when you're <span class='k'>ahead of the hands that call</span> — more than 50% against
them. Being ahead of the whole range isn't enough: whoever calls a bet usually has a better hand than whoever folds.
With a very strong hand, bet big (⅔ pot or more); with thin value (top pair), ⅓ to ⅔ pot.</p>

<h3>4. Semi-bluffing</h3>
<p>On the flop and turn, strong draws (<span class='k'>8 or more outs</span>, like a flush draw or an open-ended
straight draw) can bet without a made hand: sometimes they win the pot right away, and if called they can still
hit.</p>

<h3>5. Checking is free</h3>
<p>If nobody bet, never fold: checking costs nothing and you see the next card.</p>

<h3>6. Pre-flop benchmarks (heads-up)</h3>
<ul>
<li><span class='k'>AA</span> ≈ 85% · <span class='k'>KK</span> ≈ 82% · <span class='k'>QQ</span> ≈ 80% · <span class='k'>JJ</span> ≈ 77%</li>
<li><span class='k'>AKs</span> ≈ 67% · <span class='k'>AKo</span> ≈ 65% · <span class='k'>AQo</span> ≈ 64%</li>
<li><span class='k'>22</span> ≈ 50% — even the smallest pair is a slight favorite against a random hand.</li>
<li>Worst hand: <span class='k'>32o</span> ≈ 32%. Being suited adds only ~2–4 points; connected cards, ~1–2.</li>
</ul>

<h3>7. More opponents, less chance</h3>
<p>AA drops from ~85% (1 opponent) to ~73% (2), ~64% (3) and ~56% (4). Speculative hands (small pairs, suited
connectors) lose less relative value, because when they hit they tend to win big pots.</p>

<h3>8. After the flop: count your outs</h3>
<ul>
<li>On the <span class='k'>flop</span> (2 cards to come): outs × 4 ≈ % to hit by the river.</li>
<li>On the <span class='k'>turn</span> (1 card to come): outs × 2 ≈ % to hit on the river.</li>
<li>Flush draw = 9 outs (~35% from the flop) · open-ended straight = 8 (~31%) · gutshot = 4 (~16%).</li>
</ul>

<h3>9. Read the board texture</h3>
<ul>
<li>3 cards of one suit on the board: a flush is possible — hands like trips are worth less.</li>
<li>Paired board: full houses show up; your flush or straight is less safe.</li>
<li>With the same pair, the kicker breaks the tie: A-K on an Ace-high flop dominates A-7.</li>
</ul>

<h3>10. Result ≠ decision</h3>
<p>An 80% hand loses 1 time in 5. A good decision is the one that wins more <i>on average</i>: judge your plays by
your score over many hands, not by the result of one.</p>

<h3>Keyboard shortcuts</h3>
<ul>
<li><span class='k'>F</span> fold · <span class='k'>C</span> check/call · <span class='k'>R</span> bet/raise ·
<span class='k'>Enter</span> or <span class='k'>S</span> next hand.</li>
<li>In cash games and tournaments: <span class='k'>P</span> pause; <span class='k'>S</span> skips the rest of the bots'
play once you've folded.</li>
</ul>
"""


class TipsPage(QWidget):
    closeRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        page, v = _page_shell(tr("Dicas", "Tips"),
                              tr("Como decidir entre desistir, pagar e aumentar — sem calculadora.",
                                 "How to choose between folding, calling and raising — without a calculator."),
                              on_close=self.closeRequested.emit)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setHtml(TIPS_CSS + pick(TIPS_HTML_PT, TIPS_HTML_EN))
        v.addWidget(tb, 1)


# ---------------------------------------------------------------- configurações

class SettingsPage(QWidget):
    statsReset = Signal()
    closeRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        page, v = _page_shell(tr("Configurações", "Settings"),
                              tr("As mudanças valem a partir da próxima mão.", "Changes apply from the next hand on."),
                              on_close=self.closeRequested.emit)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page)

        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignRight)

        def section(text: str, first: bool = False) -> None:
            if not first:
                spacer = QWidget()
                spacer.setFixedHeight(8)
                form.addRow(spacer)
            sec = QLabel(text.upper())
            sec.setObjectName("section")
            form.addRow(sec)

        # treino
        section(tr("Treino de decisões", "Decision training"), first=True)
        self.opp = QSpinBox()
        self.opp.setRange(1, 9)
        self.opp.setValue(S.get("opponents"))
        self.opp.valueChanged.connect(lambda x: S.put("opponents", x))
        form.addRow(tr("Oponentes na mão", "Opponents in the hand"), self.opp)
        self.rand = QCheckBox(tr(f"Aleatório: sortear de 1 a {S.MAX_OPPONENTS} a cada mão",
                                 f"Random: draw 1 to {S.MAX_OPPONENTS} every hand"))
        self.rand.setChecked(S.get("random_opponents"))
        self.rand.toggled.connect(self._random_toggled)
        self.opp.setEnabled(not self.rand.isChecked())
        form.addRow("", self.rand)
        self.range = QComboBox()
        for pct in coach.RANGES:
            self.range.addItem(coach.range_name(pct), pct)
        self.range.setCurrentIndex(max(0, self.range.findData(S.get("opp_range"))))
        self.range.currentIndexChanged.connect(lambda i: S.put("opp_range", self.range.itemData(i)))
        form.addRow(tr("Mãos dos oponentes", "Opponents' hands"), self.range)
        self.prec = QComboBox()
        precisions = S.precisions()
        for name, n in precisions:
            self.prec.addItem(name, n)
        cur = S.get("iterations")
        self.prec.setCurrentIndex(next((i for i, (_, n) in enumerate(precisions) if n == cur), 1))
        self.prec.currentIndexChanged.connect(lambda i: S.put("iterations", self.prec.itemData(i)))
        form.addRow(tr("Precisão do cálculo", "Calculation precision"), self.prec)
        self.name = QCheckBox(tr("Mostrar o nome da mão atual (ex.: “Par de Ases”)",
                                 "Show the current hand's name (e.g. “Pair of Aces”)"))
        self.name.setChecked(S.get("show_hand_name"))
        self.name.toggled.connect(lambda x: S.put("show_hand_name", x))
        form.addRow("", self.name)

        # jogo
        section(tr("Cash game e torneio", "Cash game and tournament"))
        self.diff = QComboBox()
        for k in ai.DIFFICULTIES:
            self.diff.addItem(ai.difficulty_name(k), k)
        self.diff.setCurrentIndex(max(0, self.diff.findData(S.get("difficulty"))))
        self.diff_help = QLabel()
        self.diff_help.setObjectName("muted")
        self.diff_help.setWordWrap(True)
        self.diff_help.setStyleSheet("font-size: 12px;")
        self.diff.currentIndexChanged.connect(self._diff_changed)
        self._diff_changed(self.diff.currentIndex(), save=False)
        diff_box = QWidget()
        dl = QVBoxLayout(diff_box)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(6)
        dl.addWidget(self.diff)
        dl.addWidget(self.diff_help)
        form.addRow(tr("Dificuldade dos bots", "Bot difficulty"), diff_box)
        self.play_opp = QSpinBox()
        self.play_opp.setRange(1, S.MAX_OPPONENTS)
        self.play_opp.setValue(S.get("play_opponents"))
        self.play_opp.valueChanged.connect(lambda x: S.put("play_opponents", x))
        form.addRow(tr("Oponentes na mesa", "Opponents at the table"), self.play_opp)
        self.speed = QComboBox()
        for name, key in play_speeds():
            self.speed.addItem(name, key)
        self.speed.setCurrentIndex(max(0, self.speed.findData(S.get("play_speed"))))
        self.speed.currentIndexChanged.connect(lambda i: S.put("play_speed", self.speed.itemData(i)))
        form.addRow(tr("Velocidade dos bots", "Bot speed"), self.speed)
        self.pers = QCheckBox(tr("Mostrar a personalidade e o humor dos bots (modo aprendizado)",
                                 "Show the bots' personality and mood (learning mode)"))
        self.pers.setChecked(S.get("show_personality"))
        self.pers.toggled.connect(lambda x: S.put("show_personality", x))
        form.addRow("", self.pers)
        self.assist = QCheckBox(tr("Assistente: mostrar minha chance de vencer na minha vez",
                                   "Assistant: show my chance of winning on my turn"))
        self.assist.setChecked(S.get("play_assist"))
        self.assist.toggled.connect(lambda x: S.put("play_assist", x))
        form.addRow("", self.assist)
        self.mucked = QCheckBox(tr("Mostrar as cartas de quem descartou no showdown (aprendizado)",
                                   "Show the cards of players who mucked at showdown (learning)"))
        self.mucked.setToolTip(tr("Numa mesa real, quem perde no showdown pode descartar a mão sem mostrar.",
                                  "At a real table, a player who loses at showdown can muck without showing."))
        self.mucked.setChecked(S.get("show_mucked"))
        self.mucked.toggled.connect(lambda x: S.put("show_mucked", x))
        form.addRow("", self.mucked)
        self.show_bb = QCheckBox(tr("Mostrar valores em big blinds (bb) na mesa",
                                    "Show amounts in big blinds (bb) at the table"))
        self.show_bb.setChecked(S.get("show_bb"))
        self.show_bb.toggled.connect(lambda x: S.put("show_bb", x))
        form.addRow("", self.show_bb)

        # aparência e som
        section(tr("Aparência e som", "Look and sound"))
        self.anim = QCheckBox(tr("Animar cartas", "Animate cards"))
        self.anim.setChecked(S.get("animations"))
        self.anim.toggled.connect(lambda x: S.put("animations", x))
        form.addRow("", self.anim)
        self.snd = QCheckBox(tr("Sons (fichas, cartas, sua vez)", "Sounds (chips, cards, your turn)"))
        self.snd.setChecked(S.get("sounds"))
        self.snd.toggled.connect(lambda x: S.put("sounds", x))
        form.addRow("", self.snd)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(S.get("volume"))
        self.vol.setMinimumWidth(220)
        self.vol.sliderReleased.connect(self._vol_done)
        form.addRow(tr("Volume", "Volume"), self.vol)

        # dados
        section(tr("Dados", "Data"))
        reset = QPushButton(tr("Zerar estatísticas", "Reset statistics"))
        reset.setObjectName("danger")
        reset.setCursor(Qt.PointingHandCursor)
        reset.setToolTip(tr("Apaga as estatísticas e o histórico do treino e do jogo.",
                            "Erases the training and game statistics and history."))
        reset.clicked.connect(self._reset)
        form.addRow(tr("Estatísticas", "Statistics"), reset)
        self.reset_info = QLabel("")
        self.reset_info.setObjectName("muted")
        form.addRow("", self.reset_info)

        v.addSpacing(8)
        form_box = QWidget()
        form_box.setLayout(form)
        form_box.setMaximumWidth(720)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 12, 0)
        hl.addWidget(form_box)
        hl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(holder)
        v.addWidget(scroll, 1)
        credits = QLabel(tr(
            "Créditos: cartas de <i>playing-cards-assets</i> (Howard Yeh, licença MIT); "
            "foto de fundo “World Poker Tour table 3” (World Poker Tour, Wikimedia Commons, CC BY 3.0).",
            "Credits: cards from <i>playing-cards-assets</i> (Howard Yeh, MIT license); "
            "background photo “World Poker Tour table 3” (World Poker Tour, Wikimedia Commons, CC BY 3.0)."))
        credits.setWordWrap(True)
        credits.setStyleSheet("color: #7f948e; font-size: 11px;")
        v.addWidget(credits)

    def _vol_done(self) -> None:
        S.put("volume", self.vol.value())
        from pokertrainer.gui import sound
        sound.play("bet")

    def _diff_changed(self, i: int, save: bool = True) -> None:
        key = self.diff.itemData(i)
        if save:
            S.put("difficulty", key)
        n = ai.tournament_rounds(key)
        self.diff_help.setText(tr(*ai.DIFFICULTY_HELP[key]) + " " +
                               tr(f"Torneio: {n} rodadas. Vale a partir da próxima partida.",
                                  f"Tournament: {n} rounds. Applies from the next game."))

    def _random_toggled(self, on: bool) -> None:
        S.put("random_opponents", on)
        self.opp.setEnabled(not on)

    def refresh(self) -> None:
        """Relê valores que também mudam fora desta página (botões da mesa)."""
        self.play_opp.blockSignals(True)
        self.play_opp.setValue(S.get("play_opponents"))
        self.play_opp.blockSignals(False)
        self.snd.blockSignals(True)
        self.snd.setChecked(S.get("sounds"))
        self.snd.blockSignals(False)
        self.speed.blockSignals(True)
        self.speed.setCurrentIndex(max(0, self.speed.findData(S.get("play_speed"))))
        self.speed.blockSignals(False)
        for w, val in ((self.opp, S.get("opponents")), (self.rand, S.get("random_opponents"))):
            w.blockSignals(True)
            w.setValue(val) if w is self.opp else w.setChecked(val)
            w.blockSignals(False)
        self.opp.setEnabled(not self.rand.isChecked())
        self.range.blockSignals(True)
        self.range.setCurrentIndex(max(0, self.range.findData(S.get("opp_range"))))
        self.range.blockSignals(False)
        self.show_bb.blockSignals(True)
        self.show_bb.setChecked(S.get("show_bb"))
        self.show_bb.blockSignals(False)

    def _reset(self) -> None:
        ans = QMessageBox.question(self, tr("Zerar estatísticas", "Reset statistics"),
                                   tr("Apagar todas as estatísticas e o histórico? Isso não pode ser desfeito.",
                                      "Erase all statistics and history? This can't be undone."))
        if ans != QMessageBox.Yes:
            return
        S.reset_stats()
        self.reset_info.setText(tr("Estatísticas zeradas.", "Statistics reset."))
        self.statsReset.emit()
