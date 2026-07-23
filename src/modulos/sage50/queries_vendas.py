from modulos.sage50.queries_base import (
    DatabaseExecutor,
    build_docs_filter,
    build_salesman_filter,
    detect_salesman_column,
    normalize_text,
    sql_literal,
)


def _build_salesman_select(sc: str | None) -> str:
    return f"LTRIM(RTRIM(CAST(D.{sc} AS VARCHAR(50))))" if sc else "''"


def _build_salesman_name_select(sc: str | None) -> str:
    return "COALESCE(MAX(U.USRNOM), '')" if sc else "''"


def _build_join_msusr(sc: str | None) -> str:
    if not sc:
        return ""
    return f"LEFT JOIN MSUSR U ON LTRIM(RTRIM(CAST(D.{sc} AS VARCHAR(50)))) = LTRIM(RTRIM(CAST(U.USRVND AS VARCHAR(50))))"


# ==========================================================================================================
# Documentos configurados no BackOffice
# ==========================================================================================================

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

# ==========================================================================================================
# Documentos de venda existentes no ERP
# ==========================================================================================================

def get_sale_documents_in_erp(db: DatabaseExecutor):
    query = """
    SELECT TransDocumentID
    FROM Documents
    WHERE TransactionNatureID IN (1001, 1002, 1003, 1004, 1005)
    """
    rows = db.execute(query)

    return {
        normalize_text(row[0])
        for row in rows
        if row[0]
    }

# ==========================================================================================================
# Documentos já integrados no MyTeam
# ==========================================================================================================

def get_integrated_sales_documents(
    db_mss: DatabaseExecutor,
    allowed_documents=None,
    start_date: str | None = None,
    end_date: str | None = None,
    salesman_id: str | None = None,
):
    sc = detect_salesman_column(db_mss)

    ss = _build_salesman_select(sc)
    sns = _build_salesman_name_select(sc)
    jn = _build_join_msusr(sc)
    gb = f"GROUP BY D.DCCTPD, {ss}"

    filters = []
    if start_date:
        filters.append(f"D.DCCDTA >= '{sql_literal(start_date.replace('-', ''))}'")
    if end_date:
        filters.append(f"D.DCCDTA <= '{sql_literal(end_date.replace('-', ''))}'")
    if sc and salesman_id:
        filters.append(f"LTRIM(RTRIM(CAST(D.{sc} AS VARCHAR(50)))) = '{sql_literal(salesman_id)}'")
    wc = f"WHERE {' AND '.join(filters)}" if filters else ""

    query = f"""
    SELECT
        D.DCCTPD,
        {ss} AS CodigoVendedor,
        {sns} AS NomeVendedor,
        COUNT(*) AS TotalDocumentos,
        SUM(D.DCCVLL) AS TotalLiquido,
        SUM(D.DCCVLI) AS TotalIliquido
    FROM STMSDCC D
    {jn}
    {wc}
    {gb}
    ORDER BY D.DCCTPD, CodigoVendedor
    """
    rows = db_mss.execute(query)
    allowed = {normalize_text(doc) for doc in allowed_documents or []}

    return [
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

# ==========================================================================================================
# Documentos existentes na tabela de vendas
# ==========================================================================================================

def get_sales_documents_in_sales_table(db: DatabaseExecutor):
    query = """
    SELECT DISTINCT
        ST.TransDocument
    FROM SaleTransaction ST
    INNER JOIN Documents DC
        ON ST.Transdocument = DC.TransDocumentID
    WHERE DC.TransactionNatureID IN (1001, 1002, 1003, 1004, 1005)
    """
    rows = db.execute(query)

    return {
        normalize_text(row[0])
        for row in rows
        if row[0]
    }

def get_erp_sales_values_by_year(db: DatabaseExecutor, ano_atual: int = 2026):
    query = f"""
    SELECT
        ST.TransDocument,
        LTRIM(RTRIM(CAST(ST.SalesmanID AS VARCHAR(50)))) AS SalesmanID,
        MONTH(ST.CreateDate) AS MES,
        CASE WHEN YEAR(ST.CreateDate) = {ano_atual} - 1 THEN COUNT(*) ELSE 0 END AS QT_ANO_ANT,
        CASE WHEN YEAR(ST.CreateDate) = {ano_atual} - 1 THEN SUM(
            CASE
                WHEN DC.TransactionNatureID = 1005 THEN -ST.TotalNetAmount
                ELSE ST.TotalNetAmount
            END
        ) ELSE 0 END AS TOTAL_ANO_ANT,
        CASE WHEN YEAR(ST.CreateDate) = {ano_atual} THEN COUNT(*) ELSE 0 END AS QT_ANO_ATU,
        CASE WHEN YEAR(ST.CreateDate) = {ano_atual} THEN SUM(
            CASE
                WHEN DC.TransactionNatureID = 1005 THEN -ST.TotalNetAmount
                ELSE ST.TotalNetAmount
            END
        ) ELSE 0 END AS TOTAL_ANO_ATU
    FROM SaleTransaction ST
    INNER JOIN Documents DC
        ON ST.TransDocument = DC.TransDocumentID
    WHERE DC.TransactionNatureID IN (1001, 1002, 1003, 1004, 1005)
      AND ST.TransStatus = 0
      AND YEAR(ST.CreateDate) IN ({ano_atual} - 1, {ano_atual})
    GROUP BY ST.TransDocument, ST.SalesmanID, MONTH(ST.CreateDate), YEAR(ST.CreateDate)
    """
    rows = db.execute(query)
    result = {}
    for row in rows:
        key = (normalize_text(row[0]), normalize_text(row[1]), int(row[2]))
        existing = result.get(key, {"qtd_ano_ant": 0, "total_ano_ant": 0.0, "qtd_ano_atu": 0, "total_ano_atu": 0.0})
        existing["qtd_ano_ant"] += row[3] or 0
        existing["total_ano_ant"] += float(row[4] or 0)
        existing["qtd_ano_atu"] += row[5] or 0
        existing["total_ano_atu"] += float(row[6] or 0)
        result[key] = existing
    return result


# ==========================================================================================================
# Validação do campo vendedor (DCCACL_38) nos documentos
# ==========================================================================================================

def check_salesman_field_filled(db_mss: DatabaseExecutor, allowed_documents: set | None = None, start_date: str | None = None, end_date: str | None = None, salesman_id: str | None = None):
    sc = detect_salesman_column(db_mss)

    df = build_docs_filter(allowed_documents)

    date_filter = ""
    if start_date:
        date_filter += f" AND D.DCCDTA >= '{sql_literal(start_date.replace('-', ''))}'"
    if end_date:
        date_filter += f" AND D.DCCDTA <= '{sql_literal(end_date.replace('-', ''))}'"

    sf = build_salesman_filter(sc, salesman_id)

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
      {df}
      {date_filter}
      {sf}
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
          {df}
          {date_filter}
          {sf}
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


# ==========================================================================================================
# Contagem de documentos MSS (Qt. MSS na grelha)
# ==========================================================================================================

def get_mss_doc_counts(
    db_mss: DatabaseExecutor,
    allowed_documents: set | None = None,
    salesman_id: str | None = None,
    ano_atual: int = 2026,
):
    sc = detect_salesman_column(db_mss)
    ss = f"LTRIM(RTRIM(CAST(D.{sc} AS VARCHAR(50))))" if sc else "''"
    df = build_docs_filter(allowed_documents)
    sf = build_salesman_filter(sc, salesman_id)

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
      {sf}
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


# ==========================================================================================================
# Contagem de documentos ERP (Qt. ERP na grelha)
# ==========================================================================================================

def get_erp_doc_counts(db: DatabaseExecutor, ano_atual: int = 2026):
    query = f"""
    SELECT
        ST.TransDocument,
        LTRIM(RTRIM(CAST(ST.SalesmanID AS VARCHAR(50)))) AS SalesmanID,
        MONTH(ST.CreateDate) AS MES,
        COUNT(*) AS QUANTIDADE
    FROM SaleTransaction ST
    INNER JOIN Documents DC
        ON ST.TransDocument = DC.TransDocumentID
    WHERE DC.TransactionNatureID IN (1001, 1002, 1003, 1004, 1005)
      AND ST.TransStatus = 0
      AND YEAR(ST.CreateDate) IN ({ano_atual} - 1, {ano_atual})
    GROUP BY ST.TransDocument, ST.SalesmanID, MONTH(ST.CreateDate)
    """
    rows = db.execute(query)
    result = {}
    for row in rows:
        key = (normalize_text(row[0]), normalize_text(row[1]), int(row[2]))
        result[key] = (result.get(key) or 0) + (row[3] or 0)
    return result


# ==========================================================================================================
# Monthly breakdown (ano anterior vs atual) — VENDAS
# ==========================================================================================================

def get_monthly_sales_breakdown(db_mss: DatabaseExecutor, allowed_documents: set | None = None, start_date: str | None = None, end_date: str | None = None, salesman_id: str | None = None):
    ano_atual = 2026

    sc = detect_salesman_column(db_mss)

    sf = build_salesman_filter(sc, salesman_id)
    ss = _build_salesman_select(sc)
    sns = _build_salesman_name_select(sc)
    jn = _build_join_msusr(sc)
    gb = f"SUBSTRING(D.DCCDTA, 5, 2), {ss}, D.DCCTPD"

    df = build_docs_filter(allowed_documents)

    date_filter = ""
    if start_date:
        date_filter += f" AND D.DCCDTA >= '{sql_literal(start_date.replace('-', ''))}'"
    if end_date:
        date_filter += f" AND D.DCCDTA <= '{sql_literal(end_date.replace('-', ''))}'"

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
        {sns} AS VENDEDOR,
        {ss} AS CODIGO_VENDEDOR,
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
    {jn}
    WHERE D.DCCANU = 'N'
      AND D.DCCCLI <> ''
      AND LEFT(D.DCCDTA, 4) BETWEEN {ano_atual} - 1 AND {ano_atual}
      {df}
      {date_filter}
      AND D.DCCTSF <> 'FC'
      {sf}
    GROUP BY {gb}
    ORDER BY {gb}
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


# ==========================================================================================================
# VALIDAÇÃO
# ==========================================================================================================

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

    integrated_documents = get_integrated_sales_documents(
        db_mss, docs_bo | docs_erp, start_date=start_date, end_date=end_date, salesman_id=salesman_id,
    )

    docs_integrated = {row["documento"] for row in integrated_documents}

    for doc in sorted(docs_bo - docs_erp):
        issues.append({"type": "MISSING_IN_ERP", "message": f"{doc} está configurado no BackOffice mas não existe no ERP."})

    for doc in sorted(docs_integrated - docs_erp):
        issues.append({"type": "INTEGRATED_NOT_IN_ERP", "message": f"{doc} já foi integrado no MyTeam mas não existe no ERP."})

    for doc in sorted(docs_sales - docs_bo):
        issues.append({"type": "SALES_NOT_CONFIGURED", "message": f"{doc} existe na tabela de vendas mas não está configurado no BackOffice."})

    monthly = get_monthly_sales_breakdown(db_mss, allowed_documents=docs_bo | docs_erp, start_date=start_date, end_date=end_date, salesman_id=salesman_id)
    erp_values_by_year = get_erp_sales_values_by_year(db)
    mss_counts = get_mss_doc_counts(db_mss, allowed_documents=docs_bo | docs_erp, salesman_id=salesman_id)

    mss_count_map = {}
    for mc in mss_counts:
        key = (mc["documento"], mc["codigo_vendedor"], int(mc["mes_num"]))
        mss_count_map[key] = mc["quantidade"]

    erp_counts = get_erp_doc_counts(db)

    for line in monthly:
        key = (line["documento"], line["codigo_vendedor"], int(line.get("mes_num", 0)))
        erp = erp_values_by_year.get(key, {})
        line["qt_erp_ano_ant"] = erp.get("qtd_ano_ant", 0)
        line["erp_ano_ant"] = erp.get("total_ano_ant", 0.0)
        line["qt_erp_ano_atu"] = erp.get("qtd_ano_atu", 0)
        line["erp_ano_atu"] = erp.get("total_ano_atu", 0.0)
        line["qt_mss"] = mss_count_map.get(key, 0)
        line["qt_erp"] = erp_counts.get(key, 0)

    salesman_field = check_salesman_field_filled(db_mss, allowed_documents=docs_bo | docs_erp, start_date=start_date, end_date=end_date, salesman_id=salesman_id)

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