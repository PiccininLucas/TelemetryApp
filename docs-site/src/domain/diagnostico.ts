export interface ArquivoUi {
  nome: string;
  linhas: number;
  responsabilidade: string;
}

export interface PainelUi {
  nome: string;
  consome: string;
  sinais: string;
}

export interface Diagnostico {
  arquivos: ArquivoUi[];
  paineis: PainelUi[];
}

export interface DiagnosticoRepository {
  obter(): Diagnostico;
}
