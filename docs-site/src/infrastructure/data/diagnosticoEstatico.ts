import type { Diagnostico, DiagnosticoRepository } from "../../domain/diagnostico";

/** Retrato da interface (presentation/ e shared/) antes da remodelagem. Atualizar à mão se o código mudar. */
const DIAGNOSTICO: Diagnostico = {
  arquivos: [
    { nome: "presentation/main_window.py", linhas: 1263, responsabilidade: "Janela, menus e ligação dos sinais. MainWindow, ImportWorker, SessionPool, CurrentView, ComparisonMode." },
    { nome: "presentation/chart_panel.py", linhas: 761, responsabilidade: "Traçados empilhados com eixo X compartilhado. ChartStack, RowSpec, LapTrace, AxisMode." },
    { nome: "shared/strings.py", linhas: 630, responsabilidade: "Todo texto visível, em português. Dados puros." },
    { nome: "presentation/consistency_panel.py", linhas: 399, responsabilidade: "ConsistencyPanel: ranking por curva e gráfico volta a volta." },
    { nome: "presentation/corner_table.py", linhas: 335, responsabilidade: "CornerTable (QTableWidget), nomes de curva editáveis." },
    { nome: "presentation/track_map.py", linhas: 328, responsabilidade: "TrackMap: trajetória colorida por pedais ou por delta." },
    { nome: "presentation/session_browser.py", linhas: 303, responsabilidade: "SessionBrowser: árvore pista > carro > sessão > volta." },
    { nome: "presentation/gg_panel.py", linhas: 189, responsabilidade: "FrictionPanel: diagrama g-g com envelope convexo." },
    { nome: "presentation/theme.py", linhas: 181, responsabilidade: "Constantes de cor, paleta, QSS global, configuração do pyqtgraph." },
    { nome: "shared/formatting.py", linhas: 36, responsabilidade: "format_lap_time, format_gap, format_value." },
  ],
  paineis: [
    { nome: "Navegador de sessões", consome: "Somente o catálogo (SessionRow). Nunca lê os arquivos de telemetria.", sinais: "lap_selected" },
    { nome: "Gráficos (ChartStack)", consome: "LapTrace da volta principal e do benchmark, mais delta-t do pipeline.", sinais: "cursor_moved" },
    { nome: "Mapa da pista", consome: "track_paths, pedal_states, loss_classes_on.", sinais: "distance_picked" },
    { nome: "Diagrama g-g", consome: "friction_envelope, aceleração lateral e longitudinal, transition_quality.", sinais: "—" },
    { nome: "Tabela de curvas", consome: "corner_rows(primary, benchmark, ideal).", sinais: "corner_selected, corner_zoomed, corner_renamed" },
    { nome: "Consistência", consome: "SessionAnalysis.stints e ConsistencyReport.", sinais: "corner_selected, stint_changed" },
  ],
};

export class DiagnosticoEstatico implements DiagnosticoRepository {
  obter(): Diagnostico {
    return DIAGNOSTICO;
  }
}
