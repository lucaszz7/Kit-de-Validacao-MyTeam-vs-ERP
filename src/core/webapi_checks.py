import configparser
import json
import requests


INI_PATH = r"C:\MIS\MSSV5\Backoffice\MSSBO.INI"

APPSETTINGS_PATH = r"C:\MIS\MSSV5\MSSWebAPI\appsettings.json"
GET_STATUS_URL = "http://localhost:19080/MSSWebApi/MSSClient/Authentication/GetStatus"


def get_ini_keys(ini_path: str | None = None):

    path = ini_path or INI_PATH
    config = configparser.ConfigParser()

    config.read(
        path,
        encoding="cp1252"
    )

    return {

        "ApiKey":
        config["WebApi"]["apikey"],

        "ApiKeyLog":
        config["WebApi"]["apikeylog"],

        "ApiKeyInternal":
        config["WebApi"]["apikeyinternal"]

    }


def get_json_keys(json_path: str | None = None):

    path = json_path or APPSETTINGS_PATH

    with open(
        path,
        encoding="utf-8"
    ) as file:

        data = json.load(file)

    return {

        "ApiKey":
        data["ApiKey"],

        "ApiKeyLog":
        data["ApiKeyLog"],

        "ApiKeyInternal":
        data["ApiKeyInternal"]

    }


def are_api_keys_equal(ini_path: str | None = None, json_path: str | None = None):

    ini_keys = get_ini_keys(ini_path)

    json_keys = get_json_keys(json_path)

    return (

        ini_keys["ApiKey"]
        ==
        json_keys["ApiKey"]

        and

        ini_keys["ApiKeyLog"]
        ==
        json_keys["ApiKeyLog"]

        and

        ini_keys["ApiKeyInternal"]
        ==
        json_keys["ApiKeyInternal"]

    )


def get_webapi_status(ini_path: str | None = None):

    try:
        api_key = get_ini_keys(ini_path)["ApiKey"]

        response = requests.post(
            GET_STATUS_URL,

            headers={
                "X-Api-Key": api_key
            },

            json={
                "value": 123
            },

            timeout=5

        )

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code != 200:
            return {
                "online": False,
                "message": data.get(
                    "title",
                    f"HTTP {response.status_code}"
                ),
                "status_code": response.status_code
            }

        return data

    except requests.exceptions.ConnectionError:

        return {
            "online": False,
            "message": "Não foi possível ligar à WebAPI. Verifique se o serviço MSSWebAPI está em execução e se a porta 19080 está acessível."
        }

    except requests.exceptions.Timeout:

        return {
            "online": False,
            "message": "A WebAPI não respondeu dentro do tempo limite (5 segundos). O serviço pode estar sobrecarregado ou bloqueado por firewall."
        }

    except Exception as e:

        msg = str(e).strip()
        if "Connection refused" in msg or "10061" in msg or "actively refused" in msg.lower():
            friendly = "Não foi possível ligar à WebAPI (ligação recusada). Verifique se o serviço MSSWebAPI está em execução."
        elif "Name or service not known" in msg or "[Errno -2]" in msg or "[Errno 11001]" in msg:
            friendly = "Não foi possível resolver o endereço da WebAPI. Verifique a configuração de rede."
        elif "No such file" in msg or "No such file or directory" in msg or "FileNotFoundError" in msg or "section" in msg.lower() or "WebApi" in msg:
            friendly = (
                "O caminho do MSSBO.INI não é válido ou o ficheiro está incorreto. "
                "Reconfigure o caminho no formulário de login."
            )
        else:
            friendly = f"Erro ao contactar a WebAPI: {msg}"

        return {
            "online": False,
            "message": friendly
        }
