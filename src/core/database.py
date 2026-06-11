import pyodbc

class Database:

    def __init__(
        self,
        server,
        database,
        user,
        password
    ):

        self.server = server
        self.database = database
        self.user = user
        self.password = password

    def connect(self):

        return pyodbc.connect(
            f"""
            DRIVER={{ODBC Driver 17 for SQL Server}};
            SERVER={self.server};
            DATABASE={self.database};
            UID={self.user};
            PWD={self.password};
            """
        )

    def execute(self, query):

        conn = None

        try:

            conn = self.connect()

            cursor = conn.cursor()

            cursor.execute(query)

            return cursor.fetchall()

        finally:

            if conn:
                conn.close()