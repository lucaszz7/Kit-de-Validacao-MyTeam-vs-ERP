from typing import Any, Protocol 


class DatabaseExecutor(Protocol):

    def execute(self, query: str) -> Any:
        ...

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
        filters.append(
            "LTRIM(RTRIM(CAST(D."
            f"{salesman_column} AS VARCHAR(50)))) = '{sql_literal(salesman_id)}'"
        )

    return f"WHERE {' AND '.join(filters)}" if filters else ""

# ==========================================================
# Documentos configurados no BackOffice
# ==========================================================

def get_documents_configured_in_bo(db_mss: DatabaseExecutor):

    query = """
    SELECT TETVAL
    FROM BOMYTTET
    WHERE TETPAR = 'DOCS_VEN'
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
# Documentos de venda existentes no ERP
# ==========================================================

def get_sale_documents_in_erp(db: DatabaseExecutor):

    query = """
    SELECT TransDocumentID
    FROM Documents
    WHERE TransactionNatureID IN
    (
        1001,
        1002,
        1003,
        1004,
        1005
    )
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

def get_integrated_sales_documents(
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
        SUM(D.DCCVLL) AS TotalLiquido,
        SUM(D.DCCVLI) AS TotalIliquido
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

    return[
        {
            "documento": normalize_text(row[0]),
            "codigo_vendedor": normalize_text(row[1]),
            "nome_vendedor": normalize_text(row[2]),
            "total_documentos": row[3],
            "total_liquido": row[4] or 0,
            "total_iliquido": row[5] or 0
        }
        for row in rows
        if not allowed or normalize_text(row[0]) in allowed
    ]

# ==========================================================
# Documentos existentes na tabela de vendas
# ==========================================================

def get_sales_documents_in_sales_table(db: DatabaseExecutor):

    query = """
    SELECT DISTINCT
        ST.TransDocument

    FROM SaleTransaction ST

    INNER JOIN Documents DC
        ON ST.Transdocument = DC.TransDocumentID

    WHERE DC.TransactionNatureID IN
    (
        1001,
        1002,
        1003,
        1004,
        1005
    )
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

def get_erp_sales_values(db: DatabaseExecutor):
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
    WHERE DC.TransactionNatureID IN (1001, 1002, 1003, 1004, 1005)
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
# Validação do campo vendedor (DCCACL_38) nos documentos
# ==========================================================

def check_salesman_field_filled(db_mss: DatabaseExecutor, allowed_documents: set | None = None, start_date: str | None = None, end_date: str | None = None, salesman_id: str | None = None):
    """
    Verifica se o campo de vendedor (DCCACL_38 ou similar) está preenchido
    nos documentos de venda da STMSDCC.

    Se estiver vazio/nulo/zero, o dashboard mostra 0 porque não consegue
    associar o documento a um vendedor.

    allowed_documents: se fornecido, filtra apenas esses tipos de documento (DCCTPD).
    salesman_id: se fornecido, filtra apenas documentos desse vendedor.
    """
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
            docs_problematicos.append(
                f"{ex[0]} Série {ex[1]} N.º {ex[2]} (vendedor: {ex[3]})"
            )

    status = "OK" if sem_vendedor == 0 else "Warning"
    mensagem = (
        f"{sem_vendedor} de {total} documentos sem código de vendedor ({percentagem}%)."
        if sem_vendedor > 0
        else f"Todos os {total} documentos têm código de vendedor preenchido."
    )

    return {
        "status": status,
        "total": total,
        "sem_vendedor": sem_vendedor,
        "percentagem": percentagem,
        "mensagem": mensagem,
        "exemplos": docs_problematicos,
    }


# ==========================================================
# Monthly sales breakdown (nova query)
# ==========================================================

def get_monthly_sales_breakdown(db_mss: DatabaseExecutor, allowed_documents: set | None = None, start_date: str | None = None, end_date: str | None = None, salesman_id: str | None = None):
    ano_atual = 2026

    columns = get_table_columns(db_mss, "STMSDCC")
    date_column = "DCCDTA" if "DCCDTA" in columns else None
    salesman_column = None
    for col in ["DCCVND", "DCCACL_38", "DCCCVD"]:
        if col in columns:
            salesman_column = col
            break

    salesman_filter = ""
    if salesman_column and salesman_id:
        salesman_filter = f"AND CAST(D.{salesman_column} AS VARCHAR(50)) = '{sql_literal(salesman_id)}'"

    salesman_select = (
        f"CAST(D.{salesman_column} AS VARCHAR(50))"
        if salesman_column
        else "''"
    )
    salesman_name_select = "COALESCE(MAX(U.USRNOM), '')" if salesman_column else "''"
    join_clause = (
        f"LEFT JOIN MSUSR U ON CAST(D.{salesman_column} AS VARCHAR(50)) = CAST(U.USRVND AS VARCHAR(50))"
        if salesman_column
        else ""
    )
    group_by_cols = (
        f"SUBSTRING(D.{date_column}, 5, 2), CAST(D.{salesman_column} AS VARCHAR(50)), D.DCCTPD"
        if date_column and salesman_column
        else "SUBSTRING(D.DCCDTA, 5, 2), D.DCCTPD"
    )
    order_by_cols = group_by_cols

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

    query = f"""
    SELECT
        CASE SUBSTRING(D.{date_column or 'DCCDTA'}, 5, 2)
            WHEN '01' THEN 'Janeiro' WHEN '02' THEN 'Fevereiro'
            WHEN '03' THEN 'Marco' WHEN '04' THEN 'Abril'
            WHEN '05' THEN 'Maio' WHEN '06' THEN 'Junho'
            WHEN '07' THEN 'Julho' WHEN '08' THEN 'Agosto'
            WHEN '09' THEN 'Setembro' WHEN '10' THEN 'Outubro'
            WHEN '11' THEN 'Novembro' WHEN '12' THEN 'Dezembro'
            ELSE ''
        END AS MES,
        {salesman_name_select} AS VENDEDOR,
        {salesman_select} AS CODIGO_VENDEDOR,
        D.DCCTPD AS DOCUMENTO,
        SUM(CASE WHEN LEFT(D.{date_column or 'DCCDTA'}, 4) = {ano_atual} - 1
            THEN CASE WHEN D.DCCACL_27 <> 'S' THEN D.DCCVLL ELSE -D.DCCVLL END
            ELSE 0 END) AS VENDAS_ANO_ANTERIOR,
        SUM(CASE WHEN LEFT(D.{date_column or 'DCCDTA'}, 4) = {ano_atual}
            THEN CASE WHEN D.DCCACL_27 <> 'S' THEN D.DCCVLL ELSE -D.DCCVLL END
            ELSE 0 END) AS VENDAS_ANO_ATUAL
    FROM STMSDCC D
    {join_clause}
    WHERE D.DCCANU = 'N'
      AND D.DCCCLI <> ''
      AND LEFT(D.{date_column or 'DCCDTA'}, 4) BETWEEN {ano_atual} - 1 AND {ano_atual}
      {docs_filter}
      {date_filter}
      AND D.DCCTSF <> 'FC'
      {salesman_filter}
    GROUP BY {group_by_cols}
    ORDER BY {order_by_cols}
    """
    rows = db_mss.execute(query)

    results = []
    for row in rows:
        ant = row[4] or 0
        act = row[5] or 0
        results.append({
            "mes": normalize_text(row[0]),
            "vendedor": normalize_text(row[1]),
            "codigo_vendedor": normalize_text(row[2]),
            "documento": normalize_text(row[3]),
            "vendas_ano_anterior": ant,
            "vendas_ano_atual": act,
            "vendas_totais": ant + act,
        })
    return results


# ==========================================================
# VALIDAÇÃO
# ==========================================================

def validate_sales_documents(
    db,
    db_mss,
    start_date: str | None = None,
    end_date: str | None = None,
    salesman_id: str | None = None,
):

    issues = []

    docs_bo = get_documents_configured_in_bo(db_mss)
    
    docs_erp = get_sale_documents_in_erp(db)

    docs_sales = get_sales_documents_in_sales_table(db)

    erp_values = get_erp_sales_values(db)

    integrated_documents = get_integrated_sales_documents(
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

    # --------------------------------------------------
    # Configurados no BO mas não existem no ERP
    # --------------------------------------------------

    for doc in sorted(docs_bo - docs_erp):

        issues.append(
            {
                "type": "MISSING_IN_ERP",
                "message":
                (
                    f"{doc} está configurado no BackOffice "
                    "mas não existe no ERP."
                )
            }
        )

    # --------------------------------------------------
    # Integrados mas não existem no ERP
    # --------------------------------------------------

    for doc in sorted(docs_integrated - docs_erp):

        issues.append(
            {
                "type": "INTEGRATED_NOT_IN_ERP",
                "message":
                (
                    f"{doc} já foi integrado no MyTeam "
                    "mas não existe no ERP."
                )
            }
        )

    # --------------------------------------------------
    # Existem nas vendas mas não estão configurados
    # --------------------------------------------------

    for doc in sorted(docs_sales - docs_bo):

        issues.append(
            {
                "type": "SALES_NOT_CONFIGURED",
                "message":
                (
                    f"{doc} existe na tabela de vendas "
                    "mas não está configurado no BackOffice."
                )
            }
        )

    monthly = get_monthly_sales_breakdown(db_mss, allowed_documents=docs_bo | docs_erp, start_date=start_date, end_date=end_date, salesman_id=salesman_id)

    salesman_field = check_salesman_field_filled(db_mss, allowed_documents=docs_bo | docs_erp, start_date=start_date, end_date=end_date, salesman_id=salesman_id)

    return {

        "success": len(issues) == 0,

        "total_issues": len(issues),

        "issues": issues,

        "documents_configured_bo":
            sorted(docs_bo),

        "documents_erp":
            sorted(docs_erp),
        
        "documents_integrated":
            integrated_documents,

        "documents_sales":
            sorted(docs_sales),

        "erp_values": erp_values,

        "monthly_breakdown": monthly,
        "salesman_field": salesman_field,
    }