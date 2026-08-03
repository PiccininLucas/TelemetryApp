"""Every piece of text the user ever sees, in Portuguese, in one file.

Code, identifiers and docstrings are in English; the interface is in Portuguese.
Keeping the two apart means a translation never requires touching logic, and it
makes it obvious at review time when a string leaked into a module where it does
not belong: if a module renders text, it must import it from here.

Naming convention: <AREA>_<WHAT>. Templates use str.format placeholders, always
named, never positional, so the order can change per language.
"""

from __future__ import annotations

# --- Application ------------------------------------------------------------
APP_NAME = "LMU Telemetry Analyzer"
APP_TAGLINE = "Análise pós-sessão de telemetria do Le Mans Ultimate"

# --- Session file errors ----------------------------------------------------
ERR_FILE_NOT_FOUND = "Arquivo de sessão não encontrado: {path}"
ERR_FILE_UNREADABLE = (
    "Não foi possível abrir o arquivo de sessão: {path}\nDetalhe técnico: {detail}"
)
ERR_FILE_NOT_DUCKDB = (
    "O arquivo não parece ser uma sessão do Le Mans Ultimate: {path}"
)
ERR_MISSING_CATALOG_TABLE = (
    "O arquivo não contém a tabela de catálogo '{table}'. "
    "A sessão pode estar corrompida ou ter sido gravada por outra versão do jogo."
)

# --- Session file name ------------------------------------------------------
ERR_BAD_SESSION_NAME = (
    "O nome do arquivo não segue o padrão do jogo "
    "(Pista_TipoDeSessão_AAAA-MM-DDThh_mm_ssZ.duckdb): {name}"
)

# Session type codes as they appear in the file name.
SESSION_TYPE_PRACTICE = "Treino livre"
SESSION_TYPE_QUALIFYING = "Classificação"
SESSION_TYPE_RACE = "Corrida"
SESSION_TYPE_WARMUP = "Warm-up"
SESSION_TYPE_TEST = "Teste"
SESSION_TYPE_UNKNOWN = "Desconhecido ({code})"

# --- Laps -------------------------------------------------------------------
LAP_FLAG_LABEL = {
    "valid": "válida",
    "partial": "parcial",
    "invalidated": "invalidada",
    "out_lap": "volta de saída",
    "in_lap": "volta de entrada",
    "in_pits": "nos boxes",
    "off_track": "fora da pista",
}

#: One-word forms for the narrow column in the session tree. The full list goes
#: in the tooltip; a lap can carry four flags at once and spelling them all out
#: leaves no room for the track and car names.
LAP_FLAG_SHORT = {
    "valid": "válida",
    "partial": "parcial",
    "invalidated": "invalidada",
    "out_lap": "saída",
    "in_lap": "entrada",
    "in_pits": "boxes",
    "off_track": "fora",
}

#: Which flag to show when a lap has several, most decisive first. A lap that is
#: partial cannot be used at all, so that outranks everything; being valid is
#: only worth saying when nothing else applies.
LAP_FLAG_PRIORITY = (
    "partial", "invalidated", "in_lap", "out_lap", "in_pits", "off_track", "valid",
)


def primary_lap_flag(flags: list[str] | tuple[str, ...]) -> str:
    """The single most important flag of a lap, for the narrow column."""
    for candidate in LAP_FLAG_PRIORITY:
        if candidate in flags:
            return LAP_FLAG_SHORT[candidate]
    return ""

WARN_NO_LAP_CHANNEL = (
    "O canal 'Lap' não foi gravado nesta sessão, então não é possível cortar a "
    "sessão em voltas."
)
WARN_SINGLE_LAP_MARKER = (
    "A sessão tem apenas uma marcação de volta: nenhuma volta completa foi "
    "gravada."
)
WARN_NO_PIT_CHANNEL = (
    "O canal 'In Pits' não está disponível: voltas de entrada e saída dos boxes "
    "não puderam ser identificadas."
)
INFO_PITS_NEVER_TOGGLED = (
    "O canal 'In Pits' não mudou durante a sessão inteira (nenhuma passagem "
    "pelos boxes). A sessão é tratada como um único stint."
)
WARN_NO_SURFACE_CHANNEL = (
    "O canal 'SurfaceTypes' não está disponível: saídas de pista não puderam "
    "ser detectadas."
)

