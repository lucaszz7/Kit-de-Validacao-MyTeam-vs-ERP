from typing import Any, Protocol 

class DatabaseExecutor(Protocol):

    def execute(self, query: str) -> Any:
        ...

def normalize_text(value):

    if value is None:
        return ""

    return str(value).strip()

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

def get_integrated_sales_documents(db_mss: DatabaseExecutor, allowed_documents=None):

    query = """ 
    SELECT
        DCCTPD,
        COUNT(*) AS TotalDocumentos,
        SUM(DCCVLL) AS TotalLiquido,
        SUM(DCCVLI) AS TotalIliquido
    FROM STMSDCC
    GROUP BY DCCTPD
    ORDER BY DCCTPD
"""
    rows = db_mss.execute(query)
    allowed = {normalize_text(doc) for doc in allowed_documents or []}

    return[
        {
            "documento": normalize_text(row[0]),
            "total_documentos": row[1],
            "total_liquido": row[2] or 0,
            "total_iliquido": row[3] or 0
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
# VALIDAÇÃO
# ==========================================================

def validate_sales_documents(db, db_mss):

    issues = []

    docs_bo = get_documents_configured_in_bo(db_mss)
    
    docs_erp = get_sale_documents_in_erp(db)

    docs_sales = get_sales_documents_in_sales_table(db)

    integrated_documents = get_integrated_sales_documents(db_mss, docs_bo | docs_erp)

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
                    f"{doc} está configuradoo no BackOffice "
                    "mas não existe no ERP"
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
                    "mas nãoo está configurado no BackOffice."
                )
            }
        )

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
            sorted(docs_sales)
    }
