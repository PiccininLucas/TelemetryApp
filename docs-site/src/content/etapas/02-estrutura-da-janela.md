---
titulo: Estrutura da janela
resumo: Reorganizar o layout principal e quebrar o main_window.py em partes menores.
ordem: 2
status: em-andamento
risco: alto
arquivos:
  - lmu_telemetry/presentation/main_window.py
  - lmu_telemetry/shared/strings.py
---

## Escopo

O layout atual é de três colunas fixas em `QSplitter` com uma `QTabWidget` interna, tudo montado em
`MainWindow._build` (arquivo de 1263 linhas, também com menus, estado e exportação).

## Tarefas

1. Extrair de `main_window.py`: **parcial.** `ImportWorker` e o estado de sessão (`SessionPool`, `OpenSession`, `CurrentView`, `ComparisonMode`) saíram para `import_worker.py` e `session_state.py`. Menus, exportação e o fluxo de análise de volta ainda estão no `main_window.py` (1132 linhas).
2. ~~Avaliar `QDockWidget`~~ **Feito.** Navegador, mapa, g-g e curvas/consistência são docks: podem ser escondidos, movidos, agrupados em abas ou flutuar. `Painéis ▸ Restaurar layout padrão` desfaz.
3. ~~Barra de ferramentas~~ **Feita.** Importar, atualizar, modo de comparação, fixar referência, eixo X e exportar PNG/PDF, com rótulos curtos. Reaproveita as mesmas ações dos menus.
4. ~~Persistir geometria e visibilidade~~ **Feito.** `QSettings`, com versão do layout; um estado salvo incompatível cai no layout padrão.
5. Revisar a barra de status e o banner de aviso. **Pendente**, depende da referência visual (etapa 1).
7. ~~Layout padrão mais completo~~ **Feito (07/11/2026).** Cabeçalho de resumo da sessão no topo
   (`session_header.py`), lista de voltas com setores sob o navegador (`lap_list.py`), cartão da
   curva selecionada (`corner_detail.py`) entre a tabela de curvas e a consistência, e curvas
   numeradas (T1..Tn) no mapa e nos gráficos. `LAYOUT_STATE_VERSION` passou a 2.
6. ~~Quitar a dívida de arquitetura~~ **Feito.** `main_window.py` e `session_browser.py` não importam mais `infrastructure`: recebem `Gateways` (portas em `application/ports.py`) montados por `composition.py` a partir de `main.py`. A lista de dívida do `tests/test_architecture.py` foi removida.

## Critério de pronto

- `main_window.py` reduzido a composição e ligação de sinais. **Não atingido ainda:** faltam menus e exportação.
- Os sinais continuam os mesmos (ver Diagnóstico), em especial o cursor compartilhado.
- Todos os textos novos entram em `strings.py`.

## Riscos

É a etapa de maior impacto: mexe na ligação entre todos os painéis. Fazer em passos pequenos, com `tests/test_ui.py` verde a cada passo.

## Decisões (07/11/2026)

| Pergunta | Decisão |
| --- | --- |
| Docks flutuantes ou layout fixo melhorado? | **Docks**, mantidos: tudo pode ser escondido, movido, agrupado ou flutuar. |
| Disposição padrão dos painéis | **Painel com cabeçalho**: resumo da sessão no topo; sessões sobre voltas à esquerda; gráficos no centro; mapa sobre g-g à direita; curvas, curva selecionada e consistência lado a lado na faixa de baixo, de largura total. |
| Conteúdo novo | Resumo da sessão, lista de voltas com setores, detalhe da curva selecionada, números das curvas no mapa e nos gráficos. |
