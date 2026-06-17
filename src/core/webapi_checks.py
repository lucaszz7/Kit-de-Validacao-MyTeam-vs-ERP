import configparser
import json
import requests


INI_PATH = r"C:\MIS\MSSV5\Backoffice\MSSBO.INI"

APPSETTINGS_PATH = r"C:\MIS\MSSV5\MSSWebAPI\appsettings.json"


def get_ini_keys():

    config = configparser.ConfigParser()

    config.read(
        INI_PATH,
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


def get_json_keys():

    with open(
        APPSETTINGS_PATH,
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


def are_api_keys_equal():

    ini_keys = get_ini_keys()

    json_keys = get_json_keys()

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


def get_webapi_status():

    try:

        response = requests.post(

            "http://localhost:19080/MSSWebApi/MSSClient/Authentication/GetStatus",

            json={
                "value": 123
            },

            timeout=5

        )

        return response.json()

    except Exception as e:

        return {

            "online": False,

            "message": str(e)

        }