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
    dt = date_column or "DCCDTA"

    if start_date:
        filters.append(f"D.{dt} >= '{sql_literal(start_date.replace('-', ''))}'")

    if end_date:
        filters.append(f"D.{dt} <= '{sql_literal(end_date.replace('-', ''))}'")

    if salesman_column and salesman_id:
        filters.append("LTRIM(RTRIM(CAST(D." f"{salesman_column} AS VARCHAR(50)))) = '{sql_literal(salesman_id)}'")

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
# Valores do ERP (TotalNetAmount) para comparar com MSS
# ==========================================================

def get_erp_order_values(db: DatabaseExecutor):
    query = """
    SELECT
        ST.TransDocument,
        CAST(ST.SalesmanID AS VARCHAR(50)) AS SalesmanID,
        COALESCE(S.SalesmanName, '') AS SalesmanName,
        COUNT(*) AS TotalQtd,
        SUM(ST.TotalNetAmount) AS TotalLiquido
    FROM SaleTransaction ST
    INNER JOIN Documents DC
        ON ST.TransDocument = DC.TransDocumentID
    LEFT JOIN Salesman S
        ON ST.SalesmanID = S.SalesmanID
    WHERE DC.TransactionNatureID = 1060
    GROUP BY ST.TransDocument, ST.SalesmanID, S.SalesmanName
    """
    rows = db.execute(query)
    result = {}
    for row in rows:
        doc = normalize_text(row[0])
        salesman_id = normalize_text(row[1])
        salesman_name = normalize_text(row[2])
        qtd = row[3]
        total = row[4] or 0
        key = (doc, salesman_id)
        result[key] = {
            "qtd": qtd,
            "total": total,
            "salesman_name": salesman_name
        }
    return result


# ==========================================================
# # VALIDAÇÃO AUTOMÁTICA
# ==========================================================

# ==========================================================
# Validação do campo vendedor (DCCACL_38) nos documentos
# ==========================================================

def check_salesman_field_filled(db_mss: DatabaseExecutor, allowed_documents: set | None = None, start_date: str | None = None, end_date: str | None = None, salesman_id: str | None = None):
    columns = get_table_columns(db_mss, "STMSDCC")
    date_column = "DCCDTA" if "DCCDTA" in columns else None
    salesman_column = None
    for col in ["DCCVND", "DCCACL_38", "DCCCVD"]:
        if col in columns:
            salesman_column = col
            break

    docs_filter = ""
    if allowed_documents:
        docs_list = ", ".join(f"'{sql_literal(d)}'" for d in sorted(allowed_documents))
        docs_filter = f"AND D.DCCTPD IN ({docs_list})"

    date_filter = ""
    dt = date_column or "DCCDTA"
    if start_date:
        date_filter += f" AND D.{dt} >= '{sql_literal(start_date.replace('-', ''))}'"
    if end_date:
        date_filter += f" AND D.{dt} <= '{sql_literal(end_date.replace('-', ''))}'"

    salesman_filter = ""
    if salesman_column and salesman_id:
        salesman_filter = f"AND CAST(D.{salesman_column} AS VARCHAR(50)) = '{sql_literal(salesman_id)}'"

    query = f"""
    SELECT
        COUNT(*) AS TotalDocumentos,
        SUM(CASE
            WHEN D.DCCACL_38 IS NULL
              OR LTRIM(RTRIM(CAST(D.DCCACL_38 AS VARCHAR(50)))) = ''
              OR CAST(D.DCCACL_38 AS VARCHAR(50)) = '0'
            THEN 1
            ELSE 0
        END) AS SemVendedor
    FROM STMSDCC D
    WHERE D.DCCANU = 'N'
      AND D.DCCCLI <> ''
      AND D.DCCTSF <> 'FC'
      {docs_filter}
      {date_filter}
      {salesman_filter}
    """
    row = db_mss.execute(query)
    if not row:
        return None

    total = row[0][0] or 0
    sem_vendedor = row[0][1] or 0

    if total == 0:
        return None

    percentagem = round((sem_vendedor / total) * 100, 1)

    docs_problematicos = []
    if sem_vendedor > 0:
        query_exemplos = f"""
        SELECT TOP 20
            D.DCCTPD AS Documento,
            D.DCCSER AS Serie,
            D.DCCNDC AS Numero,
            ISNULL(CAST(D.DCCACL_38 AS VARCHAR(50)), '(vazio)') AS Vendedor
        FROM STMSDCC D
        WHERE D.DCCANU = 'N'
          AND D.DCCCLI <> ''
          AND D.DCCTSF <> 'FC'
          AND (
              D.DCCACL_38 IS NULL
              OR LTRIM(RTRIM(CAST(D.DCCACL_38 AS VARCHAR(50)))) = ''
              OR CAST(D.DCCACL_38 AS VARCHAR(50)) = '0'
          )
          {docs_filter}
          {date_filter}
          {salesman_filter}
        ORDER BY D.DCCDTA DESC
        """
        exemplos = db_mss.execute(query_exemplos)
        for ex in exemplos:
            docs_problematicos.append(f"{ex[0]} Série {ex[1]} N.º {ex[2]} (vendedor: {ex[3]})")

    status = "OK" if sem_vendedor == 0 else "Warning"
    mensagem = (
        f"{sem_vendedor} de {total} documentos sem código de vendedor ({percentagem}%)."
        if sem_vendedor > 0
        else f"Todos os {total} documentos têm código de vendedor preenchido."
    )

    return {"status": status, "total": total, "sem_vendedor": sem_vendedor, "percentagem": percentagem, "mensagem": mensagem, "exemplos": docs_problematicos}


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

    erp_values = get_erp_order_values(db)

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

    salesman_field = check_salesman_field_filled(db_mss, allowed_documents=docs_bo | docs_erp, start_date=start_date, end_date=end_date, salesman_id=salesman_id)

    return {

        "success": len(issues) == 0,

        "total_issues": len(issues),

        "issues": issues,

        "documents_configured_bo": sorted(docs_bo),

        "documents_erp": sorted(docs_erp),

        "documents_integrated": integrated_documents,

        "documents_sales": sorted(docs_sales),

        "erp_values": erp_values,

        "salesman_field": salesman_field,
    }
