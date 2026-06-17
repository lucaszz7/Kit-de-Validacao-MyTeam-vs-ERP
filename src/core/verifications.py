import configparser
import subprocess
from pathlib import Path
from core.database import Database
from core.port_checks import is_optimizer_port_open
from core.webapi_checks import are_api_keys_equal
from core.webapi_checks import get_webapi_status


# VERIFICACAO DO myTeam.exe EM EXECUCAO OU NAO

INI_PATH = r"C:\MIS\MSSV5\Backoffice\MSSBO.INI"
RUNNING = "Running"
STOPPED = "Stopped"


def get_myteam_status():
    service_info = get_myteam_service_info()

    return service_info["status"]


def get_myteam_service_info():
    service_name = get_myteam_service_name()

    if not service_name:
        return {
            "service_name": None,
            "status": STOPPED
        }

    return {
        "service_name": service_name,
        "status": get_windows_service_status(service_name)
    }


def get_myteam_service_name():
    ini_path = Path(INI_PATH)

    if not ini_path.exists():
        return None

    config = read_ini_file(ini_path)

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
        result = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            check=False
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


# VERIFICACAO SE A DATABASE World_Geometries EXISTE OU NAO

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

#### VERIFICAÇÃO Se a porta 288 está aberta e se existe algum serviço a escutar nela.

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

### VERIFICAÇÃO SE A WebAPI esta em execução

# =====================================================
# WEB API
# =====================================================

WEBAPI_SERVICE_NAME = "MSSWebAPI"


def get_webapi_service_info():

    return {
        "service_name": WEBAPI_SERVICE_NAME,
        "status": get_windows_service_status(
            WEBAPI_SERVICE_NAME
        )
    }


def get_webapi_apikey_info():

    if are_api_keys_equal():

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


def get_webapi_status_info():

    status = get_webapi_status()

    return {
        "online": status.get(
            "online",
            False
        ),
        "message": status.get(
            "message",
            ""
        ),
        "api_version": status.get(
            "apiVersion",
            ""
        )
    }