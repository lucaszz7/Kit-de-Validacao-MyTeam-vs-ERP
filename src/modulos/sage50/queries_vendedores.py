from typing import Any, Iterable, Protocol, TypedDict

from core.config_loader import load_config


class DatabaseExecutor(Protocol):

    def execute(self, query: str) -> Iterable[Any]:
        """Executa uma query SQL e devolve as linhas retornadas."""


class ValidationIssue(TypedDict, total=False):
    type: str
    message: str
    salesman_id: str
    salesman_name: str
    mss_user_code: str
    mss_user_name: str
    mapped_code: str


class SalesmenValidationResult(TypedDict):
    success: bool
    total_issues: int
    issues: list[ValidationIssue]


def get_salesmen_mapping(db: DatabaseExecutor) -> list[dict[str, str]]:
    """
    Retorna a tabela completa de mapeamento MSS vs ERP.

    Esta funcao serve para consulta visual/diagnostico bruto.
    A interface deve usar validate_salesmen(db) para diagnostico automatico.
    """

    config = load_config()
    mss_db = quote_sql_identifier(config["databases"]["mss"])
    sage_db = quote_sql_identifier(config["databases"]["sage50"])

    query = f"""
    SELECT
        'MSS' AS Origem,
        CAST(USRUSR AS VARCHAR(50)) AS CodigoVendedor,
        USRNOM AS NomeVendedor,
        CAST(USRVND AS VARCHAR(50)) AS CodigoVendedorERP
    FROM {mss_db}.dbo.MSUSR
    WHERE UPPER(LTRIM(RTRIM(USRUSR))) <> 'ADMIN'
    
    UNION ALL

    SELECT
        'ERP' AS Origem,
        CAST(SalesmanID AS VARCHAR(50)) AS CodigoVendedor,
        SalesmanName AS NomeVendedor,
        '' AS CodigoVendedorERP
    FROM {sage_db}.dbo.Salesman
    """

    rows = db.execute(query)

    return [
        {
            "origem": normalize_text(row[0]),
            "codigo_vendedor": normalize_text(row[1]),
            "nome_vendedor": normalize_text(row[2]),
            "codigo_vendedor_erp": normalize_text(row[3]),
        }
        for row in rows
    ]


def get_erp_salesmen(db: DatabaseExecutor) -> list[dict[str, str]]:
    """Retorna os vendedores do Sage 50 para filtros da interface."""

    config = load_config()
    sage_db = quote_sql_identifier(config["databases"]["sage50"])

    query = f"""
    SELECT
        CAST(SalesmanID AS VARCHAR(50)) AS SalesmanID,
        SalesmanName
    FROM {sage_db}.dbo.Salesman
    ORDER BY SalesmanName
    """

    rows = db.execute(query)

    return [
        {
            "salesman_id": normalize_text(row[0]),
            "salesman_name": normalize_text(row[1]),
        }
        for row in rows
        if normalize_text(row[0])
    ]


