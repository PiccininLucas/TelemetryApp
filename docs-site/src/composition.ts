// Raiz de composição: único lugar que conhece as implementações concretas.
import { criarCasosDeUsoDocumentacao } from "./application/documentacao";
import { criarCasosDeUsoEtapas } from "./application/etapas";
import { AstroEtapaRepository } from "./infrastructure/content/astroEtapaRepository";
import { DiagnosticoEstatico } from "./infrastructure/data/diagnosticoEstatico";
import { TokensEstaticos } from "./infrastructure/data/tokensEstaticos";

export const etapas = criarCasosDeUsoEtapas(new AstroEtapaRepository());
export const documentacao = criarCasosDeUsoDocumentacao(
  new DiagnosticoEstatico(),
  new TokensEstaticos(),
);
