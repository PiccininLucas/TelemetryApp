---
titulo: Objetivos e escopo
resumo: Definir o que a remodelagem precisa resolver, o que fica fora e como medir que deu certo.
ordem: 0
status: pendente
risco: baixo
arquivos: []
---

## Escopo

Esta etapa não toca em código. Fecha o alvo antes das demais.

## Perguntas a responder

- O que incomoda hoje: aparência, organização do layout, fluxo de uso ou tudo?
- O app continua desktop (PySide6) ou a remodelagem inclui levar a interface para web?
- Mantemos só o tema escuro ou entra tema claro?
- Há uma referência visual (outro app, protótipo, screenshot) a seguir?

## Fora de escopo (proposta)

- Cálculos de análise (`lmu_telemetry/domain/analysis/`) e `application/pipeline.py`.
- Formato dos arquivos de telemetria e catálogo.
- Telemetria ao vivo, overlay e 3D (já fora de escopo no projeto).

## Critério de pronto

- Lista de objetivos priorizada e aprovada.
- Decisão sobre tema(s) e tecnologia de interface registrada.

## Decisões em aberto

Todas as perguntas acima.
