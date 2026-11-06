import type { GrupoTokens, TokenRepository } from "../../domain/tokens";

/** Espelha lmu_telemetry/presentation/theme.py. Se o tema mudar, atualizar aqui. */
const GRUPOS: GrupoTokens[] = [
  { nome: "Superfícies", tokens: [
    { nome: "BACKGROUND", hex: "#0c0d14" }, { nome: "SURFACE", hex: "#141521" },
    { nome: "SURFACE_RAISED", hex: "#1d1f30" }, { nome: "BORDER", hex: "#2a2c42" },
  ]},
  { nome: "Texto", tokens: [
    { nome: "TEXT", hex: "#e9eaf5" }, { nome: "TEXT_MUTED", hex: "#9fa2bd" }, { nome: "TEXT_DISABLED", hex: "#5d6080" },
  ]},
  { nome: "Acento e avisos", tokens: [
    { nome: "ACCENT", hex: "#8f7cff" }, { nome: "WARNING", hex: "#f0b132" }, { nome: "ERROR", hex: "#e5484d" },
  ]},
  { nome: "Traçados (cores de dado)", tokens: [
    { nome: "TRACE_REFERENCE", hex: "#4da3ff" }, { nome: "TRACE_COMPARISON", hex: "#f5a524" }, { nome: "TRACE_IDEAL", hex: "#30c48d" },
  ]},
  { nome: "Pedais (cores de dado)", tokens: [
    { nome: "COLOUR_BRAKE", hex: "#e5484d" }, { nome: "COLOUR_THROTTLE", hex: "#30c48d" }, { nome: "COLOUR_COAST", hex: "#9aa0a8" },
  ]},
];

export class TokensEstaticos implements TokenRepository {
  listarGrupos(): GrupoTokens[] {
    return GRUPOS;
  }
}
