import configparser
import subprocess
from pathlib import Path
from datetime import datetime
from core.database import Database
from core.port_checks import is_optimizer_port_open
from core.webapi_checks import are_api_keys_equal
from core.webapi_checks import get_webapi_status

# ==========================================================================================================
# VERIFICACAO DO myTeam.exe EM EXECUCAO OU NAO
# ==========================================================================================================

INI_PATH = r"C:\MIS\MSSV5\Backoffice\MSSBO.INI"
RUNNING = "Running"
STOPPED = "Stopped"


def get_myteam_status():
    service_info = get_myteam_service_info()

    return service_info["status"]


def get_myteam_service_info(ini_path: str | None = None):
    service_name = get_myteam_service_name(ini_path)

    if not service_name:
        return {
            "service_name": None,
            "status": STOPPED
        }

    return {
        "service_name": service_name,
        "status": get_windows_service_status(service_name)
    }


def get_myteam_service_name(ini_path: str | None = None):
    path = ini_path or INI_PATH
    ini_path_obj = Path(path)

    if not ini_path_obj.exists():
        return None

    config = read_ini_file(ini_path_obj)

    if not config.has_section("MyTeam"):
        return None

    service_name = config.get("MyTeam", "instanceName", fallback=None)

    if not service_name:
        return None

    return service_name.strip()


def read_ini_file(ini_path):
    config = configparser.ConfigParser()

    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with ini_path.open("r", encoding=encoding) as file:
                config.read_file(file)

            return config
        except UnicodeDecodeError:
            continue
        except configparser.Error:
            return config

    return config


def get_windows_service_status(service_name):
    try:
        startupinfo = None
        creationflags = 0

        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            if hasattr(subprocess, "SW_HIDE"):
                startupinfo.wShowWindow = subprocess.SW_HIDE

        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags
        )

        output = f"{result.stdout}\n{result.stderr}".upper()

        if is_service_running(output):
            return RUNNING

        return STOPPED
    except Exception:
        return STOPPED


def is_service_running(output):
    for line in output.splitlines():
        if "STATE" in line or "ESTADO" in line:
            if "RUNNING" in line or ": 4" in line:
                return True

            return False

    return "RUNNING" in output

# ==========================================================================================================
# VERIFICACAO SE A DATABASE World_Geometries EXISTE OU NAO
# ==========================================================================================================

WORLD_GEOMETRIES_DATABASE = "World_Geometries"
WORLD_GEOMETRIES_SUPPORT_LINK = "https://msssupport.sysdevmobile.com/portal/pt/kb/articles/myteam-monitor"


def get_world_geometries_info(server, user, password):
    exists = world_geometries_exist(
        server=server,
        user=user,
        password=password
    )

    if exists:
        return {
            "database_name": WORLD_GEOMETRIES_DATABASE,
            "exists": True,
            "status": "OK",
            "support_link": None
        }

    return {
        "database_name": WORLD_GEOMETRIES_DATABASE,
        "exists": False,
        "status": "Missing",
        "support_link": WORLD_GEOMETRIES_SUPPORT_LINK
    }


def world_geometries_exist(server, user, password, nome_bd=WORLD_GEOMETRIES_DATABASE):
    db = Database(
        server=server,
        database="master",
        user=user,
        password=password
    )

    nome_bd_seguro = nome_bd.replace("'", "''")

    query = f"SELECT DB_ID(N'{nome_bd_seguro}')"

    resultado = db.execute(query)

    if not resultado:
        return False

    return resultado[0][0] is not None

# ==========================================================================================================
#### VERIFICAÇÃO Se a porta 288 está aberta e se existe algum serviço a escutar nela.
# ==========================================================================================================

def get_optimizer_port_info():

    if is_optimizer_port_open():

        return {
            "status": "OK",
            "port": 288
        }
    
    return {
        "status": "Closed",
        "port": 288
    }

