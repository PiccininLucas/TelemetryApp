---
titulo: Gráficos e mapa
resumo: Atualizar o visual dos traçados, do mapa da pista e do diagrama g-g sem perder desempenho.
ordem: 4
status: pendente
risco: medio
arquivos:
  - lmu_telemetry/presentation/chart_panel.py
  - lmu_telemetry/presentation/track_map.py
  - lmu_telemetry/presentation/gg_panel.py
---

## Escopo

`ChartStack` empilha traçados num eixo X compartilhado; `TrackMap` e `FrictionPanel` usam pyqtgraph com proporção igual.

## Tarefas

1. Aplicar os novos tokens a eixos, grades, legendas e leitura do cursor.
2. Trocar o HTML do readout por componente estilizado pelo tema.
3. Revisar a seleção de linhas de canal (hoje alternadores no menu).
4. Rever o rótulo e a unidade de cada eixo.
5. Medir o tempo de redesenho antes e depois.

## Critério de pronto

- Volta completa de Le Mans continua fluida (teste existente de tamanho de volta).
- Cor nunca é a única pista: linha tracejada para comparação, lado do zero no delta.
- `AXIS_WIDTH` mantido para alinhar os gráficos.

## Riscos

Antialiasing está desligado de propósito. Qualquer efeito visual novo precisa de medição.

## Decisões em aberto

- Quais canais aparecem por padrão (hoje: velocidade, pedais e delta)?
