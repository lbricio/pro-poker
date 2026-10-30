# Pro Poker Trainer

<img width="1624" height="969" alt="image" src="https://github.com/user-attachments/assets/33ec1870-da63-4ad1-806f-2084e3a531fb" />


Simulador instrutivo de probabilidades de mãos de Texas Hold'em, para macOS e Linux (Python + PySide6).

Você recebe uma mão, arrasta a barra até o seu palpite da chance de vencer e o app mostra a probabilidade
real (calculada por simulação), as cartas dos oponentes, o resto da mesa e uma explicação da mão.

## Como rodar

```bash
uv sync
uv run pokertrainer        # ou: uv run python -m pokertrainer
```

## Modos

| Modo     | O que você vê                 |
|----------|-------------------------------|
| Pré-flop | só as 2 cartas da mão          |
| Flop     | 2 cartas + 3 cartas da mesa    |
| Turn     | 2 cartas + 4 cartas da mesa    |
| Pot odds | flop ou turn com uma aposta: estime a chance e decida pagar ou desistir |
| Jogar    | partida completa (No-Limit Hold'em, blinds 5/10, 1000 fichas) contra bots |

A "chance de vencer" é a **equidade**: vitórias contam 100% e empates dividem o pote. Ela é calculada contra
oponentes com cartas aleatórias, até o river, por Monte Carlo (50 mil simulações por padrão, margem de ±0,5 ponto).

**Barra de palpite na escala do cenário:** a barra vai da pior à melhor mão possível naquele modo com aquele
número de jogadores e começa na chance média (100% ÷ jogadores; ex.: 5 na mesa → 20%), marcada com uma linha
dourada. As barrinhas claras acima dela mostram quão comum é cada chance, para dar noção do que é muito ou
pouco provável. No pré-flop os limites são exatos (ex.: com 4 oponentes, de 32o ≈ 11% a AA ≈ 56%); no flop e
no turn o máximo é 100% (dá para ter a mão imbatível) e o mínimo é estimado por simulação.

**Oponentes:** acima das cartas, o botão "N OPONENTES" escolhe de 1 a 9 oponentes e o botão "🎲 Aleatório"
sorteia o número de oponentes a cada mão (a barra se ajusta ao cenário sorteado).

**Pot odds:** o oponente 1 aposta (os demais pagam) e você decide pagar ou desistir. A barra mostra a chance
mínima para pagar (aposta ÷ pote final) e o app diz se a decisão foi certa e quanto pagar vale em média (EV).

**Faixa dos oponentes (ranges):** "Faixa: …" acima das cartas (ou em Configurações) faz os oponentes jogarem só
o top 50/30/15/8% das mãos iniciais, em vez de mãos aleatórias. As dicas comparam a chance contra a faixa com a
chance contra mãos aleatórias. Contra faixas a barra usa a escala de 0 a 100%.

**Estatísticas e revisão:** gráfico do erro por mão com média móvel, tendência (superestima/subestima), erro por
tipo de mão, decisões e EV no pot odds, e as últimas mãos — dois cliques reabrem a mão na mesa para revisar.
"Treinar meu ponto fraco" (ou dois cliques num tipo de mão) distribui só mãos desse tipo até você clicar no ✕.

**Modos de jogo (Cash game e Torneio):** mesa oval com 1 a 9 bots. Você desiste, passa/paga ou aposta/aumenta (atalhos ½ pote,
¾, pote, all-in; teclas F, C e R). A cada aposta que você enfrenta, o app mostra as pot odds e, depois, se a
decisão fez sentido (🎓 no histórico da mão). Há potes paralelos (all-in de stacks diferentes), recompra quando
você quebra, e bots que quebram dão lugar a novos jogadores. Em Configurações: dificuldade (Fácil, Médio, Difícil,
Semi-pro, Pro), velocidade dos bots, assistente de chance e "modo aprendizado" (mostra a personalidade, o humor e,
no fim da mão, quem blefou).

A mesa é animada: as apostas ficam em fichas na frente de cada jogador e vão para o pote no fim de cada rua; o
pote voa para o vencedor ("+340"); as cartas da mesa saem rua a rua; num all-in sem mais apostas, todos mostram as
cartas e a mesa é "corrida" devagar; no showdown as 5 cartas vencedoras ficam em destaque. Os bots "pensam" por um
tempo que depende da decisão (all-ins e apostas grandes demoram mais) e às vezes falam (balões), conforme a
personalidade e o humor. Controles: ⏸ pausar (P), velocidade (🐢/▶/⏩), ⏭ pular o resto da mão quando você já
saiu, 🔁 próxima mão automática, e pré-ações (passar/desistir, passar, pagar qualquer) enquanto os outros jogam.
O menu separa os **modos de treino** (Pré-flop, Flop, Turn, Pot odds) dos **modos de jogo**:

- **Cash game**: recompra à vontade; bots quebrados são substituídos.
- **Torneio**: rodadas eliminatórias, sem recompra — **3 rodadas** no Fácil e no Médio, **5** no Difícil e no
  Semi-pro, **6** no Pro. Cada rodada é uma mesa nova (todos com 1000 fichas, blinds começando em 5/10 e subindo a
  cada 10 mãos); quando metade da mesa é eliminada, os sobreviventes passam de rodada. Na **mesa final** é preciso
  ficar com todas as fichas. Quem cai recebe a colocação geral (ex.: "13º lugar de 16"); o número de jogadores do
  torneio é o tamanho da mesa × 2^(rodadas − 1).

**Suas estatísticas (HUD):** no seu assento aparecem VPIP, PFR e AF da partida (passe o mouse para ver todas), e o
painel lateral mostra "Seu perfil nesta partida" com avaliação de cada número. Tudo é acumulado entre partidas em
**Estatísticas → Jogo simulado**: mãos, lucro, bb/100, mãos vencidas, decisões certas, torneios, a curva de lucro
em big blinds e o perfil completo — VPIP, PFR, 3-bet, AF, c-bet, desiste diante de aposta, WTSD e W$SD —
comparado com as faixas de um jogador sólido, com o seu estilo (TAG, LAG, calling station…) e sugestões.

Cada bot tem uma personalidade sorteada a partir de um estilo — amadores: **Recreativo** (joga muitas mãos e só
paga), **Paga-tudo** (calling station), **Maníaco**, **Conservador** (aposta pouco e só entra com 50%+ de chance)
e **Blefador**; e jogadores de verdade: **Retranqueiro**, **Sólido e agressivo (TAG)**, **Solto e agressivo (LAG)**,
**Regular** e **Profissional** — com traços de 0 a 100%: agressividade, seletividade, blefe, all-in, "paga
demais", slowplay e propensão a tilt. A dificuldade segue a composição de mesas reais: os amadores são ~73% no
Fácil, ~46% no Médio, ~24% no Difícil e raros no Semi-pro (~10%) e no Pro (~7%). Quanto maior a habilidade, menos
erros grosseiros (de ~10% das decisões no Fácil a quase 0 no Pro), traços mais perto do jogo sólido e mais leitura
dos adversários. Em simulações com ~720 mil mãos-jogador, o ganho cresce com a dificuldade (Fácil −175, Médio −99,
Difícil +32, Semi-pro +44, Pro +83 bb/100 em mesas mistas) e os estilos amadores perdem. O humor muda com o jogo
(tilt 😤, confiança 😎) e as decisões têm uma dose de acaso. Na mesa, cada bot mostra "VPIP/PFR · estilo"; passe o
mouse para ver tudo (e, no modo aprendizado, a personalidade e como jogar contra ela).

**Leitura de faixa (Pro):** os bots de habilidade alta (a partir de ~0,80, sobretudo no nível Pro), diante de uma
aposta depois do flop, estimam com que mãos aquele jogador apostaria naquela mesa — mãos fortes quase sempre, pares e
projetos às vezes, blefes conforme a desconfiança e a agressividade observadas — e misturam essa estimativa (até
60%) à própria leitura. Num teste A/B com bots Pro nas mesmas mesas, quem usa a leitura ganhou ~+11 bb/100 contra
~−13 de quem não usa.

**👑 Campeão (só no nível Pro, ~6% dos bots):** joga de forma **equilibrada** — perto do jogo teórico, difícil de
ler e de explorar —, executada com a maior competência: habilidade máxima, nenhum erro grosseiro, praticamente imune
a tilt e sem "pressão por impulso". Depois do flop ele estima com que mãos cada adversário apostaria ou pagaria
naquela mesa (mão forte, par alto, par fraco, projeto, nada) e decide em cima disso; o tamanho da aposta é sorteado
(⅓, ⅔ ou pote) e não depende da força da mão; blefa na proporção equilibrada para o tamanho (~1/3 das apostas),
semiblefa com projetos, às vezes passa com mãos fortes e não desiste demais diante de apostas. Usa as leituras da
mesa só de leve (explorar demais o tornaria previsível). Em simulação contra mesas de profissionais ele ganha
~+200 bb/100 (os profissionais ficam em −40); contra mesas fáceis, ~+500.

**Pressão, medo de quebrar e caça aos curtos:** do Difícil para cima, bots agressivos ou confiantes (😎) tendem a
aumentar o pote seguidamente (os muito habilidosos, ~0,9+, não fazem isso por impulso: só apostam quando a mão ou a
leitura pede) — re-aumentos antes do flop, apostas rua após rua e re-aumentos com mãos médias, com
tamanhos maiores quando há vários jogadores — para tirar os outros da mão. Quando o stack fica curto (menos de ~25
big blinds), estilos medrosos (conservador, retranqueiro, recreativo) e jogadores fracos encolhem: apostam menos,
largam mais e esperam uma mão premium; profissionais quase não fazem isso (sabem que é hora de empurrar). E quem
cobre com folga um jogador curto tenta eliminá-lo: isola, paga mais leve o all-in dele e aposta o suficiente para
colocá-lo all-in — sobretudo os agressivos (LAG, maníaco, blefador) e os habilidosos.

**Sons:** fichas (pagar, apostar, all-in), batida na mesa (passar), cartas (dar, virar, desistir), pote indo ao
vencedor, vitória e um aviso na sua vez. Ligue/desligue no 🔊 da mesa ou em Configurações (com volume). Os sons são
sintetizados por `tools/make_sounds.py` e tocados pelo reprodutor do sistema (afplay no macOS, paplay/aplay no
Linux), sem dependências extras.

**Memória dos bots (medo e desconfiança):** cada bot guarda uma leitura individual de cada outro jogador da mesa
— você e os outros bots — com dois indicadores: **😨 medo** (respeita as apostas dele: mostrou mão forte quando
apostou, joga poucas mãos) e **🤨 desconfiança** (acha que ele blefa: foi visto mostrando mão fraca depois de
apostar, aposta e aumenta demais). Eles aprendem só com o que estaria à vista numa mesa real (showdowns e o estilo
observado); quem não estava na mão às vezes se distrai e não presta atenção. Na hora de decidir, a desconfiança faz
pagar mais leve contra aquele jogador e o medo faz largar mais. Para não ser fácil de manipular: cada bot só muda de
opinião aos poucos (um blefe mostrado move a desconfiança de um profissional em poucos pontos; um padrão repetido
convence), padrões de longo prazo pesam mais que uma jogada isolada, o efeito nas decisões tem teto e é aplicado
com variação, e a memória vai sendo esquecida (amadores esquecem rápido; profissionais lembram por mais tempo). A
intensidade cresce com a dificuldade e a reação depende do estilo: o retranqueiro e o conservador se assustam com
uma mão forte mostrada, o maníaco e o blefador acham que todo mundo blefa, o paga-tudo liga pouco (paga de qualquer
jeito). O peso da memória nas decisões vai de ~20% (Fácil) a no máximo 70% (Pro) — o resto fica para o jogo e o
acaso, com um fator aleatório em cada decisão. No modo aprendizado, cada bot mostra na mesa
"você: 😨 x% · 🤨 y%", o histórico avisa quando alguém viu seu blefe ou sua mão forte, a dica (mouse) mostra o que
ele pensa de cada jogador, e o painel lateral mostra a sua imagem média na mesa.

O número de oponentes do modo Jogar é separado do dos modos de treino: botão 👥 na mesa ou Configurações → Jogo
simulado → Oponentes na mesa.

**Cartas restantes:** ao lado da sua mão, a pilha de cartas mostra quantas cartas ainda não foram vistas; ao
clicar, abre o baralho inteiro com as cartas já conhecidas (sua mão e mesa; depois da revelação, também as dos
oponentes) apagadas.

**Idioma:** 🇧🇷 PT/BR ou 🇺🇸 ENG, no canto superior direito (as bandeiras são desenhadas pelo app). A troca reabre a mesma mão no novo idioma.

**Teclado:** ← → ajustam o palpite (Shift = 5 pontos), a roda do mouse também funciona, Enter confirma ou passa
para a próxima mão e Esc volta.

## Telas

- **Menu lateral:** os modos de jogo. Durante a partida ele passa a mostrar a pontuação, o erro médio, os acertos
  e a análise da última mão (vitória/empate, distribuição da sua mão final, outs, regra do 2 e do 4 e dicas).
- **Tabela de probabilidades:** grade 13×13 das 169 mãos iniciais contra 1 a 9 oponentes, tabela de outs e
  ranking de mãos com a chance de cada uma.
- **Dicas:** como estimar a chance de vencer sem calculadora.
- **Configurações:** número de oponentes (fixo ou aleatório), precisão, margem de acerto, desfoque do fundo, nome da mão e animações.

## Estrutura

```
pokertrainer/
  engine.py         avaliador de mãos (tabela de produto de primos) + Monte Carlo + outs + faixas
  table.py          mesa de No-Limit Hold'em (apostas, all-in, potes paralelos, showdown)
  ai.py             bots: personalidade, humor/tilt, dificuldade e decisões
  coach.py          nota do palpite, explicações, tabelas de referência
  settings.py       preferências e estatísticas (QSettings)
  gui/              janela, menu lateral, tela de jogo, páginas, componentes
  assets/           cartas PNG, fundo, tabela pré-flop pré-calculada
tools/
  fetch_assets.py          baixa e gera as imagens (cartas a partir de SVG, verso, fundo)
  build_preflop_table.py   recalcula assets/preflop_equity.json
  build_scenarios.py       recalcula assets/scenarios.json (limites e distribuição da barra)
  make_sounds.py           gera os sons (assets/sounds/*.wav)
tests/
```

```bash
uv run pytest                                  # testes
uv run python tools/fetch_assets.py            # baixa as imagens de novo
uv run python tools/build_preflop_table.py     # recalcula a tabela pré-flop (~2 min)
uv run python tools/build_scenarios.py         # recalcula a escala da barra (rodar depois da tabela)
```

## Créditos

- Cartas: [playing-cards-assets](https://github.com/hayeah/playing-cards-assets), de Howard Yeh (licença MIT),
  convertidas de SVG para PNG de 480 px.
- Fundo: "[World Poker Tour table 3](https://commons.wikimedia.org/wiki/File:World_Poker_Tour_table_3.jpg)", do
  World Poker Tour, Wikimedia Commons, CC BY 3.0 (desfocado no app).
- O verso da carta é desenhado por `tools/fetch_assets.py`.
