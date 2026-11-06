---
titulo: Testes e validação
resumo: Garantir que a remodelagem não quebra comportamento e criar uma rede de proteção visual.
ordem: 7
status: pendente
risco: medio
arquivos:
  - tests/test_ui.py
  - tests/test_architecture.py
  - .github/workflows/tests.yml
---

## Escopo

`tests/test_ui.py` tem 70 testes de comportamento (offscreen). Não há teste visual.

## Tarefas

1. Manter `pytest -q` verde a cada etapa.
2. Acrescentar testes para o que for criado (docks, persistência de layout, estados vazio/erro).
3. Avaliar captura de tela de referência (`QWidget.grab`) para os painéis principais.
4. Atualizar os screenshots de `docs/screenshots/` e do README.
5. Rodar a CI em Ubuntu e Windows, Python 3.13 e 3.14.

## Riscos

A plataforma offscreen não tem fontes: teste de pixel pode ser instável entre sistemas.

## Decisões em aberto

- Vale o custo de testes visuais ou basta checagem manual com screenshots?
