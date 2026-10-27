"""Perfil de jogador (HUD): estatísticas, faixas de referência e estilo de jogo.

Funciona com os contadores de `table.Player` (partida atual) ou com os totais acumulados em settings.
As faixas de referência são as usuais de um jogador sólido em mesas de 6 a 9 jogadores.
"""

from __future__ import annotations

from dataclasses import dataclass

from pokertrainer import ai
from pokertrainer.i18n import tr

COUNTERS = ("hands", "vpip", "pfr", "bets_raises", "calls", "faced_bets", "folds_to_bet", "saw_flop", "showdowns",
            "showdown_wins", "threebets", "threebet_opp", "cbets", "cbet_opp")
MIN_HANDS = 15          # abaixo disso o estilo ainda não é confiável


def counters_of(p) -> dict[str, int]:
    return {k: int(getattr(p, k, 0)) for k in COUNTERS}


def _ratio(a: float, b: float) -> float | None:
    return a / b if b else None


@dataclass
class Stat:
    key: str
    value: float | None      # fração (0..1) ou razão (AF)
    sample: int              # tamanho da amostra (oportunidades)
    lo: float                # faixa de referência
    hi: float
    is_ratio: bool = False   # AF não é porcentagem

    @property
    def name(self) -> str:
        return tr(*STAT_NAMES[self.key][0])

    @property
    def short(self) -> str:
        return tr(*SHORT_NAMES.get(self.key, (self.key, self.key)))

    @property
    def help(self) -> str:
        return tr(*STAT_NAMES[self.key][1])

    def fmt(self) -> str:
        if self.value is None:
            return "–"
        return f"{self.value:.1f}" if self.is_ratio else f"{self.value:.0%}"

    def ref(self) -> str:
        return f"{self.lo:.1f}–{self.hi:.1f}" if self.is_ratio else f"{self.lo:.0%}–{self.hi:.0%}"

    def verdict(self) -> tuple[str, str]:
        """(texto, cor) comparando com a faixa de referência."""
        if self.value is None or self.sample < 5:
            return tr("poucos dados", "not enough data"), "#9fb3ad"
        lo_txt, hi_txt = STAT_NAMES[self.key][2]
        if self.value < self.lo:
            return tr(*lo_txt), "#f5c542"
        if self.value > self.hi:
            return tr(*hi_txt), "#ff8a80"
        return tr("na faixa", "in range"), "#3ddc84"


SHORT_NAMES = {"vpip": ("VPIP", "VPIP"), "pfr": ("PFR", "PFR"), "threebet": ("3-bet", "3-bet"), "af": ("AF", "AF"),
               "cbet": ("C-bet", "C-bet"), "fold_to_bet": ("Desiste p/ aposta", "Fold to bet"),
               "wtsd": ("WTSD", "WTSD"), "wsd": ("W$SD", "W$SD")}

STAT_NAMES = {
    "vpip": (("VPIP", "VPIP"),
             ("Mãos em que você pôs fichas por vontade antes do flop (pagou ou aumentou).",
              "Hands where you voluntarily put chips in before the flop (called or raised)."),
             (("seletivo demais", "too tight"), ("solto demais", "too loose"))),
    "pfr": (("PFR", "PFR"),
            ("Mãos em que você aumentou antes do flop.", "Hands where you raised before the flop."),
            (("aumenta pouco", "raises too little"), ("aumenta demais", "raises too much"))),
    "threebet": (("3-bet", "3-bet"),
                 ("Re-aumentos diante de um aumento antes do flop.", "Re-raises when facing a pre-flop raise."),
                 (("3-bet raro", "rarely 3-bets"), ("3-bet demais", "3-bets too much"))),
    "af": (("AF (agressividade)", "AF (aggression)"),
           ("Apostas + aumentos ÷ pagamentos. Abaixo de 1 = passivo.", "Bets + raises ÷ calls. Below 1 = passive."),
           (("passivo", "passive"), ("agressivo demais", "too aggressive"))),
    "cbet": (("C-bet", "C-bet"),
             ("Aposta no flop depois de ter aumentado antes do flop.",
              "Betting the flop after raising before the flop."),
             (("c-bet raro", "rarely c-bets"), ("c-bet demais", "c-bets too much"))),
    "fold_to_bet": (("Desiste diante de aposta", "Fold to bet"),
                    ("Quantas vezes você desiste quando alguém aposta.", "How often you fold when someone bets."),
                    (("paga demais", "calls too much"), ("desiste demais", "folds too much"))),
    "wtsd": (("WTSD (vai ao showdown)", "WTSD (went to showdown)"),
             ("Das mãos em que viu o flop, quantas foram até o showdown.",
              "Of the hands where you saw the flop, how many went to showdown."),
             (("larga cedo demais", "gives up too early"), ("vai longe demais", "goes too far"))),
    "wsd": (("W$SD (ganha no showdown)", "W$SD (won at showdown)"),
            ("Dos showdowns, quantos você ganhou. Baixo = paga com mãos fracas.",
             "Of the showdowns, how many you won. Low = calling with weak hands."),
            (("perde muitos showdowns", "loses many showdowns"), ("ótimo", "great"))),
}