# --- Session listing (scripts/list_laps.py) ---------------------------------
LAPS_TITLE = "VOLTAS DA SESSÃO"
LAPS_TRACK = "Pista"
LAPS_CAR = "Carro"
LAPS_SESSION = "Sessão"
LAPS_DATE = "Data (UTC)"
LAPS_WEATHER = "Condições"
LAPS_DURATION = "Duração da gravação"
LAPS_TIME_BASE = "Base de tempo"
LAPS_TIME_BASE_UNIFORM = "validada pelo GPS Time (deriva máx. {drift:.4f} s)"
LAPS_TIME_BASE_CORRECTED = "CORRIGIDA pelo GPS Time (deriva {drift:.4f} s)"
LAPS_TIME_BASE_UNVALIDATED = "NÃO validada (GPS Time indisponível)"
LAPS_TABLE_HEADER = "volta        tempo    medido       S1       S2       S3  situação"
LAPS_NO_LAPS = "Nenhuma volta identificada nesta sessão."
LAPS_SUMMARY = "{n_total} voltas · {n_comparable} comparáveis · melhor {best}"
LAPS_NO_COMPARABLE = "{n_total} voltas · nenhuma comparável"

# --- Main window ------------------------------------------------------------
WINDOW_TITLE = "LMU Telemetry Analyzer"
WINDOW_TITLE_WITH_SESSION = "{track} · {car} — LMU Telemetry Analyzer"

MENU_FILE = "&Arquivo"
MENU_VIEW = "&Exibir"
MENU_CHANNELS = "&Canais"
MENU_COMPARE = "&Comparação"
ACTION_IMPORT = "&Importar sessão..."
ACTION_IMPORT_FOLDER = "Importar &pasta..."
ACTION_REFRESH = "&Atualizar catálogo"
ACTION_QUIT = "&Sair"
ACTION_AXIS_DISTANCE = "Eixo X: &distância"
ACTION_AXIS_TIME = "Eixo X: &tempo"
ACTION_AXIS_TIME_BLOCKED = (
    "Duas voltas só podem ser comparadas no eixo de distância. Escolha "
    "\"Sem comparação\" para liberar o eixo de tempo."
)
ACTION_COMPARE_NONE = "&Sem comparação"
ACTION_COMPARE_BEST = "Comparar com a &melhor volta da sessão"
ACTION_COMPARE_PINNED = "Comparar com a volta &fixada"
ACTION_PIN_REFERENCE = "&Fixar volta atual como referência"

DIALOG_IMPORT_TITLE = "Escolha uma sessão de telemetria"
DIALOG_IMPORT_FOLDER_TITLE = "Escolha a pasta Telemetry"
DIALOG_FILE_FILTER = "Sessões do LMU (*.duckdb)"
DIALOG_IMPORT_FAILED_TITLE = "Falha na importação"

STATUS_READY = "Pronto"
STATUS_LOADING = "Carregando {name}..."
STATUS_IMPORTING = "Importando..."
STATUS_IMPORTED = "{n} sessão(ões) importada(s)."
STATUS_LAP_LOADED = (
    "Volta {number} · {time} · {length:.0f} m · {n_corners} curvas · "
    "carregada em {elapsed:.0f} ms"
)
STATUS_LAP_COMPARED = (
    "Volta {number} · {time} · {gap} s vs {reference} · "
    "pior perda {loss} s em {loss_at:.0f} m · carregada em {elapsed:.0f} ms"
)
STATUS_REFERENCE_LAP = "volta {number}"
STATUS_REFERENCE_IDEAL = "volta ideal"
STATUS_NO_SELECTION = "Selecione uma volta na árvore à esquerda."
STATUS_REFERENCE_PINNED = "Volta {number} fixada como referência."
STATUS_NO_REFERENCE_PINNED = "Nenhuma volta fixada. Use Exibir ▸ Comparação ▸ Fixar."

