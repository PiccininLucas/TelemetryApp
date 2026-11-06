import type { Diagnostico, DiagnosticoRepository } from "../domain/diagnostico";
import type { GrupoTokens, TokenRepository } from "../domain/tokens";

export function criarCasosDeUsoDocumentacao(
  diagnostico: DiagnosticoRepository,
  tokens: TokenRepository,
) {
  return {
    obterDiagnostico: (): Diagnostico => diagnostico.obter(),
    listarGruposDeTokens: (): GrupoTokens[] => tokens.listarGrupos(),
  };
}
