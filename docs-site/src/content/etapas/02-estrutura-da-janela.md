---
titulo: Estrutura da janela
resumo: Reorganizar o layout principal e quebrar o main_window.py em partes menores.
ordem: 2
status: pendente
risco: alto
arquivos:
  - lmu_telemetry/presentation/main_window.py
  - lmu_telemetry/shared/strings.py
---

## Escopo

O layout atual é de três colunas fixas em `QSplitter` com uma `QTabWidget` interna, tudo montado em
`MainWindow._build` (arquivo de 1263 linhas, também com menus, estado e exportação).

## Tarefas

1. Extrair de `main_window.py`: construção de menus, `SessionPool`/estado de sessão e exportação.
2. Avaliar `QDockWidget` para painéis que o usuário queira esconder, mover ou destacar.
3. Adicionar barra de ferramentas com as ações mais usadas (modo de comparação, eixo X, exportar).
4. Persistir geometria e visibilidade dos painéis entre execuções.
5. Revisar a barra de status e o banner de aviso.
6. Quitar a dívida de arquitetura: hoje `main_window.py` e `session_browser.py` importam `infrastructure` direto (catálogo, carga de sessão, exportação). Criar portas em `application/` e injetá-las a partir de `main.py`; a lista `PRESENTATION_INFRASTRUCTURE_DEBT` em `tests/test_architecture.py` deve esvaziar.

## Critério de pronto

- `main_window.py` reduzido a composição e ligação de sinais.
- Os sinais continuam os mesmos (ver Diagnóstico), em especial o cursor compartilhado.
- Todos os textos novos entram em `strings.py`.

## Riscos

É a etapa de maior impacto: mexe na ligação entre todos os painéis. Fazer em passos pequenos, com `tests/test_ui.py` verde a cada passo.

## Decisões em aberto

- Docks flutuantes ou layout fixo melhorado?
- Qual a disposição padrão dos painéis?
