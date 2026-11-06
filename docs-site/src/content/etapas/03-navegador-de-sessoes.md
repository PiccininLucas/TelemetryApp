---
titulo: Navegador de sessões
resumo: Melhorar a árvore pista > carro > sessão > volta com busca, filtros e leitura mais clara.
ordem: 3
status: pendente
risco: baixo
arquivos:
  - lmu_telemetry/presentation/session_browser.py
  - lmu_telemetry/shared/strings.py
---

## Escopo

`SessionBrowser` lê só o catálogo e emite `LapSelection`. Voltas parciais, inválidas e de box aparecem esmaecidas.

## Tarefas

1. Campo de busca e filtros (pista, carro, tipo de sessão).
2. Destacar a melhor volta de cada sessão e a volta fixada como referência.
3. Estado vazio com chamada para importar sessão.
4. Navegação completa por teclado.

## Critério de pronto

- Seleção padrão preservada (volta mais recente, nunca a mais curta).
- Continua funcionando com catálogo ilegível ou vazio (testes existentes).

## Decisões em aberto

- Manter árvore ou trocar por lista com agrupamento?
