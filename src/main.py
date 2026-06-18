from core.config_loader import load_config
from core.database import Database

from core.verifications import get_myteam_service_info
from core.verifications import get_world_geometries_info

from modulos.sage50.queries_vendedores import get_salesmen_mapping
from modulos.sage50.queries_vendedores import validate_salesmen

from core.verifications import get_optimizer_port_info

from core.verifications import get_webapi_service_info
from core.verifications import get_webapi_apikey_info
from core.verifications import get_webapi_status_info

from core.verifications import get_google_maps_api_info

from core.verifications import get_currency_symbol_info


try:

    print()
    print("==========================================")
    print("      KIT DE VALIDAÇÃO MYTEAM VS ERP")
    print("==========================================")

    # ==========================================
    # MYTEAM
    # ==========================================

    print()
    print(">>> SERVIÇO MYTEAM")

    myteam_service = get_myteam_service_info()

    print(f"Nome........: {myteam_service['service_name']}")
    print(f"Status......: {myteam_service['status']}")

    # ==========================================
    # WEBAPI
    # ==========================================

    print()
    print(">>> WebAPI")

    webapi_service = get_webapi_service_info()

    print(f"Serviço.....: {webapi_service['status']}")

    apikey = get_webapi_apikey_info()

    print(f"ApiKeys.....: {apikey['status']}")

    status = get_webapi_status_info()

    print(f"Online......: {status['online']}")
    print(f"Versão API..: {status['api_version']}")

    if status["message"]:
        print(f"Mensagem....: {status['message']}")

    if status["date_on_server_formatted"]:
        print(
            f"Data servidor: {status['date_on_server_formatted']}"
        )

    # ==========================================
    # PORTA 288
    # ==========================================

    print()
    print(">>> OTIMIZADOR")

    optimizer = get_optimizer_port_info()

    print(f"Porta 288...: {optimizer['status']}")

    # ==========================================
    # CONFIG
    # ==========================================

    print()
    print(">>> CONFIGURAÇÃO")

    config = load_config()

    print("Configuração carregada com sucesso.")

    # ==========================================
    # WORLD_GEOMETRIES
    # ==========================================

    print()
    print(">>> WORLD_GEOMETRIES")

    world_geometries = get_world_geometries_info(
        server=config["sql_server"]["server"],
        user=config["sql_server"]["user"],
        password=config["sql_server"]["password"]
    )

    print(f"Base de dados........: {world_geometries['database_name']}")
    print(f"Status......: {world_geometries['status']}")

    if not world_geometries["exists"]:
        print(
            f"Suporte.....: {world_geometries['support_link']}"
        )

    # ==========================================
    # SQL
    # ==========================================

    print()
    print(">>> SQL SERVER")

    db = Database(
        server=config["sql_server"]["server"],
        database=config["databases"]["sage50"],
        user=config["sql_server"]["user"],
        password=config["sql_server"]["password"]
    )

    db.execute("SELECT 1")

    print("Ligação efetuada com sucesso.")

    # ==========================================
    # GOOGLE MAPS
    # ==========================================

    db_mss = Database(
        server=config["sql_server"]["server"],
        database=config["databases"]["mss"],
        user=config["sql_server"]["user"],
        password=config["sql_server"]["password"]
    )

    print()
    print(">>> API DE MAPAS")

    google_maps = get_google_maps_api_info(db_mss)

    print(f"Status......: {google_maps['status']}")

    print()

    print(">>> SÍMBOLO DA MOEDA")

    currency = get_currency_symbol_info(db_mss)

    print(f"Estado......: {currency['status']}")

    if currency["missing_terminals"]:

        print("Terminais sem símbolo:")

        for terminal in currency["missing_terminals"]:

            print(f"  • Terminal {terminal}")

    # ==========================================
    # MAPEAMENTO DE VENDEDORES
    # ==========================================

    print()
    print(">>> MAPEAMENTO DE VENDEDORES")
    print()

    rows = get_salesmen_mapping(db)

    for row in rows:

        if row["origem"] == "MSS":

            print(row)

    print()

    # ==========================================
    # VALIDAÇÃO
    # ==========================================

    print()
    print(">>> VALIDAÇÃO DE VENDEDORES")

    result = validate_salesmen(db)

    if result["success"]:

        print()
        print("✓ Nenhuma divergência encontrada.")

    else:

        print()
        print(
            f"Foram encontradas "
            f"{result['total_issues']} divergências:"
        )
        print()

        for issue in result["issues"]:

            print(f"• {issue['message']}")

    print()
    print("==========================================")
    print("      VALIDAÇÃO CONCLUÍDA")
    print("==========================================")

except Exception as e:

    print()
    print("==========================================")
    print("               ERRO")
    print("==========================================")
    print(e)