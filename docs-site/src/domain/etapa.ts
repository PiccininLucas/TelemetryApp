export const STATUS = ["pendente", "em-andamento", "concluida"] as const;
export type Status = (typeof STATUS)[number];

export const RISCOS = ["baixo", "medio", "alto"] as const;
export type Risco = (typeof RISCOS)[number];

export const ROTULO_STATUS: Record<Status, string> = {
  pendente: "Pendente",
  "em-andamento": "Em andamento",
  concluida: "Concluída",
};

export const ROTULO_RISCO: Record<Risco, string> = {
  baixo: "Risco baixo",
  medio: "Risco médio",
  alto: "Risco alto",
};

export interface Etapa {
  id: string;
  ordem: number;
  titulo: string;
  resumo: string;
  status: Status;
  risco: Risco;
  arquivos: string[];
}

/** Porta: de onde vêm as etapas. Quem implementa é a infraestrutura. */
export interface EtapaRepository {
  listar(): Promise<Etapa[]>;
}