# --- Session browser --------------------------------------------------------
BROWSER_TITLE = "Sessões"
BROWSER_COLUMN_NAME = "Pista · carro · sessão · volta"
BROWSER_COLUMN_TIME = "Tempo"
BROWSER_COLUMN_NOTE = "Situação"
BROWSER_EMPTY = "Catálogo vazio — use Arquivo ▸ Importar sessão."
BROWSER_SESSION_LABEL = "{date} · {type}"
BROWSER_LAP_LABEL = "Volta {number}"
BROWSER_N_SESSIONS = "{n} sessões"
BROWSER_N_LAPS = "{n} voltas"

# --- Chart ------------------------------------------------------------------
CHART_AXIS_DISTANCE = "Distância (m)"
CHART_AXIS_TIME = "Tempo (s)"
CHART_NO_DATA = "Nenhuma volta carregada"

#: Left-axis label of each stacked row. The unit belongs here, never in the
#: readout, so it is stated once per screen instead of once per sample.
CHART_ROW_SPEED = "Velocidade (km/h)"
CHART_ROW_PEDALS = "Pedais (%)"
CHART_ROW_STEERING = "Volante (%)"
CHART_ROW_GEAR = "Marcha"
CHART_ROW_RPM = "Motor (rpm)"
CHART_ROW_DELTA = "Delta-t (s)"

#: Short names used in the cursor readout, where space is tight.
CHART_SERIES_SPEED = "vel"
CHART_SERIES_THROTTLE = "acel"
CHART_SERIES_BRAKE = "freio"
CHART_SERIES_STEERING = "volante"
CHART_SERIES_GEAR = "marcha"
CHART_SERIES_RPM = "rpm"
CHART_SERIES_DELTA = "Δt"

CHART_LEGEND_PRIMARY = "Volta {number} · {time}"
CHART_LEGEND_BENCHMARK = "referência: volta {number} · {time} · {gap} s"
CHART_LEGEND_NO_BENCHMARK = "sem comparação"

CHART_READOUT_DISTANCE = "{distance:.0f} m"
CHART_READOUT_TIME = "{time:.2f} s"
CHART_READOUT_SEPARATOR = " · "

# --- Track map --------------------------------------------------------------
MAP_TITLE = "Traçado"
MAP_NO_DATA = "Esta sessão não gravou GPS: o traçado não pode ser desenhado."
MAP_COLOUR_PEDALS = "Cor: &pedais"
MAP_COLOUR_DELTA = "Cor: &ganho/perda"
MAP_SHOW_INTEGRATED = "Sobrepor traçado &reconstruído"

MAP_LEGEND_BRAKE = "freio"
MAP_LEGEND_COAST = "inércia"
MAP_LEGEND_THROTTLE = "acelerador"
MAP_LEGEND_LOSS = "perdendo"
MAP_LEGEND_NEUTRAL = "igual"
MAP_LEGEND_GAIN = "ganhando"

MAP_EXTENT = "{width:.0f} × {height:.0f} m · fechamento {closure:.1f} m"
#: Shown when the reconstructed path is overlaid. The reconstruction uses no
#: position data at all, so the disagreement is the headline number.
MAP_INTEGRATED_ERROR = (
    "traçado reconstruído de a_y/V: erro médio {mean:.0f} m, máx {max:.0f} m"
)
MAP_INTEGRATED_UNAVAILABLE = (
    "O traçado reconstruído precisa da aceleração lateral, que não está "
    "disponível nesta sessão."
)

