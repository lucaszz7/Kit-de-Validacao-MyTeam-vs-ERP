from typing import Any, Protocol, TypedDict


class DatabaseExecutor(Protocol):

    def execute(self, query: str) -> Any:
        ...


class ValidationIssue(TypedDict):

    type: str
    message: str


def normalize_text(value):

    if value is None:
        return ""

    return str(value).strip()


def sql_literal(value: str) -> str:
    """Escapa texto usado em filtros SQL simples."""

    return value.replace("'", "''")


def get_table_columns(db: DatabaseExecutor, table_name: str) -> set[str]:
    """Devolve as colunas existentes numa tabela da base MSS."""

    rows = db.execute(
        f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = '{sql_literal(table_name)}'
        """
    )

    return {normalize_text(row[0]).upper() for row in rows}


def build_integrated_filters(
    date_column: str | None,
    salesman_column: str | None,
    start_date: str | None = None,
    end_date: str | None = None,
    salesman_id: str | None = None,
) -> str:
    """Monta o WHERE dos documentos integrados sem misturar regras de UI."""

    filters = []

    if date_column and start_date:
        filters.append(f"D.{date_column} >= '{sql_literal(start_date)}'")

    if date_column and end_date:
        filters.append(f"D.{date_column} < DATEADD(day, 1, '{sql_literal(end_date)}')")

    if salesman_column and salesman_id:
        filters.append(
            "LTRIM(RTRIM(CAST(D."
            f"{salesman_column} AS VARCHAR(50)))) = '{sql_literal(salesman_id)}'"
        )

    return f"WHERE {' AND '.join(filters)}" if filters else ""


# ==========================================================
# Documentos configurados no Backoffice
# ==========================================================

def get_documents_configured_in_bo(db_mss: DatabaseExecutor):

    query = """
    SELECT TETVAL
    FROM BOMYTTET
    WHERE TETPAR = 'DOCS_ENC'
    """

    rows = db_mss.execute(query)

    if not rows:
        return set()

    docs_string = normalize_text(rows[0][0])

    return {
        doc.strip()
        for doc in docs_string.split(";")
        if doc.strip()
    }

# ==========================================================
# Documentos de encomenda existentes no ERP
# ==========================================================

def get_order_documents_in_erp(db: DatabaseExecutor):

    query = """
    SELECT TransDocumentID
    FROM Documents
    WHERE TransactionNatureID = 1060
    """

    rows = db.execute(query)

    return {
        normalize_text(row[0])
        for row in rows
        if row[0]
    }


# ==========================================================
# Documentos já integrados no MyTeam
# ==========================================================

def get_integrated_documents(
    db_mss: DatabaseExecutor,
    allowed_documents=None,
    start_date: str | None = None,
    end_date: str | None = None,
    salesman_id: str | None = None,
):

    columns = get_table_columns(db_mss, "STMSDCC")
    date_column = "DCCDTA" if "DCCDTA" in columns else None
    salesman_column = None
    for col in ["DCCVND", "DCCACL_38", "DCCCVD"]:
        if col in columns:
            salesman_column = col
            break
    where_clause = build_integrated_filters(
        date_column,
        salesman_column,
        start_date,
        end_date,
        salesman_id,
    )

    salesman_select = (
        f"CAST(D.{salesman_column} AS VARCHAR(50))"
        if salesman_column
        else "''"
    )
    salesman_name_select = "COALESCE(MAX(U.USRNOM), '')" if salesman_column else "''"
    join_clause = (
        f"""
    LEFT JOIN MSUSR U
        ON CAST(D.{salesman_column} AS VARCHAR(50)) = CAST(U.USRVND AS VARCHAR(50))
        """
        if salesman_column
        else ""
    )
    group_by = (
        f"GROUP BY D.DCCTPD, CAST(D.{salesman_column} AS VARCHAR(50))"
        if salesman_column
        else "GROUP BY D.DCCTPD"
    )

    query = """
    SELECT
        D.DCCTPD,
        {salesman_select} AS CodigoVendedor,
        {salesman_name_select} AS NomeVendedor,
        COUNT(*) AS TotalDocumentos,
        SUM(D.DCCVLL) AS TotalLiquido
    FROM STMSDCC D
    {join_clause}
    {where_clause}
    {group_by}
    ORDER BY D.DCCTPD, CodigoVendedor
    """.format(
        salesman_select=salesman_select,
        salesman_name_select=salesman_name_select,
        join_clause=join_clause,
        where_clause=where_clause,
        group_by=group_by,
    )

    rows = db_mss.execute(query)
    allowed = {normalize_text(doc) for doc in allowed_documents or []}

    return [
        {
            "documento": normalize_text(row[0]),
            "codigo_vendedor": normalize_text(row[1]),
            "nome_vendedor": normalize_text(row[2]),
            "total_documentos": row[3],
            "total_liquido": row[4] or 0
        }
        for row in rows
        if not allowed or normalize_text(row[0]) in allowed
    ]


# ==========================================================
# Documentos existentes na tabela de vendas
# ==========================================================

def get_documents_in_sales_table(db: DatabaseExecutor):

    query = """
    SELECT DISTINCT
        ST.TransDocument
    FROM SaleTransaction ST
    INNER JOIN Documents DC
        ON ST.TransDocument = DC.TransDocumentID
    WHERE DC.TransactionNatureID = 1060
    """

    rows = db.execute(query)

    return {
        normalize_text(row[0])
        for row in rows
        if row[0]
    }


# ==========================================================
# # VALIDAÇÃO AUTOMÁTICA
# ==========================================================

def validate_order_documents(
    db,
    db_mss,
    start_date: str | None = None,
    end_date: str | None = None,
    salesman_id: str | None = None,
):

    issues = []

    docs_bo = get_documents_configured_in_bo(db_mss)

    docs_erp = get_order_documents_in_erp(db)

    docs_sales = get_documents_in_sales_table(db)

    integrated_documents = get_integrated_documents(
        db_mss,
        docs_bo | docs_erp,
        start_date=start_date,
        end_date=end_date,
        salesman_id=salesman_id,
    )

    docs_integrated = {
        row["documento"]
        for row in integrated_documents
    }

# -------------------------------------------------------------------
# Configurados no BO mas não existem no ERP
# -------------------------------------------------------------------

    for doc in sorted(docs_bo - docs_erp):

        issues.append(
            {
                "type": "MISSING_IN_ERP",
                "message": (
                    f"{doc} está configurado no Backoffice "
                    "mas não existe no ERP."
                )
            }
        )

# -------------------------------------------------------------------
# Existem no ERP mas não estão configurados no BO
# -------------------------------------------------------------------

    for doc in sorted(docs_erp - docs_bo):

        issues.append(
            {
                "type": "MISSING_IN_BO",
                "message": (
                    f"{doc} existe no ERP "
                    "mas não está configurado no Backoffice."
                )
            }
        )

# -------------------------------------------------------------------
# Integrados no MyTeam mas não existem no ERP
# -------------------------------------------------------------------

    for doc in sorted(docs_integrated - docs_erp):

        issues.append(
            {
                "type": "INTEGRATED_NOT_IN_ERP",
                "message": (
                    f"{doc} já foi integrado no MyTeam "
                    "mas não existe no ERP."
                )
            }
        )

# -------------------------------------------------------------------
# Existem na tabela de vendas mas não estão configurados no BO
# -------------------------------------------------------------------

    for doc in sorted(docs_sales - docs_bo):

        issues.append(
            {
                "type": "SALES_NOT_CONFIGURED",
                "message": (
                    f"{doc} existe na tabela de vendas "
                    "mas não está configurado no Backoffice."
                )
            }
        )

    return {

        "success": len(issues) == 0,

        "total_issues": len(issues),

        "issues": issues,

        "documents_configured_bo": sorted(docs_bo),

        "documents_erp": sorted(docs_erp),

        "documents_integrated": integrated_documents,

        "documents_sales": sorted(docs_sales)
    }
