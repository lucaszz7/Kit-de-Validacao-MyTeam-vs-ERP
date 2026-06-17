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

try:

    print("A verificar serviço MyTeam...")

    myteam_service = get_myteam_service_info()

    print(f"Serviço MyTeam: {myteam_service['service_name']}")
    print(f"Status MyTeam: {myteam_service['status']}")

    print()

    print("A verificar serviço WebAPI...")

    webapi_service = get_webapi_service_info()

    print(f"Serviço WebAPI: {webapi_service['status']}")

    print()

    print("A verificar Apikeys...")

    apikey = get_webapi_apikey_info()

    print(f"ApiKeys: {apikey['status']}")

    print()

    print("A verificar GetStatus...")

    status = get_webapi_status_info()

    print(f"Online: {status['online']}")

    print(f"Versão API: {status['api_version']}")

    print(f"Mensagem: {status['message']}")

    print()

    print("A verificar porta do Otimizador...")

    optimizer = get_optimizer_port_info()

    print(f"Porta {optimizer['port']}: {optimizer['status']}")

    print()

    print("A carregar configuração...")

    config = load_config()

    print("Configuração carregada!")

    print()

    print("A verificar base de dados World_Geometries...")

    world_geometries = get_world_geometries_info(
        server=config["sql_server"]["server"],
        user=config["sql_server"]["user"],
        password=config["sql_server"]["password"]
    )

    print(f"Base de dados: {world_geometries['database_name']}")
    print(f"Status World_Geometries: {world_geometries['status']}")

    if not world_geometries["exists"]:
        print(f"Artigo de suporte: {world_geometries['support_link']}")

    print()

    print("A ligar ao SQL Server...")

    db = Database(
        server=config["sql_server"]["server"],
        database=config["databases"]["sage50"],
        user=config["sql_server"]["user"],
        password=config["sql_server"]["password"]
    )

    db.execute("SELECT 1")

    print("Ligação efetuada com sucesso!")

    print()

    # ================================
    # MAPEAMENTO COMPLETO (VISUAL)
    # ================================

    print("MAPEAMENTO DE VENDEDORES:")
    print()

    rows = get_salesmen_mapping(db)

    for row in rows:

        if row["origem"] == "MSS":
            print(row)

    print()

    # ================================
    # VALIDACAO
    # ================================

    print("VALIDAÇÃO DE VENDEDORES:")
    print()

    result = validate_salesmen(db)

    if result["success"]:
        print("Nenhuma divergência encontrada!")
    else:
        print(f"Foram encontradas {result['total_issues']} divergências:")
        print()

        for issue in result["issues"]:
            print(f"- {issue['message']}")

    print()
    print("Validação concluída!")

except Exception as e:

    print("ERRO:")
    print(e)
