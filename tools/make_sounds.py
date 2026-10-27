"""Gera os sons genéricos de poker (WAV 44,1 kHz, mono, 16 bits) em pokertrainer/assets/sounds/.

Tudo é sintetizado aqui (sem arquivos de terceiros): fichas batendo, cartas deslizando, batida na mesa etc.
Uso:  uv run python tools/make_sounds.py
"""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "pokertrainer" / "assets" / "sounds"
rng = random.Random(42)


def silence(sec: float) -> list[float]:
    return [0.0] * int(SR * sec)


def mix(dst: list[float], src: list[float], at: float, gain: float = 1.0) -> None:
    i0 = int(at * SR)
    need = i0 + len(src)
    if need > len(dst):
        dst.extend([0.0] * (need - len(dst)))
    for k, v in enumerate(src):
        dst[i0 + k] += v * gain


def lowpass(x: list[float], cutoff: float) -> list[float]:
    a = 1 - math.exp(-2 * math.pi * cutoff / SR)
    y, prev = [], 0.0
    for v in x:
        prev += a * (v - prev)
        y.append(prev)
    return y


def highpass(x: list[float], cutoff: float) -> list[float]:
    low = lowpass(x, cutoff)
    return [a - b for a, b in zip(x, low)]


def clack(bright: float = 1.0) -> list[float]:
    """Uma ficha batendo em outra: estalo curto + ressonâncias agudas que somem rápido."""
    n = int(0.09 * SR)
    freqs = [rng.uniform(2300, 2700) * bright, rng.uniform(3600, 4200) * bright, rng.uniform(5200, 6200) * bright]
    decays = [0.020, 0.014, 0.009]
    out = []
    for i in range(n):
        t = i / SR
        v = sum(math.sin(2 * math.pi * f * t) * math.exp(-t / d) for f, d in zip(freqs, decays)) / 3
        if i < SR * 0.003:
            v += rng.uniform(-1, 1) * (1 - i / (SR * 0.003))
        out.append(v)
    return out


def noise_burst(sec: float, attack: float, cutoff_start: float, cutoff_end: float, hp: float = 300) -> list[float]:
    """Ruído filtrado com o filtro "abrindo/fechando" (deslize de carta, swish)."""
    n = int(sec * SR)
    out, prev = [], 0.0
    for i in range(n):
        t = i / SR
        cut = cutoff_start + (cutoff_end - cutoff_start) * (i / n)
        a = 1 - math.exp(-2 * math.pi * cut / SR)
        prev += a * (rng.uniform(-1, 1) - prev)
        env = min(1.0, t / attack) * (1 - i / n) ** 1.6
        out.append(prev * env)
    return highpass(out, hp)


def knock() -> list[float]:
    """Batida com os dedos na mesa (passar)."""
    n = int(0.12 * SR)
    out = []
    for i in range(n):
        t = i / SR
        v = (math.sin(2 * math.pi * 150 * t) * 0.8 + math.sin(2 * math.pi * 310 * t) * 0.4) * math.exp(-t / 0.025)
        if i < SR * 0.004:
            v += rng.uniform(-1, 1) * 0.5 * (1 - i / (SR * 0.004))
        out.append(v)
    return lowpass(out, 2500)


def tone(freqs: list[float], sec: float, decay: float, attack: float = 0.005) -> list[float]:
    n = int(sec * SR)
    out = []
    for i in range(n):
        t = i / SR
        v = sum(math.sin(2 * math.pi * f * t) / (k + 1) for k, f in enumerate(freqs))
        out.append(v * min(1.0, t / attack) * math.exp(-t / decay))
    return out


def cascade(count: int, span: float, start: float = 0.0, gain: float = 1.0) -> list[float]:
    out = silence(span + 0.15)
    for k in range(count):
        at = start + span * (k / max(1, count - 1)) ** 1.3 + rng.uniform(-0.01, 0.01)
        mix(out, clack(rng.uniform(0.9, 1.1)), max(0.0, at), gain * rng.uniform(0.5, 1.0))
    return out


def normalize(x: list[float], peak: float) -> list[float]:
    m = max(1e-9, max(abs(v) for v in x))
    fade = int(0.004 * SR)
    y = [v / m * peak for v in x]
    for i in range(min(fade, len(y))):
        y[-1 - i] *= i / fade
    return y


def save(name: str, x: list[float], peak: float = 0.8) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    y = normalize(x, peak)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v)) * 32767)) for v in y))
    print(f"  {name}.wav  ({len(y) / SR:.2f}s)")


def main() -> None:
    print("gerando sons em", OUT)
    save("chip", clack(), 0.55)
    bet = silence(0.25)
    for k in range(3):
        mix(bet, clack(rng.uniform(0.92, 1.08)), 0.045 * k, rng.uniform(0.6, 1.0))
    save("bet", bet, 0.7)
    call = silence(0.2)
    for k in range(2):
        mix(call, clack(rng.uniform(0.95, 1.05)), 0.05 * k, 0.8)
    save("call", call, 0.6)
    save("allin", cascade(16, 0.55), 0.85)
    chk = silence(0.25)
    mix(chk, knock(), 0.0)
    mix(chk, knock(), 0.11, 0.8)
    save("check", chk, 0.75)
    save("fold", noise_burst(0.22, 0.015, 5000, 1200, hp=600), 0.45)
    save("deal", noise_burst(0.12, 0.004, 7000, 2500, hp=1500), 0.5)
    flip = noise_burst(0.07, 0.002, 8000, 3000, hp=2000)
    mix(flip, lowpass([rng.uniform(-1, 1) * math.exp(-i / (SR * 0.006)) for i in range(int(0.03 * SR))], 1800),
        0.045, 0.6)
    save("flip", flip, 0.5)
    collect = noise_burst(0.35, 0.02, 3000, 1500, hp=400)
    mix(collect, cascade(6, 0.25, 0.05, 0.5), 0.0)
    save("collect", collect, 0.6)
    win = cascade(10, 0.45)
    mix(win, tone([1047, 2094], 0.6, 0.25), 0.05, 0.5)
    mix(win, tone([1319, 2638], 0.7, 0.3), 0.18, 0.55)
    save("win", win, 0.75)
    save("turn", tone([880, 1760, 2640], 0.5, 0.18, attack=0.01), 0.45)


if __name__ == "__main__":
    main()
