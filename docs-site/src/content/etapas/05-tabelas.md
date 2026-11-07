---
titulo: Tabelas de curvas e consistência
resumo: Rever a tabela de curvas e o painel de consistência para leitura mais rápida.
ordem: 5
status: pendente
risco: medio
arquivos:
  - lmu_telemetry/presentation/corner_table.py
  - lmu_telemetry/presentation/consistency_panel.py
  - lmu_telemetry/shared/formatting.py
---

## Escopo

`CornerTable` mostra colunas condicionais (comparação e volta ideal) e permite renomear curvas. `ConsistencyPanel` mostra ranking por curva e gráfico volta a volta.

## Tarefas

1. Hierarquia visual: destacar a curva que mais custa tempo.
2. Agrupar colunas de comparação e de volta ideal com cabeçalho claro.
3. Padronizar formatação de tempo, diferença e velocidade em `formatting.py`.
4. Revisar o seletor de stint e de métrica do painel de consistência.

## Critério de pronto

- Linhas continuam na ordem da volta (sem ordenação).
- Nome de curva editável persiste no catálogo.
- Corte de aviso vindo da configuração (`ui.consistency.*`).

## Decisões (07/11/2026)

- Tabela e consistência passam a ser **painéis lado a lado** (docks `dock_corners` e
  `dock_consistency`), com o cartão da curva selecionada entre os dois.
- A coluna de nome da tabela de curvas deixou de esticar: todas as colunas têm a largura do
  conteúdo e a sobra vai para a última, para as medidas não saírem da área visível.