def get_integrated_salesmen(db_mss: DatabaseExecutor) -> list[dict[str, str]]:
    """Retorna os vendedores que existem na tabela de documentos integrados (STMSDCC).

    Consulta diretamente a tabela STMSDCC para obter os códigos de vendedor (DCCVND)
    que realmente possuem documentos integrados, com o nome obtido via MSUSR.
    Isto garante que o filtro da interface mostra apenas vendedores com dados.
    """

    # Verificar se a coluna DCCVND existe na tabela
    col_check = db_mss.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'STMSDCC'
          AND COLUMN_NAME = 'DCCVND'
    """)

    if not col_check:
        return []

    query = """
    SELECT DISTINCT
        LTRIM(RTRIM(CAST(D.DCCVND AS VARCHAR(50)))) AS CodigoVendedor,
        COALESCE(U.USRNOM, '') AS NomeVendedor
    FROM STMSDCC D
    LEFT JOIN MSUSR U
        ON CAST(D.DCCVND AS VARCHAR(50)) = CAST(U.USRVND AS VARCHAR(50))
    WHERE D.DCCVND IS NOT NULL
      AND LTRIM(RTRIM(CAST(D.DCCVND AS VARCHAR(50)))) <> ''
    ORDER BY NomeVendedor, CodigoVendedor
    """

    rows = db_mss.execute(query)

    return [
        {
            "salesman_id": normalize_text(row[0]),
            "salesman_name": normalize_text(row[1]),
        }
        for row in rows
        if normalize_text(row[0])
    ]


def get_unmapped_salesmen(db: DatabaseExecutor) -> list[ValidationIssue]:
    """Identifica vendedores do ERP que nao estao mapeados em nenhum utilizador MSS."""

    config = load_config()
    mss_db = quote_sql_identifier(config["databases"]["mss"])
    sage_db = quote_sql_identifier(config["databases"]["sage50"])

    query = f"""
    SELECT
        CAST(s.SalesmanID AS VARCHAR(50)) AS SalesmanID,
        s.SalesmanName
    FROM {sage_db}.dbo.Salesman s
    LEFT JOIN {mss_db}.dbo.MSUSR m
        ON CAST(s.SalesmanID AS VARCHAR(50)) = CAST(m.USRVND AS VARCHAR(50))
    WHERE m.USRVND IS NULL
    """

    rows = db.execute(query)

    return [
        {
            "type": "UNMAPPED_SALESMAN",
            "salesman_id": normalize_text(row[0]),
            "salesman_name": normalize_text(row[1]),
            "message": (
                f"{normalize_text(row[1])} existe no ERP, "
                "mas nao esta associado no MSS."
            ),
        }
        for row in rows
    ]


def get_invalid_mss_mappings(db: DatabaseExecutor) -> list[ValidationIssue]:
    """Identifica utilizadores MSS que apontam para vendedores ERP inexistentes."""

    config = load_config()
    mss_db = quote_sql_identifier(config["databases"]["mss"])
    sage_db = quote_sql_identifier(config["databases"]["sage50"])

    query = f"""
    SELECT
        CAST(m.USRUSR AS VARCHAR(50)) AS CodigoUtilizador,
        m.USRNOM,
        CAST(m.USRVND AS VARCHAR(50)) AS CodigoVendedorERP
    FROM {mss_db}.dbo.MSUSR m
    LEFT JOIN {sage_db}.dbo.Salesman s
        ON CAST(s.SalesmanID AS VARCHAR(50)) = CAST(m.USRVND AS VARCHAR(50))
    WHERE UPPER(LTRIM(RTRIM(m.USRUSR))) <> 'ADMIN'
        AND m.USRVND IS NOT NULL
        AND LTRIM(RTRIM(CAST(m.USRVND AS VARCHAR(50)))) <> ''
        AND s.SalesmanID IS NULL
    """

    rows = db.execute(query)

    return [
        {
            "type": "INVALID_MSS_MAPPING",
            "mss_user_code": normalize_text(row[0]),
            "mss_user_name": normalize_text(row[1]),
            "mapped_code": normalize_text(row[2]),
            "message": (
                f"{normalize_text(row[1])} referencia o vendedor ERP "
                f"{normalize_text(row[2])}, mas esse vendedor nao existe no Sage 50."
            ),
        }
        for row in rows
    ]


def get_mss_users_without_erp_salesman(db: DatabaseExecutor) -> list[ValidationIssue]:
    """Identifica utilizadores MSS sem codigo de vendedor ERP associado."""

    config = load_config()
    mss_db = quote_sql_identifier(config["databases"]["mss"])

    query = f"""
    SELECT
        CAST(USRUSR AS VARCHAR(50)) AS CodigoUtilizador,
        USRNOM
    FROM {mss_db}.dbo.MSUSR
    WHERE UPPER(LTRIM(RTRIM(USRUSR))) <> 'ADMIN'
        AND (
            USRVND IS NULL
            OR LTRIM(RTRIM(CAST(USRVND AS VARCHAR(50)))) = ''
            )
    """

    rows = db.execute(query)

    return [
        {
            "type": "MSS_USER_WITHOUT_ERP_SALESMAN",
            "mss_user_code": normalize_text(row[0]),
            "mss_user_name": normalize_text(row[1]),
            "message": (
                f"{normalize_text(row[1])} existe no MSS, "
                "mas nao tem codigo de vendedor ERP associado."
            ),
        }
        for row in rows
    ]


def validate_salesmen(db: DatabaseExecutor) -> SalesmenValidationResult:
    """
    Executa a validacao completa de vendedores.

    Esta funcao foi preparada para ser chamada diretamente por um botao da interface.
    Ela devolve dados estruturados, nao texto solto nem query bruta.
    """

    issues: list[ValidationIssue] = []
    issues.extend(get_unmapped_salesmen(db))
    issues.extend(get_invalid_mss_mappings(db))
    issues.extend(get_mss_users_without_erp_salesman(db))

    return {
        "success": len(issues) == 0,
        "total_issues": len(issues),
        "issues": issues,
    }


def normalize_text(value: Any) -> str:
    """Converte valores vindos do SQL para texto limpo."""

    if value is None:
        return ""

    return str(value).strip()


def quote_sql_identifier(identifier: str) -> str:
    """Protege nomes de bases/tabelas antes de os usar numa query SQL."""

    return f"[{identifier.replace(']', ']]')}]"