# --- g-g diagram ------------------------------------------------------------
GG_TITLE = "Diagrama g-g"
GG_AXIS_LATERAL = "Aceleração lateral (g)"
GG_AXIS_LONGITUDINAL = "Aceleração longitudinal (g)"
GG_NO_DATA = (
    "Esta sessão não gravou acelerações: o diagrama g-g não pode ser montado."
)
GG_SUMMARY = (
    "lateral {lateral:.2f} g · frenagem {braking:.2f} g · "
    "tração {acceleration:.2f} g"
)
GG_FILL = "envelope preenchido {fill:.0%} · transições {transitions:.0%}"
#: The caveat that keeps the fill fraction from being read as a grade.
GG_FILL_TOOLTIP = (
    "Preenchimento: área do fecho convexo dividida pela da elipse que os "
    "próprios extremos deste piloto descrevem. Valores perto de 100% não são "
    "esperados — a elipse é um limite externo.\n\n"
    "Transições: fração do tempo em que os dois eixos estão carregados ao "
    "mesmo tempo, ou seja, o quanto a frenagem é misturada com a curva."
)
GG_CURSOR = "{lateral:+.2f} g lat · {longitudinal:+.2f} g long · {total:.2f} g total"

# --- Corner table -----------------------------------------------------------
CORNERS_TITLE = "Curvas"
CORNERS_EMPTY = "Nenhuma curva detectada nesta volta."

CORNERS_COLUMN_NAME = "Curva"
CORNERS_COLUMN_APEX = "Ápice (m)"
CORNERS_COLUMN_MIN_SPEED = "V mín (km/h)"
CORNERS_COLUMN_ENTRY_SPEED = "V entrada (km/h)"
CORNERS_COLUMN_BRAKING = "Frenagem (m)"
CORNERS_COLUMN_TRAIL = "Trail (m)"
CORNERS_COLUMN_COASTING = "Inércia (s)"
CORNERS_COLUMN_SPEED_DELTA = "ΔV mín (km/h)"
CORNERS_COLUMN_DELTA = "Δt (s)"
CORNERS_COLUMN_BEST_LAP = "Melhor volta"
CORNERS_COLUMN_GAIN = "A ganhar (s)"

CORNERS_TOOLTIP_NAME = (
    "Clique duas vezes para nomear a curva. O nome fica gravado por pista e "
    "sobrevive a reimportar qualquer sessão — ele é ancorado na distância da "
    "linha de chegada, não no número da curva."
)
CORNERS_TOOLTIP_GAIN = (
    "Quanto esta volta perde neste trecho para a melhor passagem da sessão. "
    "Somado, é o ganho da volta ideal."
)
CORNERS_TOOLTIP_ROW = "Clique para levar o cursor ao ápice; duas vezes para ampliar."

# --- Ideal lap --------------------------------------------------------------
IDEAL_SUMMARY = (
    "Volta ideal {time} · {gain} s abaixo da melhor real ({best}) · "
    "{n_laps} voltas contribuem"
)
IDEAL_UNAVAILABLE = (
    "A volta ideal precisa de pelo menos duas voltas comparáveis na sessão."
)
#: Stated wherever the ideal lap appears, per the analysis module's own caveat.
IDEAL_CAVEAT = (
    "A volta ideal é costurada com o melhor trecho de cada volta. A velocidade "
    "de saída de um trecho condiciona a entrada no seguinte, então este alvo "
    "não é garantidamente possível — é um alvo, não um recorde.\n\n"
    "As emendas onde a velocidade salta estão marcadas no gráfico: elas são a "
    "evidência de que a volta é sintética."
)
IDEAL_SEAMS = "{n} emendas com salto de velocidade (máx {jump:.0f} km/h)"
ACTION_COMPARE_IDEAL = "Comparar com a volta &ideal"
CHART_LEGEND_IDEAL = "volta ideal · {time} · {gap} s"
STATUS_BUILDING_IDEAL = "Analisando todas as voltas da sessão..."

