"""Histórico de mãos no formato do PokerStars (texto), para revisar o jogo em outras ferramentas.

O `Recorder` acompanha uma mão da mesa (eventos de `pokertrainer.table`) e, no fim, gera o texto. As mãos são
acrescentadas a um arquivo na pasta de dados do app; a aba de estatísticas exporta esse arquivo.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from pokertrainer import engine as E

HISTORY_FILE = "hand_history.txt"
MAX_BYTES = 5_000_000      # guarda só as mãos mais recentes


def data_dir() -> Path:
    """Pasta de dados do app (POKERTRAINER_DATA, se definida — usado nos testes)."""
    env = os.environ.get("POKERTRAINER_DATA")
    if env:
        return Path(env)
    from PySide6.QtCore import QStandardPaths
    return Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or Path.home() / ".pokertrainer")


def history_path() -> Path:
    return data_dir() / HISTORY_FILE


def _cards(cards: list[int]) -> str:
    return "[" + " ".join(E.card_str(c) for c in cards) + "]"


class Recorder:
    """Uma mão em andamento: recebe os eventos da mesa e monta as linhas no formato do PokerStars."""

    def __init__(self, t, hand_id: int, table_name: str, tournament: bool = False, level: str = "") -> None:
        self.t = t
        self.lines: list[str] = []
        self.street_bets: dict[int, int] = {}
        self.cur = 0
        self._dealt = False
        stamp = time.strftime("%Y/%m/%d %H:%M:%S")
        game = f"Hold'em No Limit ({t.sb}/{t.bb})"
        if tournament:
            game = f"Tournament, Hold'em No Limit - Level {level} ({t.sb}/{t.bb})"
        self.lines.append(f"PokerStars Hand #{hand_id}: {game} - {stamp}")
        seats = [i for i, p in enumerate(t.players) if not p.sitting_out]
        self.lines.append(f"Table '{table_name}' {len(t.players)}-max Seat #{t.dealer + 1} is the button")
        for i in seats:
            p = t.players[i]
            self.lines.append(f"Seat {i + 1}: {p.name} ({p.stack + p.total} in chips)")

    def _name(self, seat: int) -> str:
        return self.t.players[seat].name

    def feed(self, events) -> None:
        for ev in events:
            k = ev.kind
            if k == "blind":
                if ev.text == "SB":
                    self.lines.append(f"{self._name(ev.seat)}: posts small blind {ev.amount}")
                    self.street_bets[ev.seat] = ev.amount
                elif ev.text == "BB":
                    self.lines.append(f"{self._name(ev.seat)}: posts big blind {ev.amount}")
                    self.street_bets[ev.seat] = ev.amount
                    self.cur = max(self.cur, ev.amount)
                else:
                    self.lines.append(f"{self._name(ev.seat)}: posts the ante {ev.amount}")
            elif k == "action":
                self._hole_cards()
                self._action(ev)
            elif k == "street":
                self._hole_cards()
                board = ev.data["board"]
                name = {3: "FLOP", 4: "TURN", 5: "RIVER"}[len(board)]
                shown = _cards(board[:3]) if len(board) == 3 else f"{_cards(board[:-1])} {_cards(board[-1:])}"
                self.lines.append(f"*** {name} *** {shown}")
                self.street_bets, self.cur = {}, 0

    def _hole_cards(self) -> None:
        if self._dealt:
            return
        self._dealt = True
        hero = next((i for i, p in enumerate(self.t.players) if p.is_hero), None)
        self.lines.append("*** HOLE CARDS ***")
        if hero is not None and self.t.players[hero].hole:
            self.lines.append(f"Dealt to {self._name(hero)} {_cards(self.t.players[hero].hole)}")

    def _action(self, ev) -> None:
        name = self._name(ev.seat)
        a = ev.action
        before = self.street_bets.get(ev.seat, 0)
        total = ev.amount or 0
        if a == "fold":
            self.lines.append(f"{name}: folds")
        elif a == "check":
            self.lines.append(f"{name}: checks")
        elif a == "call" or (a == "allin" and total <= self.cur):
            extra = " and is all-in" if a == "allin" else ""
            self.lines.append(f"{name}: calls {total - before}{extra}")
            self.street_bets[ev.seat] = total
        elif a in ("bet", "raise", "allin"):
            extra = " and is all-in" if a == "allin" else ""
            if self.cur == 0:
                self.lines.append(f"{name}: bets {total}{extra}")
            else:
                self.lines.append(f"{name}: raises {total - self.cur} to {total}{extra}")
            self.street_bets[ev.seat] = total
            self.cur = total

    def finish(self) -> str:
        t = self.t
        self._hole_cards()
        if t.showdown_hands:
            self.lines.append("*** SHOW DOWN ***")
            for i, sc in t.showdown_hands.items():
                p = t.players[i]
                if i in t.shown or p.is_hero:
                    self.lines.append(f"{p.name}: shows {_cards(p.hole)} ({E.describe(sc)})")
                else:
                    self.lines.append(f"{p.name}: mucks hand")
        for i, amt in t.winners.items():
            self.lines.append(f"{self._name(i)} collected {amt} from pot")
        self.lines.append("*** SUMMARY ***")
        self.lines.append(f"Total pot {sum(t.winners.values())} | Rake 0")
        if t.board:
            self.lines.append(f"Board {_cards(t.board)}")
        return "\n".join(self.lines) + "\n\n\n"


def append(text: str) -> None:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(text)
    if path.stat().st_size > MAX_BYTES:   # corta as mais antigas
        data = path.read_text(encoding="utf-8")
        half = data[len(data) // 2:]
        idx = half.find("PokerStars Hand #")
        if idx >= 0:
            path.write_text(half[idx:], encoding="utf-8")


def count_hands() -> int:
    path = history_path()
    if not path.exists():
        return 0
    return path.read_text(encoding="utf-8").count("PokerStars Hand #")
