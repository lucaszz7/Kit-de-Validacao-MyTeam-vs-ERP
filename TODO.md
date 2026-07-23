# TODO

## Concluído

### Projeto base

- [x] Definir tema e linguagem (Python)
- [x] Estrutura de pastas (`src/core`, `src/modulos/sage50`, `src/ui`)
- [x] `requirements.txt` (PySide6, pyodbc, requests, keyring, cryptography, openpyxl, pyinstaller)
- [x] Empacotamento `.exe` com PyInstaller (`--onefile --windowed`)

### Configuração e setup

- [x] Diálogo de configuração SQL (testa ligação antes de aceitar)
- [x] Verificação do ODBC Driver 17 for SQL Server ao arrancar (com proposta de download)
- [x] Credenciais no Windows Credential Manager (keyring + Fernet AES-128), nunca em ficheiro
- [x] Botão "Reconfigurar ligação SQL" no painel Definições
- [x] Caminhos MSSBO.INI e appsettings.json configuráveis no diálogo

### Core — ambiente e infraestrutura

- [x] Ligação SQL Server (`database.py`, `config_loader.py`)
- [x] Verificação serviço MyTeam (Windows)
- [x] Verificação WebAPI (serviço, status, API Keys)
- [x] Porta do otimizador (288)
- [x] World Geometries
- [x] Google Maps API, moeda, despesas V1/V2, entregas V1/V2 e histórico de sincronização

### Módulo Sage 50

- [x] Query e validação de **documentos de encomenda** (`queries_encomendas.py`)
- [x] Query e validação de **documentos de venda** (`queries_vendas.py`)
- [x] Query e validação de **vendedores** (`queries_vendedores.py`)
- [x] Mapeamento MSS → ERP com deteção de divergências
- [x] Deteção dinâmica de coluna vendedor (`DCCVND` → `DCCACL_38` → `DCCCVD`)
- [x] Notas de crédito (NC/NTCR) subtraídas nos totais de vendas
- [x] Filtro `TransStatus = 0` em queries SaleTransaction
- [x] Coluna CreateDate (não TransDate) em queries ERP

### Interface gráfica (PySide6)

- [x] Janela principal com sidebar e 6 painéis (Ambiente, Encomendas, Vendedores, Vendas, Exportação, Definições)
- [x] Painel de ambiente (MyTeam + MSS separados, 12 cartões)
- [x] Painel de documentos de encomendas (5 secções + grelha 11 colunas)
- [x] Painel de documentos de vendas (5 secções + grelha 11 colunas, desagregação mensal)
- [x] Painel de vendedores (tabela MSS + log de divergências)
- [x] Grelha unificada com filtros de mês/vendedor/documento
- [x] Scroll vertical e horizontal na grelha (altura fixa 300px)
- [x] Validações em thread separada (UI responsiva)
- [x] Estados OK / Warning / Erro nos cartões
- [x] Exportação Excel (.xlsx) por painel
- [x] Exportação ZIP com logs coloridos
- [x] Painel de logs compacto (fonte 14px, sem subtítulo)
- [x] FixedStackedWidget para troca dinâmica de painéis
- [x] HorizontalResizeScrollArea para scroll da janela

---

## Por fazer

### Aplicação — melhorias

- [ ] Seleção de ERP (atualmente só Sage 50)
- [ ] Seleção de período para indicadores numéricos

### Documentação

- [ ] Manual de utilizador
- [ ] Artigo KB interno

### Roadmap

- [ ] Estrutura Sage 100
- [ ] Estrutura Primavera
- [ ] Estrutura PHC