# --- Panels -----------------------------------------------------------------
MENU_PANELS = "&Painéis"
ACTION_PANEL_MAP = "&Traçado"
ACTION_PANEL_GG = "Diagrama &g-g"

WARN_COMPARE_DIFFERENT_TRACK = (
    "As duas voltas são de pistas diferentes ({track_a} e {track_b}). "
    "Comparar em distância exigiria que percorressem o mesmo traçado, então a "
    "comparação foi desativada."
)
WARN_COMPARE_DIFFERENT_CAR = (
    "As voltas comparadas são de carros diferentes ({car_a} e {car_b}). "
    "O delta-t continua válido, mas a diferença vem do carro tanto quanto da "
    "pilotagem."
)

# --- Import and catalog (scripts/import_session.py) -------------------------
IMPORT_TITLE = "IMPORTAÇÃO DE SESSÕES"
IMPORT_DONE = "{n_imported} importadas, {n_cached} já em cache, {n_failed} com falha"
IMPORT_FAILED = "FALHA em {name}: {detail}"
IMPORT_NOTHING_FOUND = "Nenhum arquivo .duckdb encontrado em {folder}"

CATALOG_TITLE = "CATÁLOGO HISTÓRICO"
CATALOG_LOCATION = "Banco"
CATALOG_CACHE = "Cache"
CATALOG_EMPTY = "O catálogo está vazio. Importe uma sessão primeiro."
CATALOG_STATS = (
    "{tracks} pistas · {sessions} sessões · {laps} voltas "
    "({comparable_laps} comparáveis) · {corners} curvas nomeadas"
)
CATALOG_SECTION_SESSIONS = "SESSÕES IMPORTADAS"
CATALOG_SECTION_BEST = "MELHOR VOLTA POR PISTA E CARRO"
CATALOG_SECTION_TRACKS = "PISTAS"
CATALOG_TRACK_LENGTH_UNKNOWN = "comprimento desconhecido"

# --- Channels ---------------------------------------------------------------
ERR_CHANNEL_NOT_FOUND = (
    "O canal '{channel}' não foi gravado nesta sessão. "
    "O recurso que depende dele foi desativado."
)
WARN_UNKNOWN_CHANNEL_FORMAT = (
    "A tabela '{table}' tem um formato de colunas desconhecido ({columns}) "
    "e será ignorada."
)
WARN_CHANNEL_WITHOUT_TABLE = (
    "O canal '{channel}' aparece no catálogo mas não tem tabela de dados."
)
WARN_TABLE_WITHOUT_CATALOG = (
    "A tabela '{table}' tem dados mas não aparece no catálogo de canais. "
    "Frequência e unidade são desconhecidas."
)
ERR_INVALID_FREQUENCY = (
    "O canal '{channel}' declara uma frequência inválida ({frequency}). "
    "Não é possível reconstruir a base de tempo dele."
)

# --- Units ------------------------------------------------------------------
WARN_UNKNOWN_UNIT = (
    "Unidade '{unit}' (canal '{channel}') não reconhecida. "
    "Os valores serão usados como estão, sem conversão."
)

# --- Time base --------------------------------------------------------------
# Shown as a banner at the top of the main window, per section 7 of the spec.
WARN_TIME_BASE_DRIFT = (
    "A base de tempo desta sessão apresentou desvio de {drift:.3f} s em relação "
    "ao relógio GPS e foi corrigida. Comparações entre voltas continuam válidas, "
    "mas verifique se houve pausa ou travamento durante a gravação."
)
WARN_TIME_BASE_NO_GPS = (
    "O canal 'GPS Time' não está disponível nesta sessão, então a base de tempo "
    "não pôde ser validada. Os tempos podem estar deslocados se o jogo travou "
    "durante a gravação."
)