def stats(c: dict[str, int]) -> list[Stat]:
    hands = c.get("hands", 0)
    return [
        Stat("vpip", _ratio(c["vpip"], hands), hands, 0.18, 0.30),
        Stat("pfr", _ratio(c["pfr"], hands), hands, 0.13, 0.24),
        Stat("threebet", _ratio(c["threebets"], c["threebet_opp"]), c["threebet_opp"], 0.05, 0.12),
        Stat("af", _ratio(c["bets_raises"], c["calls"]) if c["calls"] else (float(c["bets_raises"]) or None),
             c["bets_raises"] + c["calls"], 1.8, 4.0, is_ratio=True),
        Stat("cbet", _ratio(c["cbets"], c["cbet_opp"]), c["cbet_opp"], 0.50, 0.80),
        Stat("fold_to_bet", _ratio(c["folds_to_bet"], c["faced_bets"]), c["faced_bets"], 0.35, 0.60),
        Stat("wtsd", _ratio(c["showdowns"], c["saw_flop"]), c["saw_flop"], 0.22, 0.35),
        Stat("wsd", _ratio(c["showdown_wins"], c["showdowns"]), c["showdowns"], 0.48, 0.65),
    ]


def style(c: dict[str, int]) -> str | None:
    """Arquétipo mais próximo do jogo observado (mesmas categorias dos bots) ou None com poucos dados."""
    hands = c.get("hands", 0)
    if hands < MIN_HANDS:
        return None
    vpip = c["vpip"] / hands
    pfr = c["pfr"] / hands
    af = c["bets_raises"] / c["calls"] if c["calls"] else 5.0
    aggressive = af >= 1.6 and pfr >= 0.55 * vpip
    if vpip >= 0.45:
        return "maniac" if af >= 2.5 else "station" if af < 1.0 else "lag" if aggressive else "fish"
    if vpip >= 0.30:
        return "lag" if aggressive else "station" if af < 0.9 else "fish"
    if vpip <= 0.15:
        return "rock"
    return "tag" if aggressive else "reg"


def style_text(c: dict[str, int]) -> str:
    st = style(c)
    if st is None:
        left = MIN_HANDS - c.get("hands", 0)
        return tr(f"estilo: jogue mais {left} mão(s) para estimar", f"style: play {left} more hand(s) to estimate")
    return tr("estilo: ", "style: ") + ai.archetype_name(st)


def short_hud(c: dict[str, int]) -> str:
    """Linha curta para a mesa: VPIP / PFR / AF."""
    if not c.get("hands"):
        return ""
    s = {x.key: x for x in stats(c)}
    return f"VPIP {s['vpip'].fmt()} · PFR {s['pfr'].fmt()} · AF {s['af'].fmt()}"


def tooltip(c: dict[str, int], title: str) -> str:
    lines = [f"<b>{title}</b>", tr(f"{c.get('hands', 0)} mãos", f"{c.get('hands', 0)} hands")]
    for st in stats(c):
        verdict, color = st.verdict()
        lines.append(f"{st.name}: <b>{st.fmt()}</b> <span style='color:#9fb3ad'>({tr('ref.', 'ref.')} {st.ref()})"
                     f"</span> <span style='color:{color}'>{verdict}</span>")
    lines.append("<br>" + style_text(c))
    return "<br>".join(lines)


def advice(c: dict[str, int]) -> list[str]:
    """Até 3 sugestões a partir das estatísticas fora da faixa."""
    tips = {
        ("vpip", "hi"): ("Jogue menos mãos: largue as fracas fora de posição.",
                         "Play fewer hands: drop weak ones out of position."),
        ("vpip", "lo"): ("Abra um pouco mais o jogo, principalmente no botão e no cutoff.",
                         "Open up a bit, especially on the button and cutoff."),
        ("pfr", "lo"): ("Quando entrar numa mão, prefira aumentar a só pagar.",
                        "When you enter a pot, prefer raising over just calling."),
        ("af", "lo"): ("Você paga muito e aposta pouco: aposte suas mãos boas para ganhar mais.",
                       "You call a lot and bet little: bet your good hands to win more."),
        ("af", "hi"): ("Agressividade alta demais vira previsível: selecione melhor os blefes.",
                       "Too much aggression becomes predictable: pick your bluffs better."),
        ("fold_to_bet", "hi"): ("Você desiste demais diante de apostas: bots agressivos vão blefar contra você.",
                                "You fold too much to bets: aggressive bots will bluff you."),
        ("fold_to_bet", "lo"): ("Você paga demais: use as pot odds antes de pagar.",
                                "You call too much: check the pot odds before calling."),
        ("wsd", "lo"): ("Você perde muitos showdowns: está pagando até o fim com mãos fracas.",
                        "You lose many showdowns: you're calling down with weak hands."),
        ("wtsd", "hi"): ("Você vai ao showdown demais: largue mãos marginais diante de apostas grandes.",
                         "You go to showdown too often: fold marginal hands to big bets."),
        ("threebet", "lo"): ("Re-aumente (3-bet) com as melhores mãos para não deixar barato.",
                             "3-bet your best hands so you don't let others in cheaply."),
        ("cbet", "lo"): ("Depois de aumentar antes do flop, aposte o flop com mais frequência (c-bet).",
                         "After raising pre-flop, bet the flop more often (c-bet)."),
    }
    out = []
    for st in stats(c):
        if st.value is None or st.sample < 8:
            continue
        side = "lo" if st.value < st.lo else "hi" if st.value > st.hi else None
        if side and (st.key, side) in tips:
            out.append(tr(*tips[(st.key, side)]))
    return out[:3]
