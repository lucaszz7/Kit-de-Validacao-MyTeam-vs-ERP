from core.config_loader import load_config
from core.database import Database


try:

    print("A carregar configuração...")

    config = load_config()

    print("Configuração carregada!")

    db = Database(
        server=config["sql_server"]["server"],
        database=config["databases"]["sage50"],
        user=config["sql_server"]["user"],
        password=config["sql_server"]["password"]
    )

    print("A ligar ao SQL Server...")

    conn = db.connect()

    print("Ligação efetuada com sucesso!")

    conn.close()

    print("Ligação encerrada!")

except Exception as e:

    print("ERRO:")
    print(e)