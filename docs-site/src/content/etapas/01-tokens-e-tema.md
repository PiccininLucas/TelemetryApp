---
titulo: Tokens e tema
resumo: Estruturar cores, tipografia e espaçamento em tokens e centralizar todo o estilo no tema.
ordem: 1
status: pendente
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

## Tarefas

1. Separar tokens em duas camadas: paleta (valores) e papéis (`primary`, `muted`, `danger`...), com os componentes usando só os papéis.
2. Definir família tipográfica, escala de tamanhos e espaçamentos (hoje só há `font-size: 13px`).
3. Mover para o tema todo estilo que está espalhado nos painéis.
4. Ampliar o QSS para botões, campos, combos, abas e barras de rolagem.
5. Se aprovado na etapa 0, preparar a troca de tema (claro/escuro) sem mudar os painéis.

## Critério de pronto

- Nenhum literal de cor fora de `theme.py`.
- `pyqtgraph` e widgets Qt leem os mesmos tokens.
- Contraste mínimo de 4,5:1 para texto normal.
- O par referência/comparação continua distinguível por daltonismo.

## Riscos

`pyqtgraph` lê as opções globais na criação do widget: o tema precisa ser aplicado antes de qualquer gráfico existir.

## Decisões

- Tema: só escuro, refinado, sem alternância (etapa 0).
- **Em espera:** a paleta e a tipografia dependem da referência visual que o usuário vai enviar.

## Decisões em aberto

- Paleta nova ou manter a atual? (depende da referência)
- Fonte embutida no app ou do sistema?
