"""Preferências e estatísticas persistentes (QSettings)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import QSettings

from pokertrainer.i18n import tr

DEFAULTS = {
    "opponents": 1,
    "random_opponents": False,
    "opp_range": 100,
    "difficulty": "medium",
    "play_opponents": 5,
    "play_speed": "normal",
    "show_personality": False,
    "play_assist": False,
    "sounds": True,
    "volume": 70,
    "play_autonext": False,
    "language": "pt",
    "iterations": 50000,
    "tolerance": 5,
    "blur": 26,
    "show_hand_name": True,
    "animations": True,
}

MAX_OPPONENTS = 9


def precisions() -> list[tuple[str, int]]:
    return [(tr("Rápida (10 mil simulações)", "Fast (10k simulations)"), 10000),
            (tr("Normal (50 mil simulações)", "Normal (50k simulations)"), 50000),
            (tr("Alta (150 mil simulações)", "High (150k simulations)"), 150000)]


@dataclass(frozen=True)
class Mode:
    key: str
    visible: int  # cartas visíveis na mesa (-1 = sorteia flop ou turn a cada mão; -2 = cash game; -3 = torneio)
    _title: tuple[str, str]
    _subtitle: tuple[str, str]

    @property
    def title(self) -> str:
        return tr(*self._title)

    @property
    def subtitle(self) -> str:
        return tr(*self._subtitle)

    @property
    def is_play(self) -> bool:
        """Modo de jogo (mesa contra bots), não de treino de probabilidades."""
        return self.visible <= -2


MODES = [
    Mode("preflop", 0, ("Pré-flop", "Pre-flop"), ("Só as 2 cartas da mão", "Just your 2 hole cards")),
    Mode("flop", 3, ("Flop", "Flop"), ("2 cartas + 3 na mesa", "2 cards + 3 on the board")),
    Mode("turn", 4, ("Turn", "Turn"), ("2 cartas + 4 na mesa", "2 cards + 4 on the board")),
    Mode("potodds", -1, ("Pot odds", "Pot odds"), ("Pagar ou desistir?", "Call or fold?")),
    Mode("play", -2, ("Cash game", "Cash game"),
         ("Recompra à vontade", "Rebuy anytime")),
    Mode("tournament", -3, ("Torneio", "Tournament"),
         ("Rodadas até a mesa final", "Rounds to the final table")),
]
MODE_BY_KEY = {m.key: m for m in MODES}


def app_settings() -> QSettings:
    return QSettings("pokertrainer", "pokertrainer")


def get(key: str):
    default = DEFAULTS[key]
    v = app_settings().value(key, default)
    if isinstance(default, bool):
        return v in (True, "true", "1", 1)
    return type(default)(v)


def put(key: str, value) -> None:
    app_settings().setValue(key, value)


@dataclass
class Stats:
    rounds: int = 0
    hits: int = 0
    total_error: float = 0.0
    points: int = 0
    streak: int = 0
    best_streak: int = 0
    decisions: int = 0
    good_decisions: int = 0
    ev: float = 0.0

    @property
    def avg_error(self) -> float:
        return self.total_error / self.rounds if self.rounds else 0.0

    @property
    def hit_rate(self) -> float:
        return self.hits / self.rounds if self.rounds else 0.0


def load_stats(mode: str) -> Stats:
    s = app_settings()
    s.beginGroup(f"stats/{mode}")
    st = Stats(int(s.value("rounds", 0)), int(s.value("hits", 0)), float(s.value("total_error", 0.0)),
               int(s.value("points", 0)), int(s.value("streak", 0)), int(s.value("best_streak", 0)),
               int(s.value("decisions", 0)), int(s.value("good_decisions", 0)), float(s.value("ev", 0.0)))
    s.endGroup()
    return st


def save_stats(mode: str, st: Stats) -> None:
    s = app_settings()
    s.beginGroup(f"stats/{mode}")
    for k, v in st.__dict__.items():
        s.setValue(k, v)
    s.endGroup()


def reset_stats() -> None:
    s = app_settings()
    s.remove("stats")
    s.remove("history")
    s.remove("play")
    s.remove("play_curve")


# ---------------------------------------------------------------- histórico de mãos (para revisão e gráficos)

HISTORY_MAX = 500


def load_history() -> list[dict]:
    raw = app_settings().value("history", "")
    try:
        data = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def append_history(entry: dict) -> None:
    h = load_history()
    h.append(entry)
    app_settings().setValue("history", json.dumps(h[-HISTORY_MAX:], separators=(",", ":")))


# ---------------------------------------------------------------- jogo simulado: totais acumulados entre partidas

PLAY_INT = ("hands", "vpip", "pfr", "bets_raises", "calls", "faced_bets", "folds_to_bet", "saw_flop", "showdowns",
            "showdown_wins", "threebets", "threebet_opp", "cbets", "cbet_opp", "won_hands", "decisions",
            "good_decisions", "net", "biggest_win", "sessions", "tournaments", "tourn_wins", "best_place")
PLAY_FLOAT = ("net_bb",)
CURVE_MAX = 2000


def load_play_stats() -> dict:
    s = app_settings()
    s.beginGroup("play")
    d = {k: int(s.value(k, 0)) for k in PLAY_INT}
    d.update({k: float(s.value(k, 0.0)) for k in PLAY_FLOAT})
    s.endGroup()
    return d


def save_play_stats(d: dict) -> None:
    s = app_settings()
    s.beginGroup("play")
    for k in PLAY_INT + PLAY_FLOAT:
        s.setValue(k, d.get(k, 0))
    s.endGroup()


def add_play_totals(delta: dict, net_bb: float = 0.0) -> None:
    """Soma contadores aos totais (biggest_win e best_place guardam o recorde)."""
    d = load_play_stats()
    for k, v in delta.items():
        if k == "biggest_win":
            d[k] = max(d.get(k, 0), v)
        elif k == "best_place":
            d[k] = v if not d.get(k) else min(d[k], v)
        else:
            d[k] = d.get(k, 0) + v
    d["net_bb"] = d.get("net_bb", 0.0) + net_bb
    save_play_stats(d)


def add_play_hand(delta: dict, net_bb: float) -> None:
    """Uma mão jogada: soma aos totais e guarda o resultado em big blinds para o gráfico."""
    add_play_totals(delta, net_bb)
    curve = load_play_curve()
    curve.append(round(net_bb, 2))
    app_settings().setValue("play_curve", json.dumps(curve[-CURVE_MAX:], separators=(",", ":")))


def load_play_curve() -> list[float]:
    raw = app_settings().value("play_curve", "")
    try:
        data = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []
