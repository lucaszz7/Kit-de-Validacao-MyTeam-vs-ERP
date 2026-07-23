from modulos.sage50.queries_base import (
    DatabaseExecutor,
    build_docs_filter,
    detect_salesman_column,
    normalize_text,
    sql_literal,
)

# ==========================================================================================================================================================
# Documentos configurados no BackOffice
# ==========================================================================================================================================================

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

# ==========================================================================================================================================================
# Documentos de encomenda existentes no ERP
# ==========================================================================================================================================================

def get_order_documents_in_erp(db: DatabaseExecutor, allowed_documents: set | None = None):

    docs_filter = ""
    if allowed_documents:
        docs_list = ", ".join(f"'{sql_literal(d)}'" for d in sorted(allowed_documents))
        docs_filter = f"WHERE DC.TransDocumentID IN ({docs_list})"

    query = f"""
    SELECT DISTINCT
        DC.TransDocumentID
    FROM Documents DC
    {docs_filter}
    """
    rows = db.execute(query)

    return {
        normalize_text(row[0])
        for row in rows
        if row[0]
    }

# ==========================================================================================================================================================
# Documentos ja integrados no MyTeam
# ==========================================================================================================================================================

def get_integrated_order_documents(db_mss: DatabaseExecutor, allowed_documents: set | None = None):

    salesman_column = detect_salesman_column(db_mss)

    salesman_select = (
        f"LTRIM(RTRIM(CAST(D.{salesman_column} AS VARCHAR(50))))"
        if salesman_column
        else "''"
    )
    salesman_name_select = "COALESCE(MAX(U.USRNOM), '')" if salesman_column else "''"
    join_clause = (
        f"LEFT JOIN MSUSR U ON LTRIM(RTRIM(CAST(D.{salesman_column} AS VARCHAR(50)))) = LTRIM(RTRIM(CAST(U.USRVND AS VARCHAR(50))))"
        if salesman_column
        else ""
    )
    group_by = (
        f"GROUP BY D.DCCTPD, LTRIM(RTRIM(CAST(D.{salesman_column} AS VARCHAR(50))))"
        if salesman_column
        else "GROUP BY D.DCCTPD"
    )

    docs_filter = ""
    if allowed_documents:
        docs_list = ", ".join(f"'{sql_literal(d)}'" for d in sorted(allowed_documents))
        docs_filter = f"AND D.DCCTPD IN ({docs_list})"

    query = f"""
    SELECT
        D.DCCTPD,
        {salesman_select} AS CodigoVendedor,
        {salesman_name_select} AS NomeVendedor,
        COUNT(*) AS TotalDocumentos,
        SUM(D.DCCVLL) AS TotalLiquido
    FROM STMSDCC D
    {join_clause}
    WHERE D.DCCANU = 'N'
      AND D.DCCCLI <> ''
      AND D.DCCTSF <> 'FC'
      {docs_filter}
    {group_by}
    ORDER BY D.DCCTPD, CodigoVendedor
    """
    rows = db_mss.execute(query)

    return [
        {
            "documento": normalize_text(row[0]),
            "codigo_vendedor": normalize_text(row[1]),
            "nome_vendedor": normalize_text(row[2]),
            "total_documentos": row[3],
            "total_liquido": row[4] or 0,
        }
        for row in rows
    ]

# ==========================================================================================================================================================
# Documentos existentes na tabela de encomendas
# ==========================================================================================================================================================

def get_order_documents_in_sales_table(db: DatabaseExecutor, allowed_documents: set | None = None):

    docs_filter = ""
    if allowed_documents:
        docs_list = ", ".join(f"'{sql_literal(d)}'" for d in sorted(allowed_documents))
        docs_filter = f"WHERE ST.TransDocument IN ({docs_list})"

    query = f"""
    SELECT DISTINCT
        ST.TransDocument
    FROM SaleTransaction ST
    WHERE ST.TransStatus = 0
      {docs_filter.replace('WHERE', 'AND')}
    """

    rows = db.execute(query)

    return {
        normalize_text(row[0])
        for row in rows
        if row[0]
    }

