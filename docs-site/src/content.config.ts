import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";
import { RISCOS, STATUS } from "./domain/etapa";

const etapas = defineCollection({
  loader: glob({ pattern: "**/*.md", base: "./src/content/etapas" }),
  schema: z.object({
    titulo: z.string().max(70),
    resumo: z.string().max(160),
    ordem: z.number().int().nonnegative(),
    status: z.enum(STATUS).default("pendente"),
    arquivos: z.array(z.string()).default([]),
    risco: z.enum(RISCOS).default("baixo"),
  }),
});

export const collections = { etapas };
