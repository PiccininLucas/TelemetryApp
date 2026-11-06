import type { GrupoTokens, TokenRepository } from "../../domain/tokens";

/** Espelha lmu_telemetry/presentation/theme.py. Se o tema mudar, atualizar aqui. */
const GRUPOS: GrupoTokens[] = [
  { nome: "Superfícies", tokens: [
    { nome: "BACKGROUND", hex: "#1a1c20" }, { nome: "SURFACE", hex: "#22252b" },
    { nome: "SURFACE_RAISED", hex: "#2b2f36" }, { nome: "BORDER", hex: "#3a3f47" },
  ]},
  { nome: "Texto", tokens: [
    { nome: "TEXT", hex: "#e6e8ea" }, { nome: "TEXT_MUTED", hex: "#9aa0a8" }, { nome: "TEXT_DISABLED", hex: "#5f656d" },
  ]},
  { nome: "Acentos", tokens: [
    { nome: "ACCENT", hex: "#4da3ff" }, { nome: "WARNING", hex: "#f0b132" }, { nome: "ERROR", hex: "#e5484d" },
  ]},
  { nome: "Traçados", tokens: [
    { nome: "TRACE_REFERENCE", hex: "#4da3ff" }, { nome: "TRACE_COMPARISON", hex: "#f5a524" }, { nome: "TRACE_IDEAL", hex: "#30c48d" },
  ]},
  { nome: "Pedais", tokens: [
    { nome: "COLOUR_BRAKE", hex: "#e5484d" }, { nome: "COLOUR_THROTTLE", hex: "#30c48d" }, { nome: "COLOUR_COAST", hex: "#9aa0a8" },
  ]},
];

export class TokensEstaticos implements TokenRepository {
  listarGrupos(): GrupoTokens[] {
    return GRUPOS;
  }
}
