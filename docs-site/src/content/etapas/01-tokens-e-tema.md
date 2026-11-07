---
titulo: Tokens e tema
resumo: Estruturar cores, tipografia e espaçamento em tokens e centralizar todo o estilo no tema.
ordem: 1
status: concluida
risco: baixo
arquivos:
  - lmu_telemetry/presentation/theme.py
  - lmu_telemetry/presentation/chart_panel.py
  - lmu_telemetry/presentation/corner_table.py
  - lmu_telemetry/presentation/session_browser.py
  - lmu_telemetry/presentation/track_map.py
  - lmu_telemetry/presentation/lap_list.py
  - lmu_telemetry/presentation/corner_detail.py
  - lmu_telemetry/presentation/session_header.py
  - lmu_telemetry/presentation/consistency_panel.py
  - tests/test_theme.py
---

## Escopo

Hoje `theme.py` tem constantes de cor soltas e um QSS global. Há estilo fora dele (spans HTML em
`chart_panel.py`, cores de célula em `corner_table.py`, fonte em negrito em `session_browser.py`).

## Direção escolhida: Violeta

Entre quatro propostas aplicadas ao app real (Violeta, Azul, Magenta e Grafite), a escolhida foi a **Violeta**: superfícies índigo quase pretas, painéis como cartões de borda fina separados por um vão, raio de 8 px e um único acento violeta.

![Janela principal com a direção Violeta](/violeta.png)

**A regra da identidade:** o acento da interface nunca é uma cor de dado. Azul, laranja, verde e vermelho já significam algo nos traçados; o violeta vive numa matiz que nenhum dado usa, então uma linha selecionada nunca se confunde com uma volta.

| Papel | Valor |
| --- | --- |
| Fundo da janela | `#0c0d14` |
| Painel (cartões, gráficos, tabelas) | `#141521` |
| Elevado (cabeçalhos, botões, menus) | `#1d1f30` |
| Borda | `#2a2c42` |
| Texto, texto secundário, desabilitado | `#e9eaf5`, `#9fa2bd`, `#5d6080` |
| Acento | `#8f7cff` |

Contrastes medidos sobre o painel: texto 15,1:1, texto secundário 7,2:1, acento 5,6:1 (mínimo AA: 4,5:1). O desabilitado fica em ~3:1, como esperado. Tipografia: Bahnschrift nos títulos e cabeçalhos, Segoe UI Variable no corpo, ambas do sistema, com famílias de reserva.

## Tarefas

1. ~~Separar tokens em duas camadas~~ **Feito.** `Palette` (ingredientes) e papéis semânticos (`BACKGROUND`, `SURFACE`, `ACCENT`, `PLOT_BACKGROUND`...). As cores dos dados ficam fora da paleta.
2. ~~Definir família tipográfica, escala de tamanhos e espaçamentos~~ **Feito (07/11/2026).** `TypeScale` na paleta, com seis passos em pixels: `micro` 10 (números das curvas no mapa), `caption` 11, `label` 12 (cabeçalhos e títulos), `body` 13, `stat` 15 e `title` 17. Todo `font-size` do QSS é um passo da escala; o texto que o pyqtgraph desenha usa `PLOT_TEXT_SIZE` ou `theme.font(passo)`.
3. ~~Mover para o tema todo estilo espalhado nos painéis~~ **Feito (07/11/2026).** Os painéis agora dizem o que um número *significa*, e o tema decide como ele aparece: `Tone` (ganho, perda, melhor, aviso, esmaecido). A regra "verde se melhor, vermelho se pior", antes repetida em quatro painéis com as cores de pedal, virou `theme.verdict`. Nos rótulos, o tom é uma propriedade dinâmica lida pelo QSS (`set_tone`), no lugar de `setStyleSheet` inline; nas células, uma cor de primeiro plano (`tone_colour`). A escala de perda do mapa (`LOSS_SCALE`), o negrito (`emphasised`), os spans HTML (`rich`) e o tom do aviso também foram para o tema. A aparência não mudou: a captura da janela com o demo é idêntica pixel a pixel à de antes.
4. ~~Ampliar o QSS~~ **Feito.** Docks, barra de ferramentas, abas (sublinhado), árvores e tabelas, combos, botões, barras de rolagem, menus e dicas.
5. ~~Trocar tema claro/escuro~~ **Descartado** na etapa 0: só escuro.

## Critério de pronto

- Nenhum literal de cor fora de `theme.py`. **Feito e testado:** `tests/test_theme.py` varre cada módulo de `presentation/` e falha com um literal de cor ou um `setStyleSheet`. A paleta de impressão de `infrastructure/export/` (papel branco) fica separada de propósito.
- `pyqtgraph` e widgets Qt leem os mesmos tokens. **Feito.**
- Contraste mínimo de 4,5:1 para texto normal. **Feito e testado** (`tests/test_theme.py`).
- O par referência/comparação continua distinguível por daltonismo. **Feito e testado.** Simulação de protanopia, deuteranopia e tritanopia (Machado 2009, severidade total): o par azul/laranja fica a ΔE 84 ou mais (CIE76) nas três, e o teste exige 40. O par ganho/perda cai para ~28 em protan/deutan, mas ali o sinal impresso (ou o lado do zero) é sempre a outra pista.

## Riscos

`pyqtgraph` lê as opções globais na criação do widget: o tema precisa ser aplicado antes de qualquer gráfico existir.

## Decisões

- Tema: só escuro, refinado, sem alternância (etapa 0).
- Direção Violeta, com fontes do sistema em vez de embutidas. Se o app for distribuído para outros sistemas, vale reavaliar embutir uma família.

- Escala tipográfica de seis passos em pixels, não em pontos: a interface é desenhada para tela e o pyqtgraph aceita px direto.
- Tons em vez de cores nos painéis: um painel nunca escolhe uma cor, só o significado.

## Fica para outras etapas

- O navegador destaca a melhor volta com o acento violeta, e a lista de voltas com o tom `BEST`. Unificar é a tarefa 2 da etapa 3.
- O mapa no modo perda/ganho usa vermelho/verde sem outra pista além da legenda. Rever junto com a etapa 4.
