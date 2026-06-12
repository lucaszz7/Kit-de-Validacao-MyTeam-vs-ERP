from core.config_loader import load_config
from core.database import Database
from core.myteam_verify import get_myteam_service_info


try:

    print("A verificar servico MyTeam...")

    myteam_service = get_myteam_service_info()

    print(f"Servico MyTeam: {myteam_service['service_name']}")
    print(f"Estado MyTeam: {myteam_service['status']}")

    print("A carregar configuracao...")

    config = load_config()

    print("Configuracao carregada!")

    db = Database(
        server=config["sql_server"]["server"],
        database=config["databases"]["sage50"],
        user=config["sql_server"]["user"],
        password=config["sql_server"]["password"]
    )

    print("A ligar ao SQL Server...")

    conn = db.connect()

    print("Ligacao efetuada com sucesso!")

    conn.close()

    print("Ligacao encerrada!")

except Exception as e:

    print("ERRO:")
    print(e)
