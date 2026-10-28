"""Lobby do torneio: escolha da dificuldade, com rodadas, tamanho do torneio e os seus resultados em cada uma."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from pokertrainer import ai
from pokertrainer import settings as S
from pokertrainer.i18n import tr
from pokertrainer.gui.widgets import Glass

LEVEL_ICONS = {"easy": "♣", "medium": "♦", "hard": "♥", "semipro": "♠", "pro": "👑"}


def _summary(key: str) -> str:
    """Primeira frase da descrição da dificuldade."""
    text = tr(*ai.DIFFICULTY_HELP[key])
    return text.split(". ")[0].rstrip(".") + "."


class LevelCard(QPushButton):
    def __init__(self, key: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("tileButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(180, 196)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(4)
        head = QHBoxLayout()
        icon = QLabel(LEVEL_ICONS.get(key, "♠"))
        icon.setStyleSheet("font-size: 20px; color: #f5c542; background: transparent;")
        name = QLabel(ai.difficulty_name(key))
        name.setStyleSheet("font-size: 19px; font-weight: 800; background: transparent;")
        head.addWidget(icon)
        head.addSpacing(4)
        head.addWidget(name)
        head.addStretch(1)
        self.trophies = QLabel()
        self.trophies.setStyleSheet("font-size: 15px; font-weight: 800; color: #f5c542; background: transparent;")
        head.addWidget(self.trophies)
        v.addLayout(head)
        self.rounds = QLabel()
        self.rounds.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffe7a3; background: transparent;")
        v.addWidget(self.rounds)
        desc = QLabel(_summary(key))
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 12px; color: #9fb3ad; background: transparent;")
        v.addWidget(desc)
        v.addStretch(1)
        self.record = QLabel()
        self.record.setWordWrap(True)
        self.record.setStyleSheet("font-size: 12px; color: #dfe8e5; background: transparent;")
        v.addWidget(self.record)
        for w in (icon, name, self.trophies, self.rounds, desc, self.record):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setToolTip(tr(*ai.DIFFICULTY_HELP[key]))

    def refresh(self, table_size: int) -> None:
        n = ai.tournament_rounds(self.key)
        field = table_size * 2 ** (n - 1)
        self.rounds.setText(tr(f"{n} rodadas · {field} jogadores", f"{n} rounds · {field} players"))
        st = S.load_tourn_stats(self.key)
        self.trophies.setText(f"🏆 {st['wins']}" if st["wins"] else "")
        if not st["played"]:
            self.record.setText(tr("Ainda não jogado", "Not played yet"))
            return
        wins = st["wins"]
        titles = tr(f"{wins} título{'s' if wins != 1 else ''}", f"{wins} title{'s' if wins != 1 else ''}")
        played = tr(f"{st['played']} torneio{'s' if st['played'] != 1 else ''}",
                    f"{st['played']} tournament{'s' if st['played'] != 1 else ''}")
        best = tr(f" · melhor: {st['best']}º", f" · best: #{st['best']}") if st["best"] else ""
        self.record.setText(f"<b>{titles}</b> · {played}{best}")


class TournamentPage(QWidget):
    difficultyChosen = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        panel = Glass(alpha=180)
        outer.addWidget(panel)
        v = QVBoxLayout(panel)
        v.setContentsMargins(28, 22, 28, 22)
        v.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel(tr("🏆  Torneio", "🏆  Tournament"))
        title.setObjectName("pageTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.total = QLabel()
        self.total.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffe7a3;")
        head.addWidget(self.total)
        v.addLayout(head)
        sub = QLabel(tr("Escolha a dificuldade. Todos começam com 1000 fichas e os blinds sobem a cada 15 mãos (com "
                        "ante do big blind). Quando metade da mesa cai, quem sobrou passa de rodada levando as fichas "
                        "para uma mesa nova. Na mesa final só há um campeão.",
                        "Pick a difficulty. Everyone starts with 1000 chips and the blinds go up every 15 hands (with "
                        "a big blind ante). Once half the table is out, the survivors advance with their chips to a "
                        "new table. The final table has a single champion."))
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        v.addWidget(sub)
        self.table_info = QLabel()
        self.table_info.setObjectName("muted")
        self.table_info.setStyleSheet("font-size: 12px;")
        v.addWidget(self.table_info)
        v.addSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(14)
        self.cards: dict[str, LevelCard] = {}
        for i, key in enumerate(ai.DIFFICULTIES):
            c = LevelCard(key)
            c.clicked.connect(lambda _=False, k=key: self.difficultyChosen.emit(k))
            self.cards[key] = c
            grid.addWidget(c, i // 3, i % 3)
        v.addLayout(grid)
        v.addStretch(1)

    def refresh(self) -> None:
        size = max(1, min(S.MAX_OPPONENTS, S.get("play_opponents"))) + 1
        self.table_info.setText(tr(f"Mesas de {size} jogadores (você + {size - 1} bots) — mude no 👥 da mesa ou em "
                                   "Configurações.",
                                   f"Tables of {size} players (you + {size - 1} bots) — change it with 👥 at the "
                                   "table or in Settings."))
        wins = played = 0
        for c in self.cards.values():
            c.refresh(size)
            st = S.load_tourn_stats(c.key)
            wins += st["wins"]
            played += st["played"]
        self.total.setText(tr(f"🏆 {wins} título{'s' if wins != 1 else ''} em {played} torneio"
                              f"{'s' if played != 1 else ''}",
                              f"🏆 {wins} title{'s' if wins != 1 else ''} in {played} tournament"
                              f"{'s' if played != 1 else ''}") if played else "")
