"""Preferências e estatísticas persistentes (QSettings)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import QSettings

from pokertrainer.i18n import tr

DEFAULTS = {
    "opponents": 1,
    "random_opponents": False,
    "opp_range": 0,          # faixa dos oponentes no treino: 0 = conforme a ação; senão top X% fixo
    "difficulty": "medium",
    "play_opponents": 5,
    "play_speed": "normal",
    "show_personality": False,
    "play_assist": False,
    "sounds": True,
    "volume": 70,
    "play_autonext": False,
    "play_sidebar": True,     # menu lateral visível na mesa (cash game e torneio)
    "play_log": True,         # histórico visível na mesa
    "show_bb": False,         # valores da mesa em big blinds
    "show_mucked": False,     # mostrar as cartas de quem descartou no showdown (aprendizado)
    "language": "pt",
    "iterations": 50000,
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
    visible: int  # cartas visíveis na mesa no treino (0, 3, 4, 5); -2 = cash game; -3 = torneio
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
        """Modo de jogo (mesa contra bots), não de treino de decisões."""
        return self.visible <= -2


MODES = [
    Mode("preflop", 0, ("Pré-flop", "Pre-flop"), ("Só as suas 2 cartas", "Just your 2 hole cards")),
    Mode("flop", 3, ("Flop", "Flop"), ("3 cartas na mesa", "3 cards on the board")),
    Mode("turn", 4, ("Turn", "Turn"), ("4 cartas na mesa", "4 cards on the board")),
    Mode("river", 5, ("River", "River"), ("Mesa completa", "Full board")),
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
    """Totais do treino de decisões num modo."""
    hands: int = 0
    best: int = 0          # melhor jogada
    good: int = 0          # melhor jogada ou aceitável
    points: int = 0
    streak: int = 0        # decisões seguidas sem erro
    best_streak: int = 0
    ev: float = 0.0        # fichas ganhas/perdidas em média nas decisões de pagar ou desistir

    @property
    def best_rate(self) -> float:
        return self.best / self.hands if self.hands else 0.0

    @property
    def good_rate(self) -> float:
        return self.good / self.hands if self.hands else 0.0


def load_stats(mode: str) -> Stats:
    s = app_settings()
    s.beginGroup(f"train/{mode}")
    st = Stats()
    for k, v in st.__dict__.items():
        setattr(st, k, type(v)(s.value(k, v)))
    s.endGroup()
    return st


def save_stats(mode: str, st: Stats) -> None:
    s = app_settings()
    s.beginGroup(f"train/{mode}")
    for k, v in st.__dict__.items():
        s.setValue(k, v)
    s.endGroup()


def reset_stats() -> None:
    s = app_settings()
    for k in ("stats", "history", "train", "decisions", "tourn"):   # "stats"/"history": versões antigas
        s.remove(k)
    s.remove("play")
    s.remove("play_curve")


# ---------------------------------------------------------------- histórico de mãos (para revisão e gráficos)

HISTORY_MAX = 500


def load_history() -> list[dict]:
    raw = app_settings().value("decisions", "")
    try:
        data = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def append_history(entry: dict) -> None:
    h = load_history()
    h.append(entry)
    app_settings().setValue("decisions", json.dumps(h[-HISTORY_MAX:], separators=(",", ":")))


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


# ---------------------------------------------------------------- torneio: resultados por dificuldade

def load_tourn_stats(difficulty: str) -> dict:
    """{"played", "wins", "best"} do torneio numa dificuldade (best = melhor colocação, 0 = nenhuma)."""
    s = app_settings()
    s.beginGroup(f"tourn/{difficulty}")
    d = {k: int(s.value(k, 0)) for k in ("played", "wins", "best")}
    s.endGroup()
    return d


def add_tourn_result(difficulty: str, played: int = 0, place: int = 0) -> None:
    """Soma um torneio começado (`played`) e/ou a colocação final (`place`; 1 = título)."""
    d = load_tourn_stats(difficulty)
    d["played"] += played
    if place:
        d["wins"] += place == 1
        d["best"] = place if not d["best"] else min(d["best"], place)
    s = app_settings()
    s.beginGroup(f"tourn/{difficulty}")
    for k, v in d.items():
        s.setValue(k, v)
    s.endGroup()
