# docs-site

Documentação da remodelagem do front-end do LMU Telemetry Analyzer. Astro 7 + Tailwind v4, build estático.

```powershell
corepack pnpm install
corepack pnpm dev      # http://localhost:4321
corepack pnpm build    # dist/
```

## Estrutura (Clean Architecture)

```
src/
├── domain/            # tipos e regras puras; define as portas (interfaces dos repositórios)
├── application/       # casos de uso; dependem só de domain
├── infrastructure/    # adaptadores: content collection do Astro, dados estáticos
│   ├── content/
│   └── data/
├── presentation/      # layouts, componentes e CSS (.astro)
│   ├── layouts/
│   ├── components/
│   └── styles/
├── pages/             # rotas do Astro; só compõem presentation + casos de uso
├── content/etapas/    # as etapas, em Markdown (schema Zod em content.config.ts)
├── content.config.ts  # exigido pelo Astro nesta posição
└── composition.ts     # raiz de composição: liga portas às implementações
```

### Regra de dependência

`domain` ← `application` ← (`infrastructure`, `presentation`, `pages`) — as setas apontam para quem é dependido.

- `domain` não importa nada de fora dele (nem `astro:*`).
- `application` importa só `domain`.
- `infrastructure` implementa as portas de `domain`; é a única camada que usa `astro:content`.
- `presentation` e `pages` obtêm casos de uso por `composition.ts` e não importam `infrastructure`, com uma exceção: `pages/etapas/[...id].astro` usa `renderEtapa`, porque renderizar Markdown é função do Astro.
- Só `composition.ts` instancia classes de `infrastructure`.

## Como acrescentar

- **Nova etapa:** um `.md` em `src/content/etapas/` (frontmatter validado pelo schema).
- **Novo tipo de dado:** tipo e porta em `domain/`, caso de uso em `application/`, implementação em `infrastructure/`, ligação em `composition.ts`.