# ==========================================================================================================
# ### VERIFICAÇÃO SE A WebAPI esta em execução, SE AS API KEYS SÃO IGUAIS E SE A MESMA ESTÁ ONLINE
# ==========================================================================================================

WEBAPI_SERVICE_NAME = "MSSWebAPI"


def get_webapi_service_name(ini_path: str | None = None):
    path = ini_path or INI_PATH
    ini_path_obj = Path(path)

    if not ini_path_obj.exists():
        return None

    config = read_ini_file(ini_path_obj)

    if not config.has_section("WebApi"):
        return None

    service_name = config.get("WebApi", "instanceName", fallback=None)

    if not service_name:
        return None

    return service_name.strip()


def get_webapi_service_info(ini_path: str | None = None):
    service_name = get_webapi_service_name(ini_path) or WEBAPI_SERVICE_NAME

    return {
        "service_name": service_name,
        "status": get_windows_service_status(service_name)
    }


def get_webapi_apikey_info(ini_path: str | None = None, json_path: str | None = None):

    try:

        if are_api_keys_equal(ini_path, json_path):

            return {
                "status": "OK",
                "ApiKey": True,
                "ApiKeyLog": True,
                "ApiKeyInternal": True
            }

        return {
            "status": "Different",
            "ApiKey": False,
            "ApiKeyLog": False,
            "ApiKeyInternal": False
        }

    except Exception as e:

        msg = str(e).strip()
        if "No such file" in msg or "No such file or directory" in msg or "FileNotFoundError" in msg:
            detail = (
                "O caminho para o MSSBO.INI ou appsettings.json não é válido. "
                "Reconfigure os caminhos no formulário de login."
            )
        elif "section" in msg.lower() or "key" in msg.lower() or "WebApi" in msg:
            detail = (
                "O ficheiro MSSBO.INI parece não estar correto. "
                "Reconfigure o caminho no formulário de login."
            )
        else:
            detail = (
                "Erro ao ler os ficheiros de configuração da WebAPI. "
                "Verifique os caminhos no formulário de login."
            )

        return {
            "status": "Error",
            "message": detail,
            "ApiKey": False,
            "ApiKeyLog": False,
            "ApiKeyInternal": False
        }


def get_webapi_status_info(ini_path: str | None = None):

    status = get_webapi_status(ini_path)
    date_on_server = status.get("dateOnServer", "")

    return {
        "online": status.get(
            "online",
            False
  ),
        "message": status.get(
            "message",
            ""
        ) or "",
        "api_version": status.get(
            "apiVersion",
            ""
        ),
        "date_on_server": status.get(
            "dateOnServer",
            ""
        ),
        "date_on_server_formatted": format_webapi_date(
            date_on_server
        )
    }


def format_webapi_date(value):

    if not value:
        return ""

    value = str(value)

    if len(value) < 14:
        return value

    return (
        f"{value[6:8]}/{value[4:6]}/{value[0:4]} "
        f"{value[8:10]}:{value[10:12]}:{value[12:14]}"
    )

# ==========================================================================================================
# VERIFICAÇÃO SE A API GOOGLE MAPS EXISTE OU NAO
# ==========================================================================================================

GOOGLE_MAPS_API_SUPPORT_LINK = "https://msssupport.sysdevmobile.com/portal/pt/kb/articles/configurar-o-uso-do-google-places"

def get_google_maps_api_info(db):

    query = """
    SELECT CFGPAR, CFGVAL
    FROM BOMSCFG
    WHERE CFGGRP = 'GOOGLE'
    """

    rows = db.execute(query)

    configured_parameters = []

    for row in rows:

        parameter = str(row[0]).strip()
        value = row[1]

        if value is not None and str(value).strip():

            configured_parameters.append(parameter)

    return {

        "status": "OK" if configured_parameters else "Missing",

        "configured": len(configured_parameters) > 0,

        "parameters": configured_parameters,
        "support_link": None if configured_parameters else GOOGLE_MAPS_API_SUPPORT_LINK
    }

