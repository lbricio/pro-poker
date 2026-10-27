"""Oponentes simulados: personalidade, humor que muda durante a partida e decisões com um pouco de acaso.

Cada bot tem traços-base (0..1) sorteados a partir de um arquétipo + dificuldade:
- aggression  agressivo (aposta/aumenta) × passivo (paga/passa)
- tightness   seletivo (joga poucas mãos) × solto
- bluff       frequência de blefe
- shove       gosto por all-in
- sticky      "calling station": paga apostas além da conta
- trap        slowplay: esconde mãos fortes passando
- tilt_prone  quanto as derrotas mexem com ele
- skill       precisão na leitura da própria força, uso de pot odds e posição (vem da dificuldade)
O humor (tilt e confiança) muda depois de cada mão e desloca os traços efetivos; os traços-base também
variam um pouco ao longo da partida. Os bots só usam o que um jogador real veria (nunca as cartas dos outros).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from functools import lru_cache

from pokertrainer import coach
from pokertrainer import engine as E
from pokertrainer.i18n import tr

TRAITS = ("aggression", "tightness", "bluff", "shove", "sticky", "trap", "tilt_prone")

ARCHETYPES = {
    #            aggr  tight bluff shove sticky trap  tilt
    "rock":    (0.25, 0.85, 0.03, 0.05, 0.15, 0.35, 0.30),
    "tag":     (0.70, 0.70, 0.12, 0.10, 0.15, 0.20, 0.30),
    "lag":     (0.85, 0.35, 0.25, 0.22, 0.25, 0.15, 0.45),
    "station": (0.20, 0.25, 0.04, 0.08, 0.85, 0.10, 0.50),
    "maniac":  (0.95, 0.12, 0.40, 0.50, 0.40, 0.05, 0.70),
    "fish":    (0.30, 0.35, 0.07, 0.12, 0.55, 0.15, 0.60),
    "reg":     (0.60, 0.60, 0.14, 0.10, 0.25, 0.25, 0.25),
    "pro":     (0.70, 0.62, 0.17, 0.12, 0.12, 0.25, 0.10),
    "conservative": (0.22, 0.72, 0.02, 0.03, 0.22, 0.30, 0.30),
    "bluffer": (0.78, 0.45, 0.55, 0.22, 0.25, 0.08, 0.45),
    # campeão: só no nível Pro; perto do jogo ideal, um pouco mais agressivo, quase imune a tilt
    "champion": (0.72, 0.64, 0.16, 0.10, 0.12, 0.22, 0.03),
}
# como cada estilo reage ao que vê: (ganho de medo, ganho de desconfiança, peso da memória nas decisões)
MEMORY_STYLE = {
    "maniac": (0.5, 1.4, 0.55),       # acha que todo mundo blefa e liga pouco para isso
    "station": (0.4, 1.3, 0.45),      # "você está blefando" — e paga de qualquer jeito
    "fish": (1.2, 1.2, 0.70),         # impressionável, mas esquece rápido
    "rock": (1.5, 0.6, 1.10),         # medroso: uma mão forte mostrada pesa muito
    "conservative": (1.4, 0.7, 1.10),
    "bluffer": (0.8, 1.35, 0.90),     # projeta o próprio jogo nos outros
    "lag": (0.8, 1.2, 1.00),
    "tag": (1.0, 1.0, 1.00),
    "reg": (1.0, 1.0, 1.00),
    "pro": (0.9, 0.9, 1.00),          # equilibrado e cético
    "champion": (0.9, 0.9, 0.50),     # equilibrado: usa as leituras, mas sem se tornar previsível
}
# desconfiança − medo de um jogador desconhecido/médio (prioris das fórmulas): é o ponto de efeito zero
NEUTRAL_READ = (0.6 * 0.25 + 0.25 * 0.25 + 0.15 * 0.25) - (0.5 * 0.55 + 0.3 * 0.2 + 0.2 * 0.4)
# medo de quebrar: quanto o estilo se encolhe (aposta menos, larga mais) quando o stack fica curto
SURVIVAL_STYLE = {"champion": 0.0, "rock": 0.9, "conservative": 1.0, "fish": 0.6, "station": 0.3, "tag": 0.35, "reg": 0.4, "lag": 0.2,
                  "maniac": 0.0, "bluffer": 0.2, "pro": 0.15}
# "caçador": quanto o estilo tenta eliminar quem está com poucas fichas
BULLY_STYLE = {"champion": 0.85, "lag": 0.8, "maniac": 0.9, "bluffer": 0.7, "tag": 0.6, "pro": 0.7, "reg": 0.5, "rock": 0.15,
               "conservative": 0.1, "fish": 0.3, "station": 0.2}
# percepção inicial (antes de qualquer evidência) de cada estilo sobre os outros: (medo, desconfiança)
INITIAL_BIAS = {"rock": (0.06, -0.02), "conservative": (0.07, -0.02), "station": (-0.04, 0.05),
                "maniac": (-0.06, 0.08), "bluffer": (-0.02, 0.07), "lag": (-0.03, 0.04), "tag": (0.0, 0.01),
                "fish": (0.02, 0.02), "reg": (0.0, 0.0), "pro": (0.0, 0.0), "champion": (0.0, 0.0)}
BIAS_SPREAD = 0.05     # ±5% para cada bot (sobre todos) e ±5% para cada adversário individualmente
MAX_MEMORY_INFLUENCE = 0.70           # a memória nunca decide mais que 70%; o resto fica para o jogo e o acaso
# o que um jogador sólido faria: quanto mais habilidade, mais os traços se aproximam disto (menos vazamentos),
# mantendo o estilo de cada um
OPTIMAL = {"aggression": 0.68, "tightness": 0.63, "bluff": 0.16, "shove": 0.10, "sticky": 0.14, "trap": 0.22,
           "tilt_prone": 0.12}
# habilidade relativa do estilo: um amador continua fraco mesmo numa mesa difícil
SKILL_SHIFT = {"fish": -0.18, "station": -0.18, "maniac": -0.12, "rock": -0.06, "conservative": -0.10,
               "bluffer": -0.10, "reg": 0.0, "tag": 0.04, "lag": 0.04, "pro": 0.10, "champion": 0.2}

ARCHETYPE_NAMES = {
    "rock": ("Retranqueiro (só joga mãos muito boas)", "Nit (only plays premium hands)"),
    "tag": ("Sólido e agressivo (TAG)", "Tight-aggressive (TAG)"),
    "lag": ("Solto e agressivo (LAG)", "Loose-aggressive (LAG)"),
    "station": ("Paga-tudo (paga quase qualquer aposta)", "Calling station (calls almost everything)"),
    "maniac": ("Maníaco (aposta e aumenta em tudo)", "Maniac (bets and raises everything)"),
    "fish": ("Recreativo (amador: joga muitas mãos e só paga)", "Recreational (plays too many hands, mostly calls)"),
    "conservative": ("Conservador (aposta pouco; só entra com 50%+ de chance)",
                     "Conservative (bets small; only commits with a 50%+ chance)"),
    "bluffer": ("Blefador (blefa com frequência)", "Bluffer (bluffs often)"),
    "reg": ("Regular (jogador frequente, razoável)", "Regular (frequent, decent player)"),
    "pro": ("Profissional (equilibrado e difícil de ler)", "Professional (balanced, hard to read)"),
    "champion": ("Campeão (muito difícil de vencer)", "Champion (very hard to beat)"),
}
ARCHETYPE_SHORT = {
    "rock": ("Retranqueiro", "Nit"), "tag": ("Sólido (TAG)", "TAG"), "lag": ("Solto-agressivo", "LAG"),
    "station": ("Paga-tudo", "Calling station"), "maniac": ("Maníaco", "Maniac"), "fish": ("Recreativo", "Fish"),
    "conservative": ("Conservador", "Conservative"), "bluffer": ("Blefador", "Bluffer"),
    "reg": ("Regular", "Regular"), "pro": ("Profissional", "Pro"), "champion": ("Campeão", "Champion"),
}
ARCHETYPE_HELP = {
    "rock": ("Quase nunca entra num pote; quando aposta forte, costuma ter mesmo. Roube os blinds dele.",
             "Rarely enters a pot; when he bets big he usually has it. Steal his blinds."),
    "tag": ("Joga poucas mãos, mas com agressividade. Respeite os aumentos dele.",
            "Plays few hands, but aggressively. Respect his raises."),
    "lag": ("Joga muitas mãos e pressiona o tempo todo; blefa bastante. Pague mais leve contra ele.",
            "Plays many hands and keeps the pressure on; bluffs a lot. Call lighter against him."),
    "station": ("Paga até o fim com qualquer coisa e quase não blefa. Não blefe; aposte suas mãos boas.",
                "Calls down with anything and rarely bluffs. Don't bluff him; value-bet your good hands."),
    "maniac": ("Aposta, aumenta e vai de all-in sem critério. Espere uma mão boa e deixe ele apostar.",
               "Bets, raises and shoves without discipline. Wait for a good hand and let him bet."),
    "fish": ("Entra em muitas mãos só pagando e erra bastante. É de quem os bons jogadores ganham fichas.",
             "Enters many pots just calling and makes plenty of mistakes. Good players profit from him."),
    "conservative": ("Só aposta e aumenta quando acha que tem 50% ou mais; aposta pequeno. Quando ele acorda, "
                     "acredite — e roube os potes em que ele só passa.",
                     "Only bets and raises when he thinks he has 50%+; bets small. When he wakes up, believe him — "
                     "and steal the pots where he just checks."),
    "bluffer": ("Blefa bem mais do que deveria, principalmente quando os outros passam. Pague mais leve e deixe "
                "ele apostar.", "Bluffs much more than he should, especially when others check. Call lighter and "
                "let him bet."),
    "reg": ("Jogador frequente e razoável, com alguns vícios previsíveis.",
            "A frequent, decent player with a few predictable habits."),
    "champion": ("Joga equilibrado e quase sem erros: o tamanho da aposta não revela a mão e ~1/3 das apostas "
                 "são blefes. Não tem um ponto fraco claro para explorar: escolha bem os potes, evite blefar contra "
                 "ele sem motivo e jogue em posição.",
                 "Plays balanced and almost error-free: bet size doesn't reveal the hand and ~1/3 of bets are "
                 "bluffs. There's no clear leak to exploit: pick your pots carefully, don't bluff him without a "
                 "reason and play in position."),
    "pro": ("Joga perto do ideal: tamanhos de aposta que não entregam a mão, blefes na medida e quase sem tilt.",
            "Plays close to optimal: bet sizes that don't reveal the hand, balanced bluffs and almost no tilt."),
}

DIFFICULTIES = ["easy", "medium", "hard", "semipro", "pro"]
DIFFICULTY_NAMES = {"easy": ("Fácil", "Easy"), "medium": ("Médio", "Medium"), "hard": ("Difícil", "Hard"),
                    "semipro": ("Semi-pro", "Semi-pro"), "pro": ("Pro", "Pro")}
DIFFICULTY_HELP = {
    "easy": ("Como um jogo entre amigos ou um bar: muitos amadores e pagadores, alguns maníacos e retranqueiros. "
             "Erram bastante e entregam a força pelo tamanho da aposta.",
             "Like a home game or a bar: lots of recreational players and calling stations, some maniacs and nits. "
             "They make many mistakes and size bets by hand strength."),
    "medium": ("Como um clube com apostas baixas: metade amadores, metade jogadores razoáveis.",
               "Like a low-stakes club: half recreational, half decent players."),
    "hard": ("Apostas médias: maioria de regulares e jogadores sólidos que respeitam pot odds e posição; "
             "poucos amadores.",
             "Mid stakes: mostly regulars and solid players who respect pot odds and position; few recreational."),
    "semipro": ("Mesa forte: regulares bons e alguns profissionais; erram pouco e blefam na medida.",
                "Tough table: good regulars and some pros; few mistakes and well-measured bluffs."),
    "pro": ("Mesa de profissionais: equilibrados, difíceis de ler, quase sem tilt e se adaptam ao seu estilo.",
            "A table of pros: balanced, hard to read, almost no tilt, and they adapt to your style."),
}
# (faixa de habilidade, pesos dos arquétipos, multiplicador de tilt)
# proporções (%) inspiradas na composição típica de mesas reais em cada nível
DIFF_PROFILE = {
    # amadores (recreativo, paga-tudo, maníaco, conservador, blefador) dominam o Fácil, ainda aparecem no Médio e
    # no Difícil e só raramente nas mesas Semi-pro e Pro
    "easy": ((0.12, 0.36), {"fish": 24, "station": 17, "maniac": 10, "conservative": 12, "bluffer": 10, "rock": 10,
                            "tag": 7, "lag": 5, "reg": 5}, 1.25),
    "medium": ((0.28, 0.52), {"fish": 14, "station": 10, "maniac": 5, "conservative": 9, "bluffer": 8, "rock": 10,
                              "tag": 17, "lag": 9, "reg": 18}, 1.0),
    "hard": ((0.48, 0.72), {"fish": 6, "station": 4, "maniac": 3, "conservative": 5, "bluffer": 5, "rock": 6,
                            "tag": 25, "lag": 14, "reg": 27, "pro": 5}, 0.75),
    "semipro": ((0.66, 0.86), {"fish": 2, "station": 1, "maniac": 1, "conservative": 3, "bluffer": 3, "rock": 4,
                               "tag": 28, "lag": 16, "reg": 28, "pro": 14}, 0.5),
    "pro": ((0.84, 0.97), {"fish": 1, "station": 1, "maniac": 1, "conservative": 2, "bluffer": 2, "tag": 20, "lag": 16,
                           "reg": 19, "pro": 35, "champion": 6}, 0.3),
}

NAMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Felipe", "Gabi", "Hugo", "Iris", "João", "Kátia", "Léo",
         "Marta", "Nico", "Olga", "Paulo", "Rita", "Sérgio", "Tina", "Vítor", "Yara", "Zeca", "Mike", "Sam",
         "Lucy", "Tom", "Nina", "Igor", "Lara", "Otto"]
AVATARS = ["🦊", "🐻", "🐼", "🦁", "🐯", "🐸", "🐵", "🦉", "🐺", "🐨", "🐙", "🦄", "🐷", "🐲", "🐧", "🦈"]


def difficulty_name(key: str) -> str:
    return tr(*DIFFICULTY_NAMES.get(key, (key, key)))


def archetype_name(key: str) -> str:
    return tr(*ARCHETYPE_NAMES.get(key, (key, key)))


def archetype_short(key: str) -> str:
    return tr(*ARCHETYPE_SHORT.get(key, (key, key)))


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


@lru_cache(maxsize=1)
def hand_percentile() -> dict[str, float]:
    """Mão inicial -> percentil (0 = melhor), ponderado pelas combinações."""
    order = coach.hand_order()
    out, acc = {}, 0
    for lab in order:
        w = 6 if len(lab) == 2 else 4 if lab.endswith("s") else 12
        out[lab] = (acc + w / 2) / 1326
        acc += w
    return out


@dataclass
class Personality:
    archetype: str
    skill: float
    base: dict[str, float]
    origin: dict[str, float] = field(default_factory=dict)  # para a deriva não fugir demais
    tilt: float = 0.0          # 0..1 (frustração)
    confidence: float = 0.0    # -1..1 (abalado .. confiante)
    adapt: bool = False        # profissionais se adaptam ao seu estilo
    chatty: float = 0.3        # quanto fala na mesa
    learn: float = 0.5         # intensidade com que usa o que aprendeu dos outros (dificuldade)
    attention: float = 0.6     # chance de prestar atenção num showdown de que não participou
    prior: float = 3.0         # ceticismo: quantas evidências "neutras" pesam antes das observações
    memory: float = 0.985      # quanto da memória sobra a cada mão (esquece aos poucos)
    fear_gain: float = 1.0     # quanto cada mão forte mostrada aumenta o medo (depende do estilo)
    susp_gain: float = 1.0     # quanto cada blefe visto aumenta a desconfiança
    influence: float = 0.5     # peso máximo da memória nas decisões (≤ 70%)
    survival: float = 0.3      # medo de quebrar com stack curto (amadores muito, profissionais pouco)
    bully: float = 0.4         # vontade de eliminar quem está com poucas fichas

    def eff(self, name: str) -> float:
        b = self.base[name]
        t, c = self.tilt, self.confidence
        if name == "aggression":
            return _clamp(b + 0.30 * t + 0.12 * c)
        if name == "tightness":
            return _clamp(b - 0.35 * t + 0.05 * min(c, 0) * -1)
        if name == "bluff":
            return _clamp(b * (1 + 1.3 * t) + 0.03 * max(c, 0))
        if name == "sticky":
            return _clamp(b + 0.30 * t)
        if name == "shove":
            return _clamp(b + 0.25 * t + 0.05 * max(c, 0))
        if name == "trap":
            return _clamp(b * (1 - 0.6 * t))
        return b

    @property
    def eff_skill(self) -> float:
        return _clamp(self.skill * (1 - 0.35 * self.tilt))

    def mood_emoji(self) -> str:
        if self.tilt > 0.45:
            return "😤"
        if self.confidence > 0.4:
            return "😎"
        if self.confidence < -0.4:
            return "😟"
        return ""

    def mood_text(self) -> str:
        if self.tilt > 0.45:
            return tr("em tilt", "on tilt")
        if self.confidence > 0.4:
            return tr("confiante", "confident")
        if self.confidence < -0.4:
            return tr("abalado", "shaken")
        return tr("calmo", "calm")


def archetype_help(key: str) -> str:
    return tr(*ARCHETYPE_HELP.get(key, ("", "")))


def make_personality(difficulty: str, rng: random.Random, archetype: str | None = None) -> Personality:
    """Sorteia uma personalidade do nível; `archetype` força o estilo (usado nas simulações de população)."""
    (s_lo, s_hi), weights, tilt_mult = DIFF_PROFILE.get(difficulty, DIFF_PROFILE["medium"])
    arch = archetype or rng.choices(list(weights), weights=list(weights.values()))[0]
    skill = _clamp(rng.uniform(s_lo, s_hi) + SKILL_SHIFT.get(arch, 0.0), 0.03, 0.98)
    if arch == "champion":
        skill = rng.uniform(0.985, 0.995)
    blend = 0.55 * skill        # habilidade alta = menos vazamentos (traços mais perto do jogo sólido)
    base = {}
    for name, v in zip(TRAITS, ARCHETYPES[arch]):
        v = v + rng.gauss(0, 0.07)
        v = v * (1 - blend) + OPTIMAL[name] * blend
        if name == "tilt_prone":
            v *= tilt_mult
        base[name] = _clamp(v, 0.01, 0.99)
    learn_base = {"easy": 0.25, "medium": 0.45, "hard": 0.7, "semipro": 0.85, "pro": 1.0}.get(difficulty, 0.5)
    learn = _clamp(learn_base + rng.gauss(0, 0.08), 0.05, 1.0)
    attention = _clamp(0.30 + 0.65 * skill + rng.gauss(0, 0.05), 0.15, 0.98)
    prior = 2.0 + 9.0 * skill            # bons jogadores não mudam de opinião por uma mão só
    memory = 0.965 + 0.027 * skill       # amadores esquecem rápido; profissionais lembram por mais tempo
    fg, sg, infl = MEMORY_STYLE.get(arch, (1.0, 1.0, 1.0))
    fear_gain = max(0.2, fg * (1 + rng.gauss(0, 0.2)))
    susp_gain = max(0.2, sg * (1 + rng.gauss(0, 0.2)))
    influence = _clamp(learn * infl * (1 + rng.gauss(0, 0.15)), 0.03, MAX_MEMORY_INFLUENCE)
    # amadores jogam "com medo de perder" quando estão curtos; profissionais sabem que é hora de empurrar
    survival = _clamp(SURVIVAL_STYLE.get(arch, 0.3) * (1 - 0.6 * skill) + rng.gauss(0, 0.08))
    bully = _clamp(BULLY_STYLE.get(arch, 0.4) * (0.5 + 0.5 * skill) + rng.gauss(0, 0.08))
    chat_base = {"maniac": 0.8, "lag": 0.55, "fish": 0.55, "station": 0.4, "tag": 0.3, "reg": 0.25, "rock": 0.15,
                 "pro": 0.15, "conservative": 0.15, "bluffer": 0.6, "champion": 0.2}
    chatty = _clamp(chat_base.get(arch, 0.3) + rng.gauss(0, 0.12), 0.05, 0.95)
    return Personality(arch, skill, base, origin=dict(base), adapt=skill >= 0.7, chatty=chatty, learn=learn,
                       attention=attention, prior=prior, memory=memory, fear_gain=fear_gain, susp_gain=susp_gain,
                       influence=influence, survival=survival, bully=bully)


# ---------------------------------------------------------------- leitura de cada adversário (memória)

@dataclass
class Read:
    """O que um bot aprendeu sobre um adversário, só com o que estava à vista na mesa.

    Contagens com decaimento (esquecimento). `aggr_sd`: showdowns em que o adversário tinha apostado/aumentado
    depois do flop; `bluffs`/`values`: desses, quantos com mão fraca / forte. `sd`/`sd_strength`: força média de
    todas as mãos que ele mostrou."""
    aggr_sd: float = 0.0
    bluffs: float = 0.0
    values: float = 0.0
    sd: float = 0.0
    sd_strength: float = 0.0
    last_fear: float = 0.0
    last_susp: float = 0.0
    bias_f: float = 0.0      # impressão inicial sobre este jogador (±5%), some com as evidências
    bias_s: float = 0.0


def _hand_strength(score: int, hole: list[int], board: list[int]) -> float:
    """0 (nada) .. 1 (monstro): categoria da mão final, com par alto valendo mais que par baixo."""
    cat = score >> 20
    if cat >= E.TWO_PAIR:
        return min(1.0, 0.65 + 0.07 * (cat - E.TWO_PAIR))
    if cat == E.PAIR:
        pair_rank = (score >> 16) & 0xF
        top = max(c >> 2 for c in board)
        return 0.45 if pair_rank >= top else 0.25
    return 0.05


@dataclass
class Decision:
    action: str          # fold, check, call, raise, allin
    amount_to: int = 0
    reason: str = ""     # "value", "bluff", "semibluff", "trap", "draw", "odds", "steal", "tilt"…


class Bot:
    def __init__(self, personality: Personality, rng: random.Random | None = None) -> None:
        self.p = personality
        self.rng = rng or random.Random()
        self._eq_cache: dict = {}
        # percepção inicial sobre todos: o estilo dá a tendência e cada bot varia ±5%
        bf, bs = INITIAL_BIAS.get(personality.archetype, (0.0, 0.0))
        self.bias_fear = bf + self.rng.uniform(-BIAS_SPREAD, BIAS_SPREAD)
        self.bias_susp = bs + self.rng.uniform(-BIAS_SPREAD, BIAS_SPREAD)

    # ------------------------------------------------------------ leitura da força
    def _equity(self, t, seat: int) -> float:
        me = t.players[seat]
        n_opp = max(1, len(t.seats_in_hand()) - 1)
        if not t.board:
            eq = coach.preflop_equity(E.starting_hand_label(*me.hole), min(n_opp, 9))
            if eq is not None:
                return eq
        key = (t.hand_no, len(t.board), n_opp)
        if key not in self._eq_cache:
            if len(self._eq_cache) > 40:
                self._eq_cache = {}
            iters = 3000 if self.champion else int(250 + 1250 * self.p.skill)
            self._eq_cache[key] = E.equity(me.hole, t.board, n_opp, iters, self.rng).equity
        return self._eq_cache[key]

    @staticmethod
    def reads(t, seat: int) -> tuple[float, float, float]:
        """O que dá para observar dos adversários ainda na mão: (VPIP, desiste-diante-de-aposta, agressividade).
        Sem amostra suficiente, usa valores de um jogador médio."""
        others = [t.players[i] for i in t.seats_in_hand() if i != seat] or [p for p in t.players if p is not t.players[seat]]
        def vp(p):
            return p.vpip / max(1, p.hands - 1) if p.hands >= 8 else 0.35
        def fr(p):
            return p.folds_to_bet / p.faced_bets if p.faced_bets >= 5 else 0.45
        def ag(p):
            return p.bets_raises / max(1, p.bets_raises + p.calls) if p.hands >= 8 else 0.4
        n = len(others)
        return sum(map(vp, others)) / n, sum(map(fr, others)) / n, sum(map(ag, others)) / n

    def _range_equity(self, t, seat: int, pct: int) -> float:
        me = t.players[seat]
        n_opp = max(1, len(t.seats_in_hand()) - 1)
        key = ("r", t.hand_no, len(t.board), n_opp, pct)
        if key not in self._eq_cache:
            iters = int(250 + 1000 * self.p.skill)
            self._eq_cache[key] = E.equity(me.hole, t.board, n_opp, iters, self.rng,
                                           opp_combos=coach.range_combos(pct)).equity
        return self._eq_cache[key]

    def _perceived(self, t, seat: int) -> float:
        """Força percebida: jogadores fracos pensam em "mãos aleatórias" e erram a leitura; jogadores habilidosos
        estimam a chance contra a faixa que os adversários realmente jogam (pelo VPIP observado) e pelo quanto
        eles apostam."""
        eq = self._equity(t, seat)
        sk = self.p.eff_skill
        if t.board and sk > 0.25:
            vpip, _fr, _ag = self.reads(t, seat)
            pct = int(max(8, min(100, round(vpip * 100 / 5) * 5)))
            me = t.players[seat]
            to_call = t.current_bet - me.bet
            if to_call > 0 and t.last_aggressor is not None and t.last_aggressor != seat:
                v = t.players[t.last_aggressor]
                v_aggr = v.bets_raises / max(1, v.calls + v.bets_raises) if v.hands >= 8 else 0.4
                pressure = min(1.5, to_call / max(1, t.pot - to_call))
                # aposta grande de quem raramente aposta = faixa mais forte; de um agressivo, nem tanto
                pct = int(max(8, pct * (1 - 0.45 * pressure * (1 - v_aggr))))
                # memória: de quem já foi visto blefando, a faixa é mais larga; de quem só mostra mão boa, mais estreita
                pct = int(max(8, min(100, pct * (1 + 1.2 * self._mem(v)))))
            if pct < 100:
                eq = eq * (1 - sk) + self._range_equity(t, seat, pct) * sk
        noise = self.rng.gauss(0, 0.02 + 0.13 * (1 - sk))   # jogadores fracos erram a leitura
        return _clamp(eq + noise, 0.0, 1.0)

    def pressure(self) -> float:
        """Vontade de aumentar o pote continuamente para tirar os outros da mão (0..1). Existe do Difícil para
        cima (habilidade ~0,45+), some nos muito habilidosos (~0,9+) e cresce com a agressividade e a confiança."""
        pr = self.p
        if pr.archetype == "champion":
            return 0.0          # equilibrado: não pressiona por impulso
        gate = _clamp((pr.skill - 0.45) / 0.25)
        # jogadores muito habilidosos (~0,9+) não pressionam por impulso: só apostam quando a mão/leitura pede
        gate *= _clamp((0.90 - pr.skill) / 0.08)
        drive = _clamp(1.2 * (pr.eff("aggression") - 0.45) + 0.6 * max(0.0, pr.confidence) + 0.2 * pr.tilt)
        return gate * drive

    def bust_fear(self, t, seat: int) -> float:
        """Medo de quebrar (0..1): cresce quando o stack fica abaixo de ~25 big blinds, conforme o estilo."""
        me = t.players[seat]
        stack_bb = (me.stack + me.bet) / max(1, t.bb)
        danger = _clamp((25 - stack_bb) / 20)
        return self.p.survival * danger

    def short_targets(self, t, seat: int) -> list:
        """Adversários na mão com poucas fichas que este bot cobre com folga (candidatos a eliminação)."""
        me = t.players[seat]
        mine = me.stack + me.bet
        out = []
        for i in t.seats_in_hand():
            q = t.players[i]
            if i == seat:
                continue
            theirs = q.stack + q.bet
            if theirs / max(1, t.bb) < 25 and theirs * 1.5 < mine:
                out.append(q)
        return out

    def _hero_fold_rate(self, t) -> float | None:
        for p in t.players:
            if p.is_hero and p.faced_bets >= 6:
                return p.folds_to_bet / p.faced_bets
        return None

    # ------------------------------------------------------------ decisão
    @property
    def champion(self) -> bool:
        return self.p.archetype == "champion"

    def blunder_rate(self) -> float:
        """Chance de um erro grosseiro numa decisão: ~10% para amadores, quase 0 para profissionais."""
        if self.champion:
            return 0.0
        return 0.12 * (1 - self.p.eff_skill) ** 2 + 0.05 * self.p.tilt * (1 - self.p.skill)

    def decide(self, t, seat: int) -> Decision:
        if not t.board:
            d = self._preflop(t, seat)
        else:
            d = self._postflop(t, seat)
        lg = t.legal(seat)
        if self.rng.random() < self.blunder_rate():
            # erro de amador: paga sem pot odds, desiste de mão boa ou aposta sem motivo
            opts = ["call", "fold", "raise"] if lg.to_call else ["raise", "check"]
            choice = self.rng.choice(opts)
            amt = int(t.current_bet + max(t.bb, 0.6 * t.pot)) if choice == "raise" else 0
            d = Decision(choice, amt, "blunder")
        if d.action == "raise":
            if not lg.can_raise:
                d = Decision("call" if lg.to_call else "check", reason=d.reason)
            else:
                d.amount_to = max(lg.min_raise_to, min(d.amount_to, lg.max_raise_to))
                # se sobra pouco no stack, vai de all-in
                if lg.max_raise_to - d.amount_to < 0.25 * d.amount_to:
                    d = Decision("allin", lg.max_raise_to, d.reason)
        if d.action == "call" and lg.to_call == 0:
            d.action = "check"
        if d.action == "fold" and lg.can_check:
            d.action = "check"
        return d

    def _preflop(self, t, seat: int) -> Decision:
        r, pr = self.rng, self.p
        me = t.players[seat]
        lg = t.legal(seat)
        bb = t.bb
        pct = hand_percentile().get(E.starting_hand_label(*me.hole), 0.5)
        pct = _clamp(pct + r.gauss(0, 0.03 + 0.08 * (1 - pr.eff_skill)))
        tight, aggr = pr.eff("tightness"), pr.eff("aggression")
        bluff, sticky, shove = pr.eff("bluff"), pr.eff("sticky"), pr.eff("shove")
        fb = self.bust_fear(t, seat)
        if fb:   # com medo de quebrar: mais seletivo, menos agressivo, sem blefes
            tight = _clamp(tight + 0.3 * fb)
            aggr = _clamp(aggr - 0.4 * fb)
            bluff *= 1 - fb
        press = self.pressure()
        if self.champion:   # pressiona só quem desiste demais (contra quem paga, pressão custa caro)
            press *= _clamp((self.reads(t, seat)[1] - 0.35) * 4)
        shorts = self.short_targets(t, seat)
        hunt = pr.bully if shorts else 0.0
        pos = t.position_of(seat)
        late = pos in ("BTN", "CO", "HJ")
        early = pos.startswith("UTG")
        vpip = 0.08 + 0.62 * (1 - tight)
        vpip += pr.eff_skill * (0.08 if late else -0.05 if early else 0.0)   # consciência de posição
        vpip = _clamp(vpip, 0.05, 0.9)
        pfr = vpip * (0.20 + 0.70 * aggr)
        pfr = min(vpip, pfr * (1 + 0.5 * hunt))   # isola quem está curto
        level = t.current_bet / bb                # 1 = ninguém aumentou
        stack_bb = (me.stack + me.bet) / bb
        to_call = lg.to_call

        if stack_bb <= 12:                        # stack curto: empurra ou desiste
            if r.random() < fb:
                # amador com medo: espera uma mão premium e vai "morrendo" nos blinds
                if pct < 0.05:
                    return Decision("allin", reason="short")
                if to_call == 0:
                    return Decision("check")
                return Decision("call" if to_call <= bb and pct < 0.25 else "fold", reason="scared")
            if pct < 0.12 + 0.25 * shove + 0.1 * (1 - tight) or (to_call == 0 and lg.can_check):
                return Decision("allin" if pct < 0.3 + 0.2 * shove else "check", 0, "short")
            return Decision("fold")

        if level <= 1.0:   # pote não aumentado
            if pct < pfr:
                if pct < 0.02 and r.random() < pr.eff("trap") * 0.4:
                    return Decision("call", reason="trap")
                limpers = sum(1 for q in t.players if q.in_hand and q.bet >= t.current_bet) - 1
                size = (2.2 + 1.2 * r.random() + 0.8 * (1 - pr.eff_skill) * (1 - pct)) * bb + limpers * bb
                if pct < 0.03 and r.random() < shove * 0.15:
                    return Decision("allin", reason="value")
                return Decision("raise", int(size), "value")
            if pct < vpip:
                if lg.can_check:
                    return Decision("check")
                if r.random() < aggr * 0.45:
                    return Decision("raise", int(t.current_bet * 2.5 + bb), "value")
                return Decision("call", reason="odds")
            steal = bluff * 0.9 + 0.1 * aggr
            if late:
                # habilidosos roubam mais quando os blinds são seletivos (desistem muito)
                blinds = [q for q in t.players if q.in_hand and q is not me and q.bet > 0]
                if blinds and all(q.hands >= 8 for q in blinds):
                    tight_bl = sum(1 - q.vpip / max(1, q.hands - 1) for q in blinds) / len(blinds)
                    steal *= 1 + pr.eff_skill * max(0.0, tight_bl - 0.6) * 3
            if late and r.random() < steal:
                return Decision("raise", int(2.5 * bb), "steal")
            return Decision("check" if lg.can_check else "fold")

        # alguém aumentou
        cont = vpip * (0.55 if level <= 4 else 0.30 if level <= 12 else 0.12)
        cont *= 1 + 0.8 * sticky
        if t.last_aggressor is not None and t.last_aggressor != seat:
            rv = t.players[t.last_aggressor]
            if rv.hands >= 8:   # quem aumenta muitas mãos merece ser pago (e re-aumentado) com mais frequência
                r_pfr = rv.pfr / max(1, rv.hands - 1)
                cont *= 1 + pr.eff_skill * max(-0.4, min(2.0, (r_pfr - 0.15) * 4))
            cont *= 1 + 1.2 * self._mem(rv)
            if rv in shorts:      # o curto empurrou: paga mais leve para eliminá-lo
                cont *= 1 + 1.2 * hunt
        three = pfr * (0.35 if level <= 4 else 0.12)
        three *= 1 + 1.5 * press  # agressivos/confiantes (Difícil+) re-aumentam mais para tirar os outros
        commit = to_call / max(1, me.stack + me.bet)
        if commit > 0.4:          # pagar compromete boa parte do stack
            cont = min(cont, 0.05 + 0.08 * shove + 0.06 * sticky + 0.04 * pr.tilt)
        if pct < three:
            if level > 12 or r.random() < shove * 0.3 or commit > 0.3:
                return Decision("allin", reason="value")
            return Decision("raise", int(t.current_bet * (2.6 + 0.8 * r.random())), "value")
        if pct < cont:
            if r.random() < 0.3 * press and commit < 0.25 and level <= 12:
                return Decision("raise", int(t.current_bet * (2.5 + 0.7 * r.random())), "pressure")
            return Decision("call", reason="odds")
        if level <= 4 and r.random() < bluff * 0.25 + 0.1 * press and pct < 0.5:
            return Decision("raise", int(t.current_bet * 3), "bluff")
        if to_call <= bb * 0.5 + 1 and pct < 0.7:        # completa o small blind barato
            return Decision("call", reason="odds")
        return Decision("fold")

    # ------------------------------------------------------------ campeão: decisões por valor esperado
    @staticmethod
    def hand_class(hole: list[int], board: list[int]) -> int:
        """0 mão muito forte (dois pares+ próprios) · 1 par alto · 2 par fraco · 3 projeto de flush · 4 nada."""
        cat = E.evaluate(hole + board) >> 20
        if cat > E.board_category(board):
            if cat >= E.TWO_PAIR:
                return 0
            if cat == E.PAIR:
                ranks = [c >> 2 for c in hole + board]
                pair = max(rk for rk in set(ranks) if ranks.count(rk) >= 2)
                return 1 if pair >= max(c >> 2 for c in board) else 2
        if len(board) < 5:
            suits = [c & 3 for c in hole + board]
            if any(suits.count(sv) >= 4 and any(c & 3 == sv for c in hole) for sv in range(4)):
                return 3
        return 4

    def weighted_equity(self, t, seat: int, pct: int, weights: tuple, iters: int) -> tuple[float, float]:
        """Chance contra um adversário cuja mão sai da faixa `pct` e é ponderada pela probabilidade de ele agir
        (apostar/pagar) com aquela classe de mão; os demais adversários vêm da faixa sem ponderação.
        Devolve (chance ponderada, peso médio = probabilidade de ele agir)."""
        me = t.players[seat]
        board = list(t.board)
        known = set(me.hole) | set(board)
        combos = [(a, b) for a, b in (coach.range_combos(pct) or
                                      [(a, b) for a in range(52) for b in range(a + 1, 52)])
                  if a not in known and b not in known]
        if not combos:
            return 0.5, 0.5
        n_opp = max(1, len(t.seats_in_hand()) - 1)
        r = self.rng
        tot_w = tot_v = 0.0
        need = 5 - len(board)
        for _ in range(iters):
            a, b = r.choice(combos)
            w = weights[self.hand_class([a, b], board)]
            if w <= 0:
                continue
            used = known | {a, b}
            others = []
            for _k in range(n_opp - 1):
                for _try in range(50):
                    c1, c2 = r.choice(combos)
                    if c1 not in used and c2 not in used:
                        break
                used |= {c1, c2}
                others.append([c1, c2])
            rest = r.sample([c for c in range(52) if c not in used], need)
            full = board + rest
            hs = E.evaluate(me.hole + full)
            opp = [E.evaluate([a, b] + full)] + [E.evaluate(o + full) for o in others]
            best = max(opp)
            v = 1.0 if hs > best else (1.0 / (1 + opp.count(best)) if hs == best else 0.0)
            tot_w += w
            tot_v += w * v
        return (tot_v / tot_w if tot_w else 0.0), tot_w / iters

    def range_read_weight(self) -> float:
        """Quanto um bot (não campeão) usa a leitura da faixa de aposta do adversário: 0 até habilidade 0,80,
        crescendo até 60% nos mais habilidosos (nível Pro)."""
        if self.champion:
            return 0.0
        return 0.6 * _clamp((self.p.eff_skill - 0.80) / 0.15)

    def betting_range_equity(self, t, seat: int, to_call: int, iters: int = 400) -> float:
        """Chance contra as mãos com que quem apostou realmente apostaria: mãos fortes quase sempre, pares e
        projetos às vezes, blefes conforme a desconfiança e a agressividade observadas desse jogador."""
        vpip, _fr, _ag = self.reads(t, seat)
        pct = int(max(10, min(100, round(vpip * 100 / 5) * 5)))
        pot = t.pot
        agg = t.players[t.last_aggressor] if t.last_aggressor is not None else None
        bluff = 0.12
        if agg is not None and agg is not t.players[seat]:
            v_aggr = agg.bets_raises / max(1, agg.calls + agg.bets_raises) if agg.hands >= 8 else 0.4
            bluff = _clamp(0.06 + 0.4 * self.suspicion(agg) + 0.25 * (v_aggr - 0.4), 0.02, 0.6)
        size = min(1.5, to_call / max(1, pot - to_call))
        weights = (0.95, 0.8 - 0.15 * size, 0.35 - 0.15 * size, 0.55, bluff)
        eq, _ = self.weighted_equity(t, seat, pct, weights, iters)
        return eq

    def _champion_postflop(self, t, seat: int) -> Decision:
        """Campeão: jogo EQUILIBRADO (perto do teórico), executado com a maior competência.

        - tamanho de aposta sorteado (⅓, ⅔, pote) e independente da força da mão: não dá para ler;
        - blefes na proporção equilibrada para o tamanho (α = aposta ÷ (pote + 2·aposta)), de preferência com
          projetos; às vezes passa com mãos fortes para proteger as vezes em que passa;
        - diante de aposta: estima a faixa equilibrada de quem aposta (com uma pitada do que observou dele) e paga
          quando a chance cobre as pot odds, sem desistir demais (defende perto da frequência mínima de defesa).
        Só usa o que está à vista."""
        r = self.rng
        me = t.players[seat]
        lg = t.legal(seat)
        pot = t.pot
        n_opp = max(1, len(t.seats_in_hand()) - 1)
        stack_now = me.stack + me.bet
        vpip, _fr, _ag = self.reads(t, seat)
        pct = int(max(10, min(100, round(vpip * 100 / 5) * 5)))
        iters = 800
        cls = self.hand_class(me.hole, t.board)

        if lg.can_check:
            frac = r.choices([0.33, 0.66, 1.0], weights=[0.4, 0.4, 0.2])[0]
            b = min(max(t.bb, int(frac * pot)), stack_now)
            alpha = b / (pot + 2 * b)
            # chance contra quem pagaria essa aposta (faixa de pagamento equilibrada)
            call_w = (1.0, 0.9 - 0.15 * frac, 0.45 - 0.25 * frac, 0.6, 0.06)
            eq_c, _cont = self.weighted_equity(t, seat, pct, call_w, iters)
            multi = 1.0 / n_opp            # blefar contra muitos jogadores é caro
            if eq_c >= 0.5:
                if r.random() < 0.15:      # protege a linha de "passar" com algumas mãos fortes
                    return Decision("check", reason="trap")
                return Decision("allin" if b >= stack_now else "raise", t.current_bet + b, "value")
            if cls == 3 and r.random() < 0.6 * multi:                     # projeto: semiblefe
                return Decision("allin" if b >= stack_now else "raise", t.current_bet + b, "semibluff")
            # blefes : apostas de valor ≈ α : (1 − α). Como as mãos "sem nada" são ~5× mais comuns que as de
            # valor, a chance de blefar com uma delas é α/(1 − α) dividido por ~7
            if cls == 4 and r.random() < alpha / (1 - alpha) * 0.14 * multi:
                return Decision("allin" if b >= stack_now else "raise", t.current_bet + b, "bluff")
            return Decision("check")

        to_call = lg.to_call
        pot_before = pot - to_call
        alpha = to_call / max(1, pot_before + 2 * to_call)
        agg = t.players[t.last_aggressor] if t.last_aggressor is not None else None
        # faixa de aposta equilibrada (blefes ≈ α) com 30% do que já observou desse jogador
        bluff_w = 1.6 * alpha
        if agg is not None:
            observed = 0.06 + 0.4 * self.suspicion(agg)
            bluff_w = 0.7 * bluff_w + 0.3 * observed
        size = to_call / max(1, pot_before)
        bet_w = (0.95, 0.8 - 0.15 * min(size, 1.5), 0.35 - 0.15 * min(size, 1.5), 0.55, _clamp(bluff_w, 0.02, 0.7))
        eq_call, _ = self.weighted_equity(t, seat, pct, bet_w, iters)
        need = to_call / (pot + to_call)
        if lg.can_raise and eq_call >= 0.68:
            raise_to = min(int(t.current_bet * 2.7 + 0.3 * pot), lg.max_raise_to)
            return Decision("allin" if raise_to >= lg.max_raise_to else "raise", raise_to, "value")
        if lg.can_raise and cls == 3 and n_opp == 1 and r.random() < 0.12:      # às vezes semiblefa com aumento
            raise_to = min(int(t.current_bet * 2.7 + 0.3 * pot), lg.max_raise_to)
            return Decision("allin" if raise_to >= lg.max_raise_to else "raise", raise_to, "semibluff")
        # defende perto da frequência mínima: mãos com par alto ou melhor nunca largam aposta pequena
        if eq_call >= need or (cls <= 1 and size <= 0.5):
            return Decision("call", reason="odds")
        return Decision("fold")

    def _postflop(self, t, seat: int) -> Decision:
        if self.champion:
            return self._champion_postflop(t, seat)
        r, pr = self.rng, self.p
        me = t.players[seat]
        lg = t.legal(seat)
        n_opp = max(1, len(t.seats_in_hand()) - 1)
        pot = t.pot
        eq = self._perceived(t, seat)
        fair = 1 / (n_opp + 1)
        s = (eq - fair) / (1 - fair)               # >0: acima da média
        s += r.gauss(0, 0.03)                      # pitada de imprevisibilidade
        aggr, bluff, sticky = pr.eff("aggression"), pr.eff("bluff"), pr.eff("sticky")
        shove, trap, tight = pr.eff("shove"), pr.eff("trap"), pr.eff("tightness")
        sk = pr.eff_skill
        n_outs = len({c for cs in E.outs(me.hole, t.board).values() for c in cs}) if len(t.board) < 5 else 0
        draw = n_outs >= 8
        # ajustes a quem está na mão, proporcionais à habilidade: blefa em quem desiste, não blefa em pagador,
        # aposta mãos médias contra pagadores e paga mais leve contra agressivos
        _vp, fold_rate, field_aggr = self.reads(t, seat)
        if pr.adapt:
            hero_fr = self._hero_fold_rate(t)
            if hero_fr is not None and any(t.players[i].is_hero for i in t.seats_in_hand()):
                fold_rate = (fold_rate + hero_fr) / 2
        bluff = _clamp(bluff * ((1 - sk) + sk * (0.2 + 1.8 * fold_rate)))
        value_shift = sk * 0.18 * (0.5 - fold_rate)          # contra quem paga tudo, aposta mais mãos médias
        call_shift = sk * 0.10 * (field_aggr - 0.4)          # contra agressivos, paga um pouco mais

        conservative = pr.archetype == "conservative"
        fb = self.bust_fear(t, seat)
        if fb:   # perto de quebrar: menos apostas, menos blefes, larga mais
            aggr = _clamp(aggr - 0.4 * fb)
            bluff *= 1 - fb
        press = self.pressure()
        if self.champion:
            press *= _clamp((fold_rate - 0.35) * 4)
        shorts = self.short_targets(t, seat)
        hunt = pr.bully if shorts else 0.0
        value_shift += 0.10 * hunt            # contra um curto, aposta mais para eliminá-lo

        def bet_size() -> int:
            if conservative:   # aposta pequena, "para proteger"
                return int(round((t.current_bet + max(t.bb, r.uniform(0.28, 0.45) * pot)) / 5) * 5)
            if sk > 0.7:   # bons jogadores variam o tamanho sem entregar a força
                frac = r.choice([0.33, 0.5, 0.66, 0.75, 1.0])
                if s > 0.3 and fold_rate < 0.4:
                    frac = max(frac, 0.75 + 0.4 * (0.4 - fold_rate))   # contra pagadores: valor máximo
            else:          # fracos apostam mais quanto mais forte a mão
                frac = 0.35 + 0.75 * max(0.0, s) * (1 - sk) + 0.25 * aggr + r.gauss(0, 0.08)
            if r.random() < shove * 0.15:
                frac *= 1.8   # aposta acima do pote
            frac *= 1 + 0.12 * press * (n_opp - 1)   # multiway: aposta maior para tirar gente da mão
            frac *= 1 - 0.5 * fb                     # com medo de quebrar, aposta pequeno
            base = t.current_bet + max(t.bb, frac * pot)
            if shorts and r.random() < hunt:
                # coloca o curto em all-in de uma vez
                base = max(base, max(q.stack + q.bet for q in shorts))
            return int(round(base / 5) * 5)

        stack_now = me.stack + me.bet
        if lg.can_check:
            # slowplay só faz sentido contra quem aposta; contra pagadores, o habilidoso aposta
            trap_eff = trap * (1 - sk * min(1.0, max(0.0, (0.5 - fold_rate) * 3)))
            if s > 0.6 and r.random() < trap_eff * 0.6:
                return Decision("check", reason="trap")
            if conservative and eq < 0.5:
                return Decision("check")      # só aposta quando acha que tem 50% ou mais
            if r.random() < _sig((s - (0.32 - 0.28 * aggr - value_shift)) * 9):
                amt = bet_size()
                if s > 0.7 and (r.random() < shove * 0.4 or amt > 0.55 * stack_now):
                    return Decision("allin", reason="value")
                return Decision("raise", amt, "value")
            heads_up = 1.3 if n_opp == 1 else 0.6 / n_opp
            cbet = 1.4 if t.last_aggressor == seat else 1.0
            if t.last_aggressor == seat and s > -0.25 and r.random() < 0.4 * press:
                # continua apostando rua após rua (barrel) para manter a pressão
                return Decision("raise", bet_size(), "pressure")
            if draw and r.random() < 0.25 + 0.45 * aggr:
                return Decision("raise", bet_size(), "semibluff")
            if s < 0.15 and r.random() < bluff * heads_up * cbet:
                return Decision("raise", bet_size(), "bluff")
            return Decision("check")

        # enfrentando aposta
        to_call = lg.to_call
        need = to_call / (pot + to_call)
        read_w = self.range_read_weight()
        if read_w > 0:
            # leitura de faixa (como o Campeão): com que mãos ESTE jogador apostaria nesta mesa?
            eq_bet = self.betting_range_equity(t, seat, to_call)
            eq = (1 - read_w) * eq + read_w * eq_bet
            s = (eq - fair) / (1 - fair) + r.gauss(0, 0.03)
        implied = 0.05 * sk if draw and len(t.board) < 5 else 0.0
        stickiness = 0.14 * sticky
        if r.random() < 0.6 * sticky:
            stickiness += 0.06   # "só para ver"
        req = need * (1 + 0.15 * tight) + 0.10 * fb
        commit = to_call / max(1, stack_now)
        aggressor = t.players[t.last_aggressor] if t.last_aggressor is not None else None
        if aggressor is not None and aggressor in shorts:
            call_shift += 0.08 * hunt          # o curto apostou: paga mais leve para tentar eliminá-lo
        if commit > 0.5:
            req += 0.08 * (1 - shove) * (1 - pr.tilt)
        if s > 0.5 - 0.25 * aggr and r.random() < 0.3 + 0.5 * aggr and not (conservative and eq < 0.6):
            if s > 0.75 and (r.random() < shove * 0.5 or commit > 0.35):
                return Decision("allin", reason="value")
            return Decision("raise", int(t.current_bet * (2.4 + r.random()) + 0.3 * pot), "value")
        if s > 0.15 and commit < 0.3 and r.random() < 0.3 * press:
            # re-aumenta mãos médias para tirar os outros e controlar a mão
            return Decision("raise", int(t.current_bet * (2.3 + 0.6 * r.random()) + 0.25 * pot
                                         * (1 + 0.15 * (n_opp - 1))), "pressure")
        if n_opp == 1 and s < 0.1 and r.random() < bluff * 0.18:
            return Decision("raise", int(t.current_bet * 2.7 + 0.2 * pot), "bluff")
        if t.last_aggressor is not None and t.last_aggressor != seat:
            # memória sobre quem apostou: desconfiança faz pagar mais leve, medo faz largar mais
            call_shift += 0.12 * self._mem(t.players[t.last_aggressor])
        if eq + implied + stickiness + call_shift >= req:
            if draw and r.random() < 0.15 * aggr and not commit > 0.4:
                return Decision("raise", int(t.current_bet * 2.6 + 0.3 * pot), "semibluff")
            return Decision("call", reason="draw" if draw and s < 0.3 else "odds")
        return Decision("fold")

    # ------------------------------------------------------------ memória sobre os adversários
    def read_of(self, target) -> Read:
        if not hasattr(self, "_reads"):
            self._reads: dict[int, Read] = {}
        rd = self._reads.get(target.uid)
        if rd is None:
            # impressão inicial individual sobre este jogador: ±5% em medo e em desconfiança
            rd = Read(bias_f=self.rng.uniform(-BIAS_SPREAD, BIAS_SPREAD),
                      bias_s=self.rng.uniform(-BIAS_SPREAD, BIAS_SPREAD))
            self._reads[target.uid] = rd
        return rd

    def _bias_weight(self, rd: Read) -> float:
        """A impressão inicial pesa 100% sem evidências e vai sumindo conforme o bot vê showdowns do jogador."""
        return self.p.prior / (self.p.prior + rd.sd)

    def fear(self, target) -> float:
        """Medo / respeito pelas apostas deste jogador (0..1): ele mostrou mãos fortes quando apostou, joga poucas
        mãos (quando entra, tem jogo) e as mãos que mostra costumam ser boas."""
        pr, rd = self.p, self.read_of(target)
        a0 = pr.prior
        value_rate = min(1.0, (rd.values + a0 * 0.55) / (rd.aggr_sd + a0))
        vpip = target.vpip / max(1, target.hands - 1) if target.hands >= 10 else 0.3
        tight = _clamp((0.35 - vpip) / 0.25)
        shown = (rd.sd_strength + a0 * 0.4) / (rd.sd + a0)
        bias = (self.bias_fear + rd.bias_f) * self._bias_weight(rd)
        return _clamp(0.5 * value_rate + 0.3 * tight + 0.2 * shown + bias)

    def suspicion(self, target) -> float:
        """Desconfiança (0..1): acha que este jogador blefa. Sobe ao vê-lo mostrar mão fraca depois de apostar e
        quando ele aposta/aumenta com muita frequência (ninguém tem mão boa tantas vezes)."""
        pr, rd = self.p, self.read_of(target)
        a0 = pr.prior
        bluff_rate = min(1.0, (rd.bluffs + a0 * 0.25) / (rd.aggr_sd + a0))
        if target.hands >= 10:
            af = target.bets_raises / max(1, target.calls)
            aggr = _clamp((af - 1.5) / 3)
            loose = _clamp((target.vpip / max(1, target.hands - 1) - 0.25) / 0.4)
        else:
            aggr, loose = 0.25, 0.25
        bias = (self.bias_susp + rd.bias_s) * self._bias_weight(rd)
        return _clamp(0.6 * bluff_rate + 0.25 * aggr + 0.15 * loose + bias)

    def respect_shift(self, target) -> float:
        """Quanto paga a mais (+) ou a menos (−) contra este jogador, de −0,7 a +0,7: a opinião (desconfiança −
        medo) vezes a influência da memória, que depende da dificuldade e do estilo e nunca passa de 70%.
        Nas decisões ainda entra um fator aleatório, então a memória pesa, mas não decide sozinha."""
        d = max(-1.0, min(1.0, (self.suspicion(target) - self.fear(target) - NEUTRAL_READ) * 1.6))
        return self.p.influence * d

    def _mem(self, target) -> float:
        """respect_shift com a variação de cada decisão (o resto fica aberto ao acaso)."""
        return self.respect_shift(target) * (0.5 + 0.5 * self.rng.random())

    def observe_hand(self, t, seat: int) -> list[tuple[object, str]]:
        """Depois de cada mão: aprende com os showdowns e esquece um pouco o passado.
        Devolve as mudanças marcantes [(jogador, 'bluff'|'value')] para o histórico."""
        pr = self.p
        if not hasattr(self, "_reads"):
            self._reads = {}
        for rd in self._reads.values():
            for k in ("aggr_sd", "bluffs", "values", "sd", "sd_strength"):
                setattr(rd, k, getattr(rd, k) * pr.memory)
        notes = []
        me = t.players[seat]
        in_sd = seat in t.showdown_hands
        for i, sc in t.showdown_hands.items():
            if i == seat:
                continue
            target = t.players[i]
            # quem estava na mão presta atenção; os outros, só às vezes (amadores se distraem)
            if not in_sd and self.rng.random() > pr.attention:
                continue
            rd = self.read_of(target)
            strength = _hand_strength(sc, target.hole, t.board)
            rd.sd += 1
            rd.sd_strength += strength
            if target.post_aggr:
                rd.aggr_sd += 1
                if strength <= 0.25:
                    rd.bluffs += pr.susp_gain
                    notes.append((target, "bluff"))
                elif strength >= 0.45:
                    rd.values += pr.fear_gain
                    if strength >= 0.65:
                        notes.append((target, "value"))
        return notes

    def memory_summary(self, players) -> list[tuple[object, float, float]]:
        """[(jogador, medo, desconfiança)] sobre os outros jogadores da mesa."""
        return [(p, self.fear(p), self.suspicion(p)) for p in players if p.ai is not self and p.hands]

    # ------------------------------------------------------------ humor
    def after_hand(self, net: int, bb: int, bad_beat: bool) -> None:
        pr, r = self.p, self.rng
        nb = net / bb
        tp = pr.base["tilt_prone"]
        pr.tilt *= 0.86
        pr.confidence *= 0.9
        if nb < -12:
            pr.tilt += tp * min(0.45, -nb / 90)
            pr.confidence -= min(0.35, -nb / 120)
        if bad_beat:
            pr.tilt += 0.3 * tp
        if nb > 12:
            pr.confidence += min(0.35, nb / 100)
            pr.tilt *= 0.6
        pr.tilt = _clamp(pr.tilt)
        pr.confidence = _clamp(pr.confidence, -1, 1)
        # deriva lenta dos traços (o jogador "muda de marcha" ao longo da noite)
        for k in TRAITS:
            o = pr.origin.get(k, pr.base[k])
            pr.base[k] = _clamp(pr.base[k] + r.gauss(0, 0.012), max(0.01, o - 0.15), min(0.99, o + 0.15))


def new_bot_player(difficulty: str, stack: int, rng: random.Random, taken: set[str]):
    from pokertrainer.table import Player
    name = rng.choice([n for n in NAMES if n not in taken] or NAMES)
    pers = make_personality(difficulty, rng)
    avatar = "👑" if pers.archetype == "champion" else rng.choice(AVATARS)   # a fama do campeão chega antes dele
    return Player(name=name, stack=stack, avatar=avatar, ai=Bot(pers, random.Random(rng.random())))


# ---------------------------------------------------------------- mesa viva: tempo de decisão e falas

def think_ms(d: Decision, to_call: int, pot: int, pers: Personality, base: int, rng: random.Random) -> int:
    """Tempo de "pensar": decisões fáceis são rápidas, apostas grandes e all-ins demoram mais."""
    f = 0.45 + 0.5 * rng.random()
    if d.action in ("raise", "allin"):
        f += 0.45
    if to_call:
        f += min(1.2, to_call / max(1, pot))
    if d.action == "fold" and to_call <= 0:
        f *= 0.6
    if d.reason in ("bluff", "trap"):
        f += 0.3 * rng.random()        # hesita um pouco (um "tell")
    f *= 1.15 - 0.3 * pers.skill        # bons jogadores têm ritmo mais constante
    return int(base * f)


_LINES = {
    "allin": [("All-in! 💥", "All-in! 💥"), ("Vamos ver do que você é feito.", "Let's see what you're made of."),
              ("Tudo ou nada!", "All or nothing!"), ("Empurrei. 😏", "I'm pushing. 😏")],
    "raise": [("Vamos apimentar isso 🌶️", "Let's spice it up 🌶️"), ("Aumento.", "Raise."),
              ("Não vai ser barato.", "This won't be cheap."), ("Mais um pouquinho…", "A bit more…")],
    "call": [("Eu pago. Quero ver.", "I call. Show me."), ("Não acredito em você 🤨", "I don't believe you 🤨"),
             ("Pago, por curiosidade.", "Calling, just curious.")],
    "fold": [("Essa não é pra mim.", "Not this one."), ("Fica pra próxima.", "Next time."),
             ("Tá bom, leva.", "Fine, take it.")],
    "win": [("Obrigado pelas fichas 😎", "Thanks for the chips 😎"), ("Eu sabia! 🙌", "I knew it! 🙌"),
            ("Sorte? Talento.", "Luck? Skill."), ("Mais uma pra mim.", "Another one for me.")],
    "bigwin": [("Que pote! 🤑", "What a pot! 🤑"), ("Isso que é mão!", "Now that's a hand!"),
               ("Hoje é meu dia 🍀", "Today is my day 🍀")],
    "badbeat": [("Não acredito… 😤", "Unbelievable… 😤"), ("Que sorte a sua!", "So lucky!"),
                ("Esse river… 🙄", "That river… 🙄"), ("Como você pagou com isso?!", "How did you call with that?!")],
    "tilt": [("Agora é guerra.", "Now it's war."), ("Cansei de desistir.", "I'm done folding."),
             ("Vou recuperar tudo.", "I'm getting it all back.")],
    "lose": [("Boa mão.", "Nice hand."), ("Bem jogado.", "Well played."), ("Hmpf.", "Hmpf.")],
}
_WEIGHT = {"allin": 0.7, "raise": 0.18, "call": 0.08, "fold": 0.05, "win": 0.35, "bigwin": 0.8, "badbeat": 0.9,
           "tilt": 0.9, "lose": 0.15}


def chat(kind: str, pers: Personality, rng: random.Random) -> str | None:
    """Fala ocasional na mesa, conforme a personalidade (os maníacos falam mais) e o humor."""
    p = _WEIGHT.get(kind, 0.1) * (0.35 + pers.chatty)
    if pers.tilt > 0.45:
        p *= 1.4
    if rng.random() > p:
        return None
    if kind in ("raise", "call") and pers.tilt > 0.45 and rng.random() < 0.5:
        kind = "tilt"
    return tr(*rng.choice(_LINES[kind]))


# estrutura de blinds do torneio (sobe a cada HANDS_PER_LEVEL mãos)
BLIND_LEVELS = [(5, 10), (10, 20), (15, 30), (25, 50), (50, 100), (75, 150), (100, 200), (150, 300), (200, 400),
                (300, 600), (500, 1000), (800, 1600)]
HANDS_PER_LEVEL = 10


# rodadas do torneio por dificuldade (a última é a mesa final)
TOURNAMENT_ROUNDS = {"easy": 3, "medium": 3, "hard": 5, "semipro": 5, "pro": 6}


def tournament_rounds(difficulty: str) -> int:
    return TOURNAMENT_ROUNDS.get(difficulty, 3)


def round_qualifiers(n_players: int, final: bool) -> int:
    """Quantos jogadores da mesa passam de rodada (na mesa final, só o campeão)."""
    return 1 if final else max(1, n_players // 2)


def blinds_for(hands_played: int) -> tuple[int, int, int]:
    """(sb, bb, mãos até subir) no torneio."""
    lvl = min(len(BLIND_LEVELS) - 1, hands_played // HANDS_PER_LEVEL)
    left = HANDS_PER_LEVEL - hands_played % HANDS_PER_LEVEL if lvl < len(BLIND_LEVELS) - 1 else 0
    return (*BLIND_LEVELS[lvl], left)
