# Kit de Validação MyTeam vs ERP

Ferramenta de diagnóstico para validar a integração entre **MyTeam**, **BackOffice (MSS)** e **Sage 50 (ERP)**.

O objetivo é ajudar a equipa técnica a encontrar divergências causadas por documentos mal configurados, vendedores não mapeados, serviços parados, configs MSS em falta ou datas de sincronização incorretas.

## Estado Atual

A aplicação corre em **Python + PySide6** com 6 painéis na barra lateral:

| Painel | O que valida | Estado |
|--------|--------------|--------|
| **Ambiente** | MyTeam, WebAPI, SQL Server, World Geometries, Google Maps, moeda, despesas, entregas, histórico | Implementado |
| **Encomendas** | BO vs ERP vs MyTeam vs tabela de vendas | Implementado |
| **Vendas** | Vendas MyTeam vs ERP, desagregação mensal por vendedor/documento | Implementado |
| **Vendedores** | Mapeamento MSS ↔ Sage 50 | Implementado |
| **Exportação** | Exportar todos os painéis para Excel | Implementado |
| **Definições** | Reconfigurar ligação SQL | Implementado |

Cada painel permite validar tudo de uma vez (botão verde) ou clicar num cartão individual. Os resultados podem ser exportados para **Excel** (.xlsx).

## Decisão Técnica

Este projeto é desenvolvido em **Python** porque:

- permite criar a primeira versão mais rapidamente;
- liga facilmente a SQL Server com `pyodbc`;
- facilita exportação para Excel;
- pode ser empacotado como `.exe` para Windows com PyInstaller.

## Funcionalidades Implementadas

### Setup e configuração

- **Verificação de ODBC Driver 17 for SQL Server** ao arrancar — se não estiver instalado, mostra aviso com link de download
- **Formulário de configuração SQL** — aparece sempre ao abrir a aplicação, testa `SELECT 1` nas duas bases antes de aceitar
- **Credenciais no Windows Credential Manager** — password encriptada com Fernet (AES-128), nunca em ficheiro
- **Botão "Reconfigurar ligação SQL"** no painel Definições para reabrir o formulário de login sem fechar a app
- **Caminhos configuráveis** do MSSBO.INI e appsettings.json no diálogo de ligação

### Ambiente

- Estado do serviço Windows MyTeam (`MSSBO.INI`)
- Serviço WebAPI, endpoint de status e consistência de API Keys
- Porta do otimizador (288)
- Ligação SQL Server
- Existência da base World Geometries
- Configuração Google Maps API no MSS
- Símbolo de moeda por terminal
- Versão de Despesas (V1/V2) e Entregas (V1/V2)
- Data do documento histórico mais antigo sincronizado

### Documentos de encomendas

Compara 4 origens de dados e lista divergências:

1. Documentos configurados no BackOffice (`DOCS_ENC`)
2. Documentos de encomenda no ERP (`Documents` filtrado por tipo)
3. Tipos já integrados no MyTeam (quantidade + total líquido)
4. Tipos existentes na tabela de vendas do ERP

Grelha 11 colunas com desagregação mensal (ano anterior vs atual), filtros por mês/vendedor/documento.

### Documentos de vendas

Compara 4 origens de dados e lista divergências:

1. Documentos configurados no BackOffice (`DOCS_VEN`)
2. Documentos de venda no ERP (`TransactionNatureID IN 1001-1005`)
3. Tipos já integrados no MyTeam (quantidade + total líquido)
4. Tipos existentes na tabela de vendas do ERP

Grelha 11 colunas com desagregação mensal (ano anterior vs atual), filtros por mês/vendedor/documento. Notas de crédito (NC/NTCR) subtraídas nos totais.

### Vendedores

- Tabela de mapeamento: utilizadores **MSS** com respetivo código ERP
- Validação automática: vendedores ERP sem MSS, MSS sem ERP, mapeamentos inválidos, utilizadores sem código vendedor ERP
- Utilizador `ADMIN` ignorado na validação
- Deteção dinâmica da coluna vendedor (`DCCVND` → `DCCACL_38` → `DCCCVD`)

## Estrutura do Projeto

```text
.
├── dist/
│   └── KitValidacao.exe           # Executável standalone
├── src/
│   ├── main.py                    # Ponto de entrada (check ODBC → ConfigDialog → MainWindow)
│   ├── core/
│   │   ├── config_loader.py       # Leitura/escrita de config (via keyring)
│   │   ├── credentials.py         # Credenciais no Windows Credential Manager
│   │   ├── database.py            # Ligação ODBC ao SQL Server
│   │   ├── port_checks.py         # Porta do otimizador
│   │   ├── verifications.py       # Verificações de ambiente e MSS
│   │   └── webapi_checks.py       # WebAPI e API Keys
│   ├── modulos/
│   │   └── sage50/
│   │       ├── queries_base.py    # Utilitários partilhados
│   │       ├── queries_encomendas.py
│   │       ├── queries_vendas.py
│   │       └── queries_vendedores.py
│   └── ui/
│       ├── config_dialog.py       # Diálogo de configuração SQL
│       └── main_window.py         # Interface gráfica (6 painéis)
├── READme.md
├── TODO.md
└── requirements.txt
```

## Requisitos

- Windows 10/11
- ODBC Driver 17 for SQL Server ([download oficial](https://go.microsoft.com/fwlink/?linkid=2216184))
- Acesso às bases MSS e Sage 50 do cliente
- Ficheiro `C:\MIS\MSSV5\Backoffice\MSSBO.INI` (para verificações de serviço)

## Como Correr (modo desenvolvimento)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd src
python main.py
```

## Como Distribuir

O executável standalone é gerado com PyInstaller:

```powershell
& ".\.venv\Scripts\pyinstaller.exe" KitValidacao.spec --noconfirm
```

O `.exe` final está em `dist/KitValidacao.exe`. Basta enviar esse ficheiro — o utilizador só precisa de ter o ODBC Driver 17 instalado.

## Arquitetura da Interface

O ficheiro `src/ui/main_window.py` está organizado em fases:

1. Widgets reutilizáveis (`TaskWorker`, cartões de estado, `FixedStackedWidget`, `HorizontalResizeScrollArea`)
2. Layout (sidebar + 6 painéis)
3. Disparo de validações (`run_*`)
4. Execução assíncrona em thread (UI não congela)
5. Coleta de dados (`collect_*` → `core/` e `modulos/sage50/`)
6. Renderização dos resultados na tela
7. Exportação Excel / ZIP

A lógica de negócio **não** fica na UI — apenas consome os dicionários devolvidos pelos módulos de validação.

## Fluxo de Arranque

```
main.py
  │
  ├─ _check_odbc_driver()  → se não instalado, avisa e sugere download
  │
  ├─ ConfigDialog           → sempre ao abrir, testa SELECT 1 em ambas as bases
  │     ├─ [Aceitar]        → guarda config (keyring), cria MainWindow
  │     └─ [Cancelar / X]   → sys.exit(0)
  │
  └─ MainWindow(config)     → interface principal
```

## Roadmap

- [ ] Suporte a Sage 100, Primavera e PHC
- [ ] Manual de utilizador e artigo KB interno
