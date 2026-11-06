---
titulo: Objetivos e escopo
resumo: Definir o que a remodelagem precisa resolver, o que fica fora e como medir que deu certo.
ordem: 0
status: concluida
risco: baixo
arquivos: []
---

## Escopo

Esta etapa não toca em código. Fecha o alvo antes das demais.

## Decisões (06/11/2026)

| Pergunta | Decisão |
| --- | --- |
| Tecnologia da interface | **Continua desktop** (PySide6 + pyqtgraph). A remodelagem é de layout, tema e fluxo. |
| O que mais incomoda | **Visual/estética** e **organização do layout**. Fluxo de uso e dificuldade de manter o código não foram apontados. |
| Tema | **Só escuro, refinado**: tokens em camadas e paleta ajustada, sem alternância claro/escuro. |
| Referência visual | **Sim, será enviada** pelo usuário. A etapa 1 (visual) espera por ela. |

## Consequências para as outras etapas

- **Etapa 1 (tokens e tema):** em espera até a referência visual chegar. A estrutura em camadas dos tokens pode ser preparada antes, mas a paleta e a tipografia não.
- **Etapa 2 (estrutura da janela):** pode andar já, porque trata de layout e arquitetura, não de aparência. Prioridade: painéis que o usuário esconde, move e destaca (docks), barra de ferramentas e persistência do layout.
- **Etapas 3 a 6:** seguem a etapa 1, pois dependem dos tokens.
- **Web:** fora de escopo. As portas criadas em `application/` mantêm essa porta aberta, sem compromisso.

## Fora de escopo

- Cálculos de análise (`lmu_telemetry/domain/analysis/`) e `application/pipeline.py`.
- Formato dos arquivos de telemetria e catálogo.
- Telemetria ao vivo, overlay e 3D (já fora de escopo no projeto).
- Tema claro e interface web.

## Critério de pronto

- Objetivos priorizados e aprovados. **Feito.**
- Decisão sobre tema e tecnologia de interface registrada. **Feito.**
