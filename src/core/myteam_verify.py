import configparser
import subprocess
from pathlib import Path

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
