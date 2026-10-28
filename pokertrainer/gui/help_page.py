"""Como jogar: as regras do Texas Hold'em No-Limit e de cada modo do app, numa página rolável."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from pokertrainer import ai
from pokertrainer import engine as E
from pokertrainer.i18n import pick, tr

CSS = """
<style>
h2 { color: #f5c542; margin-top: 22px; margin-bottom: 6px; font-size: 19px; }
h3 { color: #ffe7a3; margin-top: 12px; margin-bottom: 4px; font-size: 15px; }
p, li, td { color: #dfe8e5; line-height: 150%; }
.k { color: #ffffff; font-weight: bold; }
.m { color: #9fb3ad; }
table.rank td { padding: 3px 10px 3px 0; }
</style>
"""

# (exemplo de cartas, descrição) do mais forte para o mais fraco; o nome vem do motor (bilíngue)
RANKING = [
    (8, "A♠ K♠ Q♠ J♠ 10♠", ("5 cartas em sequência do mesmo naipe. A maior possível (A-K-Q-J-10) é o <i>royal flush</i>.",
                           "5 cards in a row of the same suit. The highest one (A-K-Q-J-10) is the <i>royal flush</i>.")),
    (7, "9♣ 9♦ 9♥ 9♠ K♦", ("4 cartas do mesmo valor.", "4 cards of the same rank.")),
    (6, "Q♥ Q♣ Q♦ 7♠ 7♥", ("Uma trinca e um par.", "Three of a kind plus a pair.")),
    (5, "A♦ J♦ 8♦ 5♦ 2♦", ("5 cartas do mesmo naipe, fora de sequência.", "5 cards of the same suit, not in a row.")),
    (4, "8♣ 7♦ 6♥ 5♠ 4♦", ("5 cartas em sequência, de naipes variados. O Ás vale alto (10-J-Q-K-A) ou baixo (A-2-3-4-5).",
                           "5 cards in a row, mixed suits. The Ace plays high (10-J-Q-K-A) or low (A-2-3-4-5).")),
    (3, "J♠ J♥ J♣ K♦ 4♠", ("3 cartas do mesmo valor.", "3 cards of the same rank.")),
    (2, "K♠ K♦ 6♣ 6♥ A♠", ("Dois pares diferentes.", "Two different pairs.")),
    (1, "10♥ 10♣ A♦ 8♠ 3♣", ("2 cartas do mesmo valor.", "2 cards of the same rank.")),
    (0, "A♣ Q♦ 9♠ 6♥ 3♦", ("Nenhuma combinação: vale a carta mais alta.", "No combination: the highest card plays.")),
]


def _ranking_html() -> str:
    rows = "".join(
        f"<tr><td><span class='k'>{i + 1}. {E.category_name(cat)}</span></td>"
        f"<td style='color:#ffffff; font-family: monospace'>{cards}</td><td class='m'>{tr(*desc)}</td></tr>"
        for i, (cat, cards, desc) in enumerate(RANKING))
    return f"<table class='rank' cellspacing='0'>{rows}</table>"


def _blinds_html() -> str:
    levels = " · ".join(f"{sb}/{bb}" for sb, bb, _ante in ai.BLIND_LEVELS[:12])
    return tr(f"Níveis de blinds (sobem a cada {ai.HANDS_PER_LEVEL} mãos do torneio): {levels}…",
              f"Blind levels (going up every {ai.HANDS_PER_LEVEL} tournament hands): {levels}…")


def _rounds_html() -> str:
    parts = [f"{ai.difficulty_name(d)}: <span class='k'>{ai.tournament_rounds(d)}</span>" for d in ai.DIFFICULTIES]
    return " · ".join(parts)


def help_html() -> str:
    pt = f"""
<h2>1. O objetivo</h2>
<p>No Texas Hold'em você ganha fichas vencendo <span class='k'>potes</span> — a soma das apostas de uma mão. Há duas
formas de vencer um pote: ter a <span class='k'>melhor mão no showdown</span> (quando as cartas são mostradas no fim)
ou fazer todos os outros <span class='k'>desistirem</span> antes disso.</p>

<h2>2. As cartas</h2>
<ul>
<li>Cada jogador recebe <span class='k'>2 cartas fechadas</span>, só dele.</li>
<li>Na mesa saem até <span class='k'>5 cartas comunitárias</span>, que valem para todos: 3 no <span class='k'>flop</span>,
1 no <span class='k'>turn</span> e 1 no <span class='k'>river</span>.</li>
<li>Sua mão é a <span class='k'>melhor combinação de 5 cartas</span> entre as 7 disponíveis (suas 2 + as 5 da mesa). Vale
usar as duas, uma ou nenhuma das suas cartas.</li>
</ul>

<h2>3. Botão e blinds</h2>
<p>O <span class='k'>botão</span> (D) marca quem "dá as cartas" e gira uma posição a cada mão. Os dois jogadores à
esquerda dele põem apostas obrigatórias antes das cartas: o <span class='k'>small blind</span> (SB, meia aposta) e o
<span class='k'>big blind</span> (BB, aposta inteira). Os blinds garantem que sempre haja algo em disputa.</p>

<h2>4. As rodadas de apostas</h2>
<ol>
<li><span class='k'>Pré-flop</span>: depois das 2 cartas de cada um. Começa quem está à esquerda do big blind.</li>
<li><span class='k'>Flop</span>: saem 3 cartas na mesa. Daqui em diante começa o primeiro jogador ainda na mão à esquerda do botão.</li>
<li><span class='k'>Turn</span>: sai a 4ª carta.</li>
<li><span class='k'>River</span>: sai a 5ª carta. Depois da última aposta, quem continua mostra as cartas (showdown).</li>
</ol>
<p>Uma rodada termina quando todos os que continuam na mão colocaram o mesmo valor (ou estão all-in).</p>

<h2>5. As ações</h2>
<ul>
<li><span class='k'>Desistir</span> (fold): larga a mão e perde o que já apostou nela.</li>
<li><span class='k'>Passar</span> (check): segue sem apostar — só quando ninguém apostou na rodada.</li>
<li><span class='k'>Pagar</span> (call): iguala a maior aposta da rodada.</li>
<li><span class='k'>Apostar</span> (bet): faz a primeira aposta da rodada (no mínimo um big blind).</li>
<li><span class='k'>Aumentar</span> (raise): sobe uma aposta que já existe. O aumento mínimo é do tamanho do último aumento.</li>
<li><span class='k'>All-in</span>: aposta todas as suas fichas. No No-Limit não há teto: dá para apostar tudo a qualquer momento.</li>
</ul>

<h2>6. Ranking das mãos</h2>
<p>Da mais forte para a mais fraca:</p>
{_ranking_html()}
<h3>Desempates</h3>
<ul>
<li>Na mesma categoria, vence a de cartas mais altas: um par de Reis vence um par de Damas.</li>
<li>Com o mesmo par (ou trinca), decide o <span class='k'>kicker</span> — a carta mais alta que sobra: A-A-K vence A-A-Q.</li>
<li>Naipes não têm valor. Se as 5 melhores cartas forem iguais, o pote é <span class='k'>dividido</span>.</li>
<li>Se a melhor mão está toda na mesa, todos a têm e o pote é dividido entre quem continuou.</li>
</ul>

<h2>7. All-in e potes paralelos</h2>
<p>Quem vai all-in só pode ganhar, de cada adversário, o quanto apostou. Se outros continuam apostando, as fichas extras
formam um <span class='k'>pote paralelo</span>, disputado só por quem colocou fichas nele. No app isso é automático.</p>

<h2>8. Cash game</h2>
<ul>
<li>Blinds fixos de <span class='k'>5/10</span> e <span class='k'>1000 fichas</span> (100 big blinds) para cada um.</li>
<li>Quebrou? Clique em <span class='k'>Recomprar</span> e continue. Bots que quebram dão lugar a novos jogadores.</li>
<li>A dificuldade dos bots e o número de oponentes ficam em Configurações (ou no 👥 da mesa).</li>
</ul>

<h2>9. Torneio</h2>
<ul>
<li>Ao entrar, escolha a dificuldade. O número de rodadas depende dela: {_rounds_html()}.</li>
<li>Todos começam com <span class='k'>1000 fichas</span> (100 big blinds), sem recompra.</li>
<li>{_blinds_html()} A partir do 3º nível há <span class='k'>ante do big blind</span>: o big blind paga uma ante por
toda a mesa, que vai direto para o pote.</li>
<li>Quando <span class='k'>metade da mesa</span> é eliminada, quem sobrou passa de rodada e <span class='k'>leva as suas
fichas</span> para uma mesa nova (os adversários também são classificados, com stacks parecidos). O relógio dos blinds
continua.</li>
<li><span class='k'>Bolha</span>: quando falta uma eliminação para fechar a rodada, sobreviver vale mais que fichas.
Pague só com folga; com stack grande, pressione quem tem stack médio ou curto.</li>
<li>Na <span class='k'>mesa final</span> só há um vencedor: fique com todas as fichas para ganhar o título 🏆.</li>
<li>Se você cair, recebe a colocação geral no torneio (ex.: 13º de 96). Títulos e melhor colocação ficam salvos por dificuldade.</li>
</ul>

<h2>10. Treino de decisões</h2>
<ul>
<li>Escolha a rua (pré-flop, flop, turn ou river). Cada mão traz uma situação com <span class='k'>posição</span>,
<span class='k'>stack efetivo</span> e o que cada oponente fez; você decide <span class='k'>desistir</span>,
<span class='k'>passar/pagar</span> ou <span class='k'>apostar/aumentar</span> — e escolhe o tamanho.</li>
<li>Antes do flop: abrir depende da posição (tabela de aberturas); contra um aumento, conta a sua chance contra as mãos com
que aquele jogador aumenta, o preço e a posição.</li>
<li>Depois do flop: a sua chance é calculada contra as <span class='k'>mãos com que eles fariam o que fizeram</span> (quem
aposta tem mão melhor que quem passa). Pagar exige chance acima do preço (fora de posição um pouco mais; projetos com
stack fundo têm odds implícitas). Apostar ou aumentar por valor exige estar à frente das <span class='k'>mãos que
pagam</span>.</li>
<li>Nota: 100 pontos para a melhor jogada, 40–70 para uma jogada aceitável e 0 para um erro. A explicação aparece ao lado.</li>
<li>Veja a página <span class='k'>Dicas</span> para os atalhos de cálculo (pot odds, outs, referências pré-flop).</li>
</ul>

<h2>11. Controles</h2>
<ul>
<li><span class='k'>F</span> desistir · <span class='k'>C</span> passar/pagar · <span class='k'>R</span> apostar/aumentar ·
<span class='k'>Enter</span> ou <span class='k'>S</span> próxima mão.</li>
<li>Na mesa: atalhos de aposta (⅓, ½, ¾, pote, all-in), pré-ações enquanto os outros jogam, <span class='k'>P</span> pausa,
velocidade dos bots, ⏭ <span class='k'>S</span> pula o resto da jogada dos bots quando você já saiu, 🔁 próxima mão
automática e ☰ Menu / Histórico recolhem o menu lateral e o histórico para a mesa ficar maior.</li>
<li>Pré-ações (enquanto os outros jogam): <span class='k'>F</span> passar/desistir · <span class='k'>C</span> passar · <span class='k'>A</span> pagar qualquer — aperte de novo para desmarcar.</li>
<li><span class='k'>Espaço</span> (ou Enter) vai para a próxima mão quando a mão termina.</li>
<li><span class='k'>bb</span> mostra stacks e apostas em big blinds. No showdown, quem perde pode descartar a mão sem mostrar
(opção em Configurações para ver tudo no modo aprendizado). O histórico das suas mãos pode ser exportado no formato do
PokerStars em Estatísticas.</li>
<li>Embaixo de cada jogador aparece a última ação: <span style='color:#3ddc84'><b>passou</b></span>,
<span style='color:#f5c542'><b>apostou/aumentou</b></span>, <span style='color:#7f8c88'><b>desistiu</b></span> (com o nome apagado).</li>
</ul>
"""
    en = f"""
<h2>1. The goal</h2>
<p>In Texas Hold'em you win chips by winning <span class='k'>pots</span> — the sum of the bets in a hand. There are two
ways to win a pot: have the <span class='k'>best hand at showdown</span> (when cards are shown at the end) or make
everyone else <span class='k'>fold</span> before that.</p>

<h2>2. The cards</h2>
<ul>
<li>Each player gets <span class='k'>2 face-down cards</span> of their own.</li>
<li>Up to <span class='k'>5 community cards</span> are dealt on the board, shared by everyone: 3 on the
<span class='k'>flop</span>, 1 on the <span class='k'>turn</span> and 1 on the <span class='k'>river</span>.</li>
<li>Your hand is the <span class='k'>best 5-card combination</span> out of the 7 available (your 2 + the 5 on the board).
You may use both, one or none of your own cards.</li>
</ul>

<h2>3. Button and blinds</h2>
<p>The <span class='k'>button</span> (D) marks the "dealer" and moves one seat every hand. The two players to its left
post forced bets before the cards: the <span class='k'>small blind</span> (SB, half a bet) and the
<span class='k'>big blind</span> (BB, a full bet). Blinds make sure there is always something to play for.</p>

<h2>4. The betting rounds</h2>
<ol>
<li><span class='k'>Pre-flop</span>: after everyone gets 2 cards. The player left of the big blind acts first.</li>
<li><span class='k'>Flop</span>: 3 cards hit the board. From now on, the first player still in the hand left of the button acts first.</li>
<li><span class='k'>Turn</span>: the 4th card.</li>
<li><span class='k'>River</span>: the 5th card. After the last bet, whoever is left shows their cards (showdown).</li>
</ol>
<p>A round ends when everyone still in the hand has put in the same amount (or is all-in).</p>

<h2>5. The actions</h2>
<ul>
<li><span class='k'>Fold</span>: give up the hand and lose what you've already bet in it.</li>
<li><span class='k'>Check</span>: pass without betting — only when nobody has bet this round.</li>
<li><span class='k'>Call</span>: match the highest bet of the round.</li>
<li><span class='k'>Bet</span>: make the first bet of the round (at least one big blind).</li>
<li><span class='k'>Raise</span>: increase an existing bet. The minimum raise is the size of the last raise.</li>
<li><span class='k'>All-in</span>: bet all your chips. In No-Limit there's no cap: you can bet everything at any time.</li>
</ul>

<h2>6. Hand rankings</h2>
<p>From strongest to weakest:</p>
{_ranking_html()}
<h3>Ties</h3>
<ul>
<li>Within the same category, higher cards win: a pair of Kings beats a pair of Queens.</li>
<li>With the same pair (or trips), the <span class='k'>kicker</span> — the highest remaining card — decides: A-A-K beats A-A-Q.</li>
<li>Suits have no value. If the best 5 cards are the same, the pot is <span class='k'>split</span>.</li>
<li>If the best hand is all on the board, everyone has it and the pot is split among those still in.</li>
</ul>

<h2>7. All-in and side pots</h2>
<p>An all-in player can only win from each opponent as much as they put in. If others keep betting, the extra chips form
a <span class='k'>side pot</span>, contested only by those who put chips in it. The app handles this automatically.</p>

<h2>8. Cash game</h2>
<ul>
<li>Fixed blinds of <span class='k'>5/10</span> and <span class='k'>1000 chips</span> (100 big blinds) each.</li>
<li>Went broke? Click <span class='k'>Rebuy</span> and keep playing. Bots that go broke are replaced by new players.</li>
<li>Bot difficulty and the number of opponents are in Settings (or 👥 at the table).</li>
</ul>

<h2>9. Tournament</h2>
<ul>
<li>When you enter, pick a difficulty. The number of rounds depends on it: {_rounds_html()}.</li>
<li>Everyone starts with <span class='k'>1000 chips</span> (100 big blinds), no rebuys.</li>
<li>{_blinds_html()} From level 3 there's a <span class='k'>big blind ante</span>: the big blind posts one ante for the
whole table, straight into the pot.</li>
<li>Once <span class='k'>half the table</span> is knocked out, the survivors advance and <span class='k'>carry their
chips</span> to a new table (the opponents are qualifiers too, with similar stacks). The blind clock keeps running.</li>
<li><span class='k'>Bubble</span>: when one knockout is left to close the round, surviving is worth more than chips.
Call only with a margin; with a big stack, pressure the medium and short stacks.</li>
<li>The <span class='k'>final table</span> has a single winner: take all the chips to win the title 🏆.</li>
<li>If you're knocked out, you get your overall place (e.g. #13 of 96). Titles and best place are saved per difficulty.</li>
</ul>

<h2>10. Decision training</h2>
<ul>
<li>Pick a street (pre-flop, flop, turn or river). Every hand shows a spot with <span class='k'>position</span>,
<span class='k'>effective stack</span> and what each opponent did; you decide <span class='k'>fold</span>,
<span class='k'>check/call</span> or <span class='k'>bet/raise</span> — and pick the size.</li>
<li>Pre-flop: opening depends on position (opening chart); against a raise, what counts is your chance against the hands
that player raises with, the price and your position.</li>
<li>Post-flop: your chance is computed against the <span class='k'>hands they'd play this way</span> (a bettor has a
stronger range than a checker). Calling needs a chance above the price (a bit more out of position; draws with deep
stacks get implied odds). Betting or raising for value needs you to be ahead of the <span class='k'>hands that
call</span>.</li>
<li>Score: 100 points for the best play, 40–70 for an acceptable play and 0 for a mistake. The explanation shows up on the side.</li>
<li>See the <span class='k'>Tips</span> page for calculation shortcuts (pot odds, outs, pre-flop benchmarks).</li>
</ul>

<h2>11. Controls</h2>
<ul>
<li><span class='k'>F</span> fold · <span class='k'>C</span> check/call · <span class='k'>R</span> bet/raise ·
<span class='k'>Enter</span> or <span class='k'>S</span> next hand.</li>
<li>At the table: bet shortcuts (⅓, ½, ¾, pot, all-in), pre-actions while others play, <span class='k'>P</span> pause,
bot speed, ⏭ <span class='k'>S</span> skips the rest of the bots' play once you're out, 🔁 automatic next hand
and ☰ Menu / History collapse the side menu and the history to make the table bigger.</li>
<li>Pre-actions (while others play): <span class='k'>F</span> check/fold · <span class='k'>C</span> check · <span class='k'>A</span> call any — press again to clear.</li>
<li><span class='k'>Space</span> (or Enter) goes to the next hand once the hand is over.</li>
<li><span class='k'>bb</span> shows stacks and bets in big blinds. At showdown, a losing player can muck without showing
(an option in Settings shows everything in learning mode). Your hand history can be exported in PokerStars format from
Stats.</li>
<li>Under each player you see their last action: <span style='color:#3ddc84'><b>checked</b></span>,
<span style='color:#f5c542'><b>bet/raised</b></span>, <span style='color:#7f8c88'><b>folded</b></span> (with the name faded).</li>
</ul>
"""
    return CSS + pick(pt, en)


class HelpPage(QWidget):
    closeRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from pokertrainer.gui.pages import _page_shell
        page, v = _page_shell(tr("Como jogar", "How to play"),
                              tr("As regras do Texas Hold'em No-Limit e de cada modo do app.",
                                 "The rules of No-Limit Texas Hold'em and of each mode in the app."),
                              on_close=self.closeRequested.emit)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(help_html())
        v.addWidget(self.browser, 1)
