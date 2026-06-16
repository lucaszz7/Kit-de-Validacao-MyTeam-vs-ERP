from core.config_loader import load_config
from core.database import Database

from core.verifications import get_myteam_service_info
from core.verifications import get_world_geometries_info

from modulos.sage50.queries_vendedores import get_salesmen_mapping
from modulos.sage50.queries_vendedores import validate_salesmen

try:

    print("A verificar servico MyTeam...")

    myteam_service = get_myteam_service_info()

    print(f"Servico MyTeam: {myteam_service['service_name']}")
    print(f"Estado MyTeam: {myteam_service['status']}")

    print()

    print("A carregar configuracao...")

    config = load_config()

    print("Configuracao carregada!")

    print()

    print("A verificar base de dados World_Geometries...")

    world_geometries = get_world_geometries_info(
        server=config["sql_server"]["server"],
        user=config["sql_server"]["user"],
        password=config["sql_server"]["password"]
    )

    print(f"Base de dados: {world_geometries['database_name']}")
    print(f"Estado World_Geometries: {world_geometries['status']}")

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

    print("Ligacao efetuada com sucesso!")

    print()

    # ================================
    # MAPEAMENTO COMPLETO (VISUAL)
    # ================================

    print("MAPEAMENTO DE VENDEDORES:")
    print()

    rows = get_salesmen_mapping(db)

    for row in rows:
        print(row)

    print()

    # ================================
    # VALIDACAO
    # ================================

    print("VALIDACAO DE VENDEDORES:")
    print()

    result = validate_salesmen(db)

    if result["success"]:
        print("Nenhuma divergencia encontrada!")
    else:
        print(f"Foram encontradas {result['total_issues']} divergencias:")
        print()

        for issue in result["issues"]:
            print(f"- {issue['message']}")

    print()
    print("Validacao concluida!")

except Exception as e:

    print("ERRO:")
    print(e)
