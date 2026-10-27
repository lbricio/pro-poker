"""Sons do jogo, tocados pelo reprodutor do sistema (afplay no macOS; paplay/aplay no Linux).

Não depende do QtMultimedia (que não vem no PySide6-Essentials). Fica mudo nos testes (QT_QPA_PLATFORM=offscreen)
ou com POKERTRAINER_MUTE=1. Os arquivos são gerados por tools/make_sounds.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

from pokertrainer import settings as S
from pokertrainer.gui.widgets import ASSETS

SOUNDS = ASSETS / "sounds"
MAX_PLAYING = 5


class _Player:
    def __init__(self) -> None:
        self.cmd = None
        if sys.platform == "darwin" and shutil.which("afplay"):
            self.cmd = "afplay"
        elif shutil.which("paplay"):
            self.cmd = "paplay"
        elif shutil.which("aplay"):
            self.cmd = "aplay"
        self.procs: list[subprocess.Popen] = []
        self._last: dict[str, float] = {}
        self.played: list[str] = []   # para testes/diagnóstico

    @property
    def muted(self) -> bool:
        return (os.environ.get("QT_QPA_PLATFORM") == "offscreen" or os.environ.get("POKERTRAINER_MUTE") == "1"
                or not S.get("sounds"))

    def play(self, name: str, min_gap: float = 0.05) -> None:
        self.played.append(name)
        self.played = self.played[-50:]
        if self.muted or self.cmd is None:
            return
        path = SOUNDS / f"{name}.wav"
        if not path.exists():
            return
        now = time.monotonic()
        if now - self._last.get(name, 0.0) < min_gap:   # evita "metralhadora" do mesmo som
            return
        self._last[name] = now
        self.procs = [p for p in self.procs if p.poll() is None]
        if len(self.procs) >= MAX_PLAYING:
            return
        vol = max(0.0, min(1.0, S.get("volume") / 100))
        if self.cmd == "afplay":
            args = ["afplay", "-v", f"{vol:.2f}", str(path)]
        elif self.cmd == "paplay":
            args = ["paplay", f"--volume={int(65536 * vol)}", str(path)]
        else:
            args = ["aplay", "-q", str(path)]
        try:
            self.procs.append(subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        except OSError:
            self.cmd = None


player = _Player()


def play(name: str) -> None:
    player.play(name)
