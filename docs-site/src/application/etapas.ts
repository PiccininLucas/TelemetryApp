import type { Etapa, EtapaRepository } from "../domain/etapa";

export interface EtapaComVizinhas {
  etapa: Etapa;
  anterior?: Etapa;
  proxima?: Etapa;
}

export interface Progresso {
  concluidas: number;
  total: number;
}

export function criarCasosDeUsoEtapas(repo: EtapaRepository) {
  async function listarEtapas(): Promise<Etapa[]> {
    return [...(await repo.listar())].sort((a, b) => a.ordem - b.ordem);
  }

  async function listarEtapasComVizinhas(): Promise<EtapaComVizinhas[]> {
    const etapas = await listarEtapas();
    return etapas.map((etapa, i) => ({
      etapa,
      anterior: etapas[i - 1],
      proxima: etapas[i + 1],
    }));
  }

  async function obterProgresso(): Promise<Progresso> {
    const etapas = await listarEtapas();
    return {
      concluidas: etapas.filter((e) => e.status === "concluida").length,
      total: etapas.length,
    };
  }

  return { listarEtapas, listarEtapasComVizinhas, obterProgresso };
}
