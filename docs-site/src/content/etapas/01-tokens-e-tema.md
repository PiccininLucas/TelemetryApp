---
titulo: Tokens e tema
resumo: Estruturar cores, tipografia e espaçamento em tokens e centralizar todo o estilo no tema.
ordem: 1
status: em-andamento
risco: baixo
arquivos:
  - lmu_telemetry/presentation/theme.py
  - lmu_telemetry/presentation/chart_panel.py
  - lmu_telemetry/presentation/corner_table.py
  - lmu_telemetry/presentation/session_browser.py
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
2. Definir família tipográfica, escala de tamanhos e espaçamentos. **Parcial.** Famílias e espaçamento dos controles estão na paleta; falta uma escala de tamanhos formal (hoje 13 px no corpo e 12 px nos títulos).
3. Mover para o tema todo estilo espalhado nos painéis. **Parcial.** Fundo dos gráficos e preenchimentos azuis agora vêm do tema. Ainda fora dele: spans HTML do `chart_panel.py`, as cores de célula do `corner_table.py` e a fonte em negrito do `session_browser.py`.
4. ~~Ampliar o QSS~~ **Feito.** Docks, barra de ferramentas, abas (sublinhado), árvores e tabelas, combos, botões, barras de rolagem, menus e dicas.
5. ~~Trocar tema claro/escuro~~ **Descartado** na etapa 0: só escuro.

## Critério de pronto

- Nenhum literal de cor fora de `theme.py`. **Não atingido:** restam as cores de dado do mapa (`track_map.py`) e as células da tabela.
- `pyqtgraph` e widgets Qt leem os mesmos tokens. **Feito.**
- Contraste mínimo de 4,5:1 para texto normal. **Feito e testado** (`tests/test_theme.py`).
- O par referência/comparação continua distinguível por daltonismo. **Parcial.** O par é o azul/laranja, o clássico seguro, e o teste garante que as matizes ficam afastadas. Não há simulação de daltonismo.

## Riscos

`pyqtgraph` lê as opções globais na criação do widget: o tema precisa ser aplicado antes de qualquer gráfico existir.

## Decisões

- Tema: só escuro, refinado, sem alternância (etapa 0).
- Direção Violeta, com fontes do sistema em vez de embutidas. Se o app for distribuído para outros sistemas, vale reavaliar embutir uma família.

## Decisões em aberto

- Escala tipográfica formal.
- Mover as cores de dado restantes para o tema.
