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