# ==========================================================================================================
# Validar se tem o símbolo no respetivo campo no BackOffice preenchido ou não
# ==========================================================================================================

def get_currency_symbol_info(db):

    query = """
    SELECT
        TERTER,
        TERVAL
    FROM MSTER
    WHERE TERDSC LIKE '%Simbolo do moeda%'
    """

    rows = db.execute(query)

    terminals_without_symbol = []

    for row in rows:

        terminal = str(row[0]).strip()
        symbol = "" if row[1] is None else str(row[1]).strip()

        if symbol == "":

            terminals_without_symbol.append(terminal)

    if not terminals_without_symbol:

        return{
            "status": "OK",
            "currency_symbol": "€",
            "missing_terminals": []
        }   
    
    return {
        "status": "Missing",
        "missing_terminals": terminals_without_symbol
    }

# ==========================================================================================================
# ### VERIFICAÇÃO DA VERSÃO DE DESPESAS (V1 / V2)
# ==========================================================================================================

def get_expenses_version_info(db_mss):
    query = """
    SELECT CFGGRP, CFGPAR, CFGVAL
    FROM BOMSCFG
    WHERE CFGGRP = 'EXPENSES'
      AND CFGPAR = 'DESPV2ACT'
    """
    rows = db_mss.execute(query)
    row = rows[0] if rows else None
    raw_value = None
    if row is not None and row[2] is not None:
        raw_value = str(row[2]).strip()
    if raw_value is not None and raw_value.upper() == "S":
        version = "V2"
        table_name = "MSPER"
    else:
        version = "V1"
        table_name = "MSDPS"

    count_row = db_mss.execute(f"SELECT COUNT(*) FROM {table_name}")
    total = count_row[0][0] if count_row else 0

    return {
        "status": "OK",
        "version": version,
        "table": table_name,
        "raw_value": raw_value,
        "total": total,
        "message": (
            f"O cliente usa Despesas {version}. "
            f"As despesas estão na tabela {table_name} "
            f"({total} registo(s))."
        ),
    }


# ==========================================================================================================
# ### VERIFICAÇÃO DA VERSÃO DAS ENTREGAS (V1 / V2)
# ==========================================================================================================

def get_delivery_version_info(db_mss):

    query = """
    SELECT TERVAL, TERTER
    FROM MSTER
    WHERE TERPAR = 'ENTVS'
    ORDER BY TERTER
    """
    rows = db_mss.execute(query)
    if not rows:
        return {"status": "Warning", "message": "Nenhum terminal configurado para entregas (ENTVS).", "terminais": []}
    
    terminals = []

    for row in rows:
        val = str(row[0] or "").strip()
        ter = str(row[1] or "").strip()
        version = "V1" if val == "1" else "V2" if val == "2" else f"Valor desconhecido ({val})"
        terminals.append ({"terminal": ter, "valor": val, "versao": version})

    info = "; ".join(f"Terminal {t['terminal']}: {t['versao']}" for t in terminals)
    status = "OK" if all (t["valor"] in ("1", "2") for t in terminals) else "Warning"
    return {"status": status, "message": info, "terminais": terminals}


# ==========================================================================================================
# Encontrar o documento mais antigo sincronizado na tabela STMSDCC
# ==========================================================================================================

def get_historical_sync_start_info(db_mss):

    query = """
    SELECT
        MIN(DCCDTA) AS DataMaisAntiga
    FROM STMSDCC
    """

    rows = db_mss.execute(query)

    if not rows or rows[0][0] is None:

        return {
            "status": "No Data",
            "start_date": None,
            "start_date_formatted": ""
        }

    start_date = str(rows[0][0])

    if len(start_date) == 8:
        start_date_formatted = (
            f"{start_date[6:8]}/"
            f"{start_date[4:6]}/"
            f"{start_date[0:4]}"
        )
    else:
        start_date_formatted = start_date

    return {
        "status": "OK",
        "start_date": start_date,
        "start_date_formatted": start_date_formatted
    }

