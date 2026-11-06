import { getCollection } from "astro:content";
import type { Etapa, EtapaRepository } from "../../domain/etapa";

/** Adaptador: lê as etapas da content collection do Astro (src/content/etapas). */
export class AstroEtapaRepository implements EtapaRepository {
  async listar(): Promise<Etapa[]> {
    const entries = await getCollection("etapas");
    return entries.map(({ id, data }) => ({ id, ...data }));
  }
}
