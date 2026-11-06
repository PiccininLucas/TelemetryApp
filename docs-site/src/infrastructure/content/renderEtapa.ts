import { getEntry, render } from "astro:content";

/** Renderiza o corpo Markdown de uma etapa. Fica na infraestrutura porque
 *  depende do pipeline de Markdown do Astro. */
export async function renderEtapa(id: string) {
  const entry = await getEntry("etapas", id);
  if (!entry) throw new Error(`Etapa não encontrada: ${id}`);
  return render(entry);
}