def get_erp_order_values_by_year(db: DatabaseExecutor, allowed_documents: set | None = None, ano_atual: int = 2026):

    docs_filter = ""
    if allowed_documents:
        docs_list = ", ".join(f"'{sql_literal(d)}'" for d in sorted(allowed_documents))
        docs_filter = f"AND ST.TransDocument IN ({docs_list})"

    query = f"""
    SELECT
        ST.TransDocument,
        LTRIM(RTRIM(CAST(ST.SalesmanID AS VARCHAR(50)))) AS SalesmanID,
        MONTH(ST.CreateDate) AS MES,
        CASE WHEN YEAR(ST.CreateDate) = {ano_atual - 1} THEN COUNT(*) ELSE 0 END AS QT_ANO_ANT,
        CASE WHEN YEAR(ST.CreateDate) = {ano_atual - 1} THEN SUM(ST.TotalNetAmount) ELSE 0 END AS TOTAL_ANO_ANT,
        CASE WHEN YEAR(ST.CreateDate) = {ano_atual} THEN COUNT(*) ELSE 0 END AS QT_ANO_ATU,
        CASE WHEN YEAR(ST.CreateDate) = {ano_atual} THEN SUM(ST.TotalNetAmount) ELSE 0 END AS TOTAL_ANO_ATU
    FROM SaleTransaction ST
    WHERE ST.TransStatus = 0
      AND YEAR(ST.CreateDate) IN ({ano_atual - 1}, {ano_atual})
      {docs_filter}
    GROUP BY ST.TransDocument, ST.SalesmanID, MONTH(ST.CreateDate), YEAR(ST.CreateDate)
    """
    rows = db.execute(query)
    result = {}
    for row in rows:
        doc = normalize_text(row[0])
        salesman_id = normalize_text(row[1])
        month = int(row[2])
        key = (doc, salesman_id, month)
        existing = result.get(key, {"qtd_ano_ant": 0, "total_ano_ant": 0.0, "qtd_ano_atu": 0, "total_ano_atu": 0.0})
        existing["qtd_ano_ant"] += row[3] or 0
        existing["total_ano_ant"] += float(row[4] or 0)
        existing["qtd_ano_atu"] += row[5] or 0
        existing["total_ano_atu"] += float(row[6] or 0)
        result[key] = existing
    return result


# ==========================================================================================================================================================
# Validacao do campo vendedor nos documentos
# ==========================================================================================================================================================

def check_salesman_field_filled(db_mss: DatabaseExecutor, allowed_documents: set | None = None):

    salesman_column = detect_salesman_column(db_mss)
    sc = salesman_column or "DCCACL_38"

    docs_filter = ""
    if allowed_documents:
        docs_list = ", ".join(f"'{sql_literal(d)}'" for d in sorted(allowed_documents))
        docs_filter = f"AND D.DCCTPD IN ({docs_list})"

    query = f"""
    SELECT
        COUNT(*) AS TotalDocumentos,
        SUM(CASE
            WHEN D.{sc} IS NULL
              OR LTRIM(RTRIM(CAST(D.{sc} AS VARCHAR(50)))) = ''
              OR LTRIM(RTRIM(CAST(D.{sc} AS VARCHAR(50)))) = '0'
            THEN 1
            ELSE 0
        END) AS SemVendedor
    FROM STMSDCC D
    WHERE D.DCCANU = 'N'
      AND D.DCCCLI <> ''
      AND D.DCCTSF <> 'FC'
      {docs_filter}
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
            ISNULL(LTRIM(RTRIM(CAST(D.{sc} AS VARCHAR(50)))), '(vazio)') AS Vendedor
        FROM STMSDCC D
        WHERE D.DCCANU = 'N'
          AND D.DCCCLI <> ''
          AND D.DCCTSF <> 'FC'
          AND (
              D.{sc} IS NULL
              OR LTRIM(RTRIM(CAST(D.{sc} AS VARCHAR(50)))) = ''
              OR LTRIM(RTRIM(CAST(D.{sc} AS VARCHAR(50)))) = '0'
          )
          {docs_filter}
        ORDER BY D.DCCDTA DESC
        """
        exemplos = db_mss.execute(query_exemplos)
        for ex in exemplos:
            docs_problematicos.append(
                f"{ex[0]} Serie {ex[1]} N.o {ex[2]} (vendedor: {ex[3]})"
            )

    status = "OK" if sem_vendedor == 0 else "Warning"
    mensagem = (
        f"{sem_vendedor} de {total} documentos sem codigo de vendedor ({percentagem}%)."
        if sem_vendedor > 0
        else f"Todos os {total} documentos tem codigo de vendedor preenchido."
    )

    return {
        "status": status,
        "total": total,
        "sem_vendedor": sem_vendedor,
        "percentagem": percentagem,
        "mensagem": mensagem,
        "exemplos": docs_problematicos,
    }


# ==========================================================================================================================================================
# Contagem de documentos MSS (Qt. MSS na grelha — encomendas)
# ==========================================================================================================================================================

def get_mss_order_doc_counts(
    db_mss: DatabaseExecutor,
    allowed_documents: set | None = None,
    ano_atual: int = 2026,
):
    sc = detect_salesman_column(db_mss)
    ss = f"LTRIM(RTRIM(CAST(D.{sc} AS VARCHAR(50))))" if sc else "''"
    df = build_docs_filter(allowed_documents)

    query = f"""
    SELECT
        SUBSTRING(D.DCCDTA, 5, 2) AS MES_NUM,
        {ss} AS CODIGO_VENDEDOR,
        D.DCCTPD AS DOCUMENTO,
        COUNT(*) AS QUANTIDADE
    FROM STMSDCC D
    WHERE D.DCCANU = 'N'
      AND D.DCCCLI <> ''
      AND D.DCCTSF <> 'FC'
      AND YEAR(D.DCCDTA) IN ({ano_atual} - 1, {ano_atual})
      {df}
    GROUP BY SUBSTRING(D.DCCDTA, 5, 2), {ss}, D.DCCTPD
    """
    rows = db_mss.execute(query)
    return [
        {
            "mes_num": normalize_text(row[0]),
            "codigo_vendedor": normalize_text(row[1]),
            "documento": normalize_text(row[2]),
            "quantidade": row[3] or 0,
        }
        for row in rows
    ]


# ==========================================================================================================================================================
# Contagem de documentos ERP (Qt. ERP na grelha — encomendas)
# ==========================================================================================================================================================

def get_erp_order_doc_counts(
    db: DatabaseExecutor,
    allowed_documents: set | None = None,
    ano_atual: int = 2026,
):
    docs_filter = ""
    if allowed_documents:
        docs_list = ", ".join(f"'{sql_literal(d)}'" for d in sorted(allowed_documents))
        docs_filter = f"AND ST.TransDocument IN ({docs_list})"

    query = f"""
    SELECT
        ST.TransDocument,
        LTRIM(RTRIM(CAST(ST.SalesmanID AS VARCHAR(50)))) AS SalesmanID,
        MONTH(ST.CreateDate) AS MES,
        COUNT(*) AS QUANTIDADE
    FROM SaleTransaction ST
    WHERE ST.TransStatus = 0
      AND YEAR(ST.CreateDate) IN ({ano_atual} - 1, {ano_atual})
      {docs_filter}
    GROUP BY ST.TransDocument, ST.SalesmanID, MONTH(ST.CreateDate)
    """
    rows = db.execute(query)
    result = {}
    for row in rows:
        doc = normalize_text(row[0])
        salesman_id = normalize_text(row[1])
        month = int(row[2])
        key = (doc, salesman_id, month)
        result[key] = (result.get(key) or 0) + (row[3] or 0)
    return result


# ==========================================================================================================================================================
# Monthly order breakdown (ano anterior vs atual)
# ==========================================================================================================================================================

def get_monthly_order_breakdown(db_mss: DatabaseExecutor, allowed_documents: set | None = None):
    ano_atual = 2026

    salesman_column = detect_salesman_column(db_mss)

    salesman_select = (
        f"LTRIM(RTRIM(CAST(D.{salesman_column} AS VARCHAR(50))))"
        if salesman_column
        else "''"
    )
    salesman_name_select = "COALESCE(MAX(U.USRNOM), '')" if salesman_column else "''"
    join_clause = (
        f"LEFT JOIN MSUSR U ON LTRIM(RTRIM(CAST(D.{salesman_column} AS VARCHAR(50)))) = LTRIM(RTRIM(CAST(U.USRVND AS VARCHAR(50))))"
        if salesman_column
        else ""
    )
    group_by_cols = (
        f"SUBSTRING(D.DCCDTA, 5, 2), LTRIM(RTRIM(CAST(D.{salesman_column} AS VARCHAR(50)))), D.DCCTPD"
        if salesman_column
        else "SUBSTRING(D.DCCDTA, 5, 2), D.DCCTPD"
    )

    docs_filter = ""
    if allowed_documents:
        docs_list = ", ".join(f"'{sql_literal(d)}'" for d in sorted(allowed_documents))
        docs_filter = f"AND D.DCCTPD IN ({docs_list})"

    query = f"""
    SELECT
        CASE SUBSTRING(D.DCCDTA, 5, 2)
            WHEN '01' THEN 'Janeiro' WHEN '02' THEN 'Fevereiro'
            WHEN '03' THEN 'Marco' WHEN '04' THEN 'Abril'
            WHEN '05' THEN 'Maio' WHEN '06' THEN 'Junho'
            WHEN '07' THEN 'Julho' WHEN '08' THEN 'Agosto'
            WHEN '09' THEN 'Setembro' WHEN '10' THEN 'Outubro'
            WHEN '11' THEN 'Novembro' WHEN '12' THEN 'Dezembro'
            ELSE ''
        END AS MES,
        SUBSTRING(D.DCCDTA, 5, 2) AS MES_NUM,
        {salesman_name_select} AS VENDEDOR,
        {salesman_select} AS CODIGO_VENDEDOR,
        D.DCCTPD AS DOCUMENTO,
        SUM(CASE WHEN LEFT(D.DCCDTA, 4) = {ano_atual} - 1
            THEN 1 ELSE 0 END) AS QT_MSS_ANO_ANT,
        SUM(CASE WHEN LEFT(D.DCCDTA, 4) = {ano_atual} - 1
            THEN CASE WHEN D.DCCACL_27 <> 'S' THEN D.DCCVLL ELSE -D.DCCVLL END
            ELSE 0 END) AS VENDAS_ANO_ANTERIOR,
        SUM(CASE WHEN LEFT(D.DCCDTA, 4) = {ano_atual}
            THEN 1 ELSE 0 END) AS QT_MSS_ANO_ATU,
        SUM(CASE WHEN LEFT(D.DCCDTA, 4) = {ano_atual}
            THEN CASE WHEN D.DCCACL_27 <> 'S' THEN D.DCCVLL ELSE -D.DCCVLL END
            ELSE 0 END) AS VENDAS_ANO_ATUAL
    FROM STMSDCC D
    {join_clause}
    WHERE D.DCCANU = 'N'
      AND D.DCCCLI <> ''
      AND LEFT(D.DCCDTA, 4) BETWEEN {ano_atual} - 1 AND {ano_atual}
      {docs_filter}
      AND D.DCCTSF <> 'FC'
    GROUP BY {group_by_cols}
    ORDER BY {group_by_cols}
    """
    rows = db_mss.execute(query)

    results = []
    for row in rows:
        ant = row[6] or 0
        act = row[8] or 0
        results.append({
            "mes": normalize_text(row[0]),
            "mes_num": normalize_text(row[1]),
            "vendedor": normalize_text(row[2]),
            "codigo_vendedor": normalize_text(row[3]),
            "documento": normalize_text(row[4]),
            "qt_mss_ano_ant": row[5] or 0,
            "vendas_ano_anterior": ant,
            "qt_mss_ano_atu": row[7] or 0,
            "vendas_ano_atual": act,
            "vendas_totais": ant + act,
        })
    return results


# ==========================================================================================================================================================
# VALIDACAO
# ==========================================================================================================================================================

def validate_order_documents(
    db,
    db_mss,
):

    issues = []

    docs_bo = get_documents_configured_in_bo(db_mss)

    docs_erp = get_order_documents_in_erp(db, allowed_documents=docs_bo)

    docs_sales = get_order_documents_in_sales_table(db, allowed_documents=docs_bo)

    integrated_documents = get_integrated_order_documents(db_mss, allowed_documents=docs_bo | docs_erp)

    docs_integrated = {
        row["documento"]
        for row in integrated_documents
    }

    for doc in sorted(docs_bo - docs_erp):
        issues.append(
            {
                "type": "MISSING_IN_ERP",
                "message": f"{doc} esta configurado no Backoffice mas nao existe no ERP."
            }
        )

    for doc in sorted(docs_integrated - docs_erp):
        issues.append(
            {
                "type": "INTEGRATED_NOT_IN_ERP",
                "message": f"{doc} ja foi integrado no MyTeam mas nao existe no ERP."
            }
        )

    for doc in sorted(docs_sales - docs_bo):
        issues.append(
            {
                "type": "SALES_NOT_CONFIGURED",
                "message": f"{doc} existe na tabela de encomendas mas nao esta configurado no Backoffice."
            }
        )

    monthly = get_monthly_order_breakdown(db_mss, allowed_documents=docs_bo | docs_erp)

    erp_values_by_year = get_erp_order_values_by_year(db, allowed_documents=docs_bo)

    mss_counts = get_mss_order_doc_counts(db_mss, allowed_documents=docs_bo | docs_erp)
    mss_count_map = {}
    for mc in mss_counts:
        key = (mc["documento"], mc["codigo_vendedor"], int(mc["mes_num"]))
        mss_count_map[key] = mc["quantidade"]

    erp_counts = get_erp_order_doc_counts(db, allowed_documents=docs_bo | docs_erp)

    for line in monthly:
        mes_num = int(line.get("mes_num", 0))
        key = (line["documento"], line["codigo_vendedor"], mes_num)
        erp = erp_values_by_year.get(key, {})
        line["qt_erp_ano_ant"] = erp.get("qtd_ano_ant", 0)
        line["erp_ano_ant"] = erp.get("total_ano_ant", 0.0)
        line["qt_erp_ano_atu"] = erp.get("qtd_ano_atu", 0)
        line["erp_ano_atu"] = erp.get("total_ano_atu", 0.0)
        line["qt_mss"] = mss_count_map.get(key, 0)
        line["qt_erp"] = erp_counts.get(key, 0)

    salesman_field = check_salesman_field_filled(db_mss, allowed_documents=docs_bo | docs_erp)

    return {
        "success": len(issues) == 0,
        "total_issues": len(issues),
        "issues": issues,
        "documents_configured_bo": sorted(docs_bo),
        "documents_erp": sorted(docs_erp),
        "documents_integrated": integrated_documents,
        "documents_sales": sorted(docs_sales),
        "erp_values_by_year": erp_values_by_year,
        "monthly_breakdown": monthly,
        "salesman_field": salesman_field,
    }
