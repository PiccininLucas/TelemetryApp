---
titulo: Estados, feedback e acessibilidade
resumo: Cobrir estados vazio, carregando e erro em todos os painéis e garantir uso por teclado.
ordem: 6
status: pendente
risco: baixo
arquivos:
  - lmu_telemetry/presentation/main_window.py
  - lmu_telemetry/shared/strings.py
  - lmu_telemetry/presentation/theme.py
---

## Escopo

Hoje há placeholders em alguns painéis e um banner âmbar para avisos. A importação roda em `QThread`, mas o feedback de progresso é mínimo.

## Tarefas

1. Estado vazio, de carregamento e de erro em cada painel.
2. Indicador de progresso da importação.
3. Ordem de tabulação, atalhos de teclado e foco visível.
4. Nomes acessíveis (`setAccessibleName`) nos widgets principais.
5. Mensagens de erro com causa e próximo passo, todas em `strings.py`.

## Critério de pronto

- Fluxo principal (importar, escolher volta, comparar, exportar) concluído só com teclado.
- Foco sempre visível, contraste mínimo 4,5:1.
