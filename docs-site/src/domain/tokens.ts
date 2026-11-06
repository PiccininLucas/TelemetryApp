export interface Token {
  nome: string;
  hex: string;
}

export interface GrupoTokens {
  nome: string;
  tokens: Token[];
}

export interface TokenRepository {
  listarGrupos(): GrupoTokens[];
}
