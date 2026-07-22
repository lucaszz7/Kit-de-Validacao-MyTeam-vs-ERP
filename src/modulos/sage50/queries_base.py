"""Funções utilitárias partilhadas entre queries_vendas e queries_encomendas."""

from typing import Any, Protocol


class DatabaseExecutor(Protocol):
    def execute(self, query: str) -> Any: ...


def normalize_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def sql_literal(value: str) -> str:
    return value.replace("'", "''")


def get_table_columns(db: DatabaseExecutor, table_name: str) -> set[str]:
    rows = db.execute(
        f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = '{sql_literal(table_name)}'
        """
    )
    return {normalize_text(row[0]).upper() for row in rows}


def detect_salesman_column(db_mss: DatabaseExecutor) -> str | None:
    columns = get_table_columns(db_mss, "STMSDCC")
    for col in ["DCCVND", "DCCACL_38", "DCCCVD"]:
        if col in columns:
            return col
    return None


def build_docs_filter(allowed_documents: set | None, column: str = "DCCTPD") -> str:
    if not allowed_documents:
        return ""
    docs_list = ", ".join(f"'{sql_literal(d)}'" for d in sorted(allowed_documents))
    return f"AND D.{column} IN ({docs_list})"


def build_salesman_filter(sc: str | None, salesman_id: str | None) -> str:
    if not sc or not salesman_id:
        return ""
    return f"AND LTRIM(RTRIM(CAST(D.{sc} AS VARCHAR(50)))) = '{sql_literal(salesman_id)}'"