# --- Schema inspection report (scripts/inspect_schema.py) -------------------
INSPECT_TITLE = "INSPEÇÃO DE SCHEMA"
INSPECT_FILE = "Arquivo"
INSPECT_SIZE = "Tamanho"
INSPECT_TABLE_COUNT = "Tabelas encontradas"
INSPECT_SECTION_TABLES = "1. TABELAS E COLUNAS"
INSPECT_SECTION_CATALOG = "2. TABELAS DE CATÁLOGO"
INSPECT_SECTION_FORMATS = "3. CLASSIFICAÇÃO DE FORMATO"
INSPECT_SECTION_DIVERGENCE = "4. DIVERGÊNCIAS EM RELAÇÃO AO SCHEMA ESPERADO"
INSPECT_SECTION_COHERENCE = "5. COERÊNCIA DO CATÁLOGO"
INSPECT_SECTION_TIMEBASE = "6. SANIDADE DA BASE DE TEMPO"
INSPECT_NO_DIVERGENCE = "Nenhuma divergência: o schema bate com o esperado."
INSPECT_MISSING_TABLES = "Esperadas mas AUSENTES ({count})"
INSPECT_EXTRA_TABLES = "Presentes mas NÃO esperadas ({count})"
INSPECT_WRONG_FORMAT = "Formato diferente do esperado ({count})"
INSPECT_UNKNOWN_FORMAT = "Formato NÃO RECONHECIDO ({count})"
INSPECT_ALL_CHANNELS_HAVE_TABLE = "Todo canal do catálogo tem tabela de dados."
INSPECT_ALL_TABLES_IN_CATALOG = "Toda tabela de dados aparece no catálogo."
INSPECT_DISTINCT_UNITS = "Unidades distintas encontradas"
INSPECT_DISTINCT_FREQUENCIES = "Frequências distintas encontradas"
INSPECT_DURATION_CONSISTENT = (
    "Durações implícitas coerentes: t[i] = i / frequency se sustenta."
)
INSPECT_DURATION_INCONSISTENT = (
    "As durações implícitas dos canais contínuos não batem entre si. "
    "Verifique abaixo se a causa é a frequência declarada (coluna INTEGER, "
    "truncada) ou uma falha real na gravação."
)
INSPECT_GPS_TIME_RANGE = "Intervalo de GPS Time"
INSPECT_GPS_TIME_MISSING = "Canal 'GPS Time' ausente: sem referência de relógio."
INSPECT_SECTION_FREQUENCY = "7. FREQUÊNCIA DECLARADA vs EMPÍRICA"
INSPECT_FREQ_ALL_EXACT = (
    "Toda frequência declarada bate com a empírica dentro da tolerância."
)
INSPECT_FREQ_TRUNCATED = (
    "Canais cuja frequência declarada está truncada ({count}). "
    "A coluna 'frequency' é INTEGER, então uma taxa real não inteira é gravada "
    "arredondada para baixo. Usar o valor declarado desloca estes canais ao "
    "longo da sessão."
)
INSPECT_DISCRETE_CHANNELS = (
    "Canais de valor discreto ({count}) - reamostragem por degrau, nunca "
    "interpolação linear"
)

# --- Format names shown in reports ------------------------------------------
FORMAT_LABEL = {
    "A": "A - contínuo simples (value)",
    "B": "B - contínuo por roda (value1..value4)",
    "C": "C - evento (ts, value)",
    "D": "D - evento por roda (ts, value1..value4)",
    "UNKNOWN": "DESCONHECIDO",
}


def session_type_label(code: str) -> str:
    """Return the Portuguese label for a session type code from the file name."""
    labels = {
        "P": SESSION_TYPE_PRACTICE,
        "Q": SESSION_TYPE_QUALIFYING,
        "R": SESSION_TYPE_RACE,
        "W": SESSION_TYPE_WARMUP,
        "T": SESSION_TYPE_TEST,
    }
    return labels.get(code.upper(), SESSION_TYPE_UNKNOWN.format(code=code))
