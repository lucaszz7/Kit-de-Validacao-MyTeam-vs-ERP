# TODO

## Concluído

### Projeto base

- [x] Definir tema e linguagem (Python)
- [x] Estrutura de pastas (`src/core`, `src/modulos/sage50`, `src/ui`)
- [x] `config/config.example.json`
- [x] `requirements.txt` (PySide6, pyodbc, requests)
- [x] Empacotamento `.exe` com PyInstaller (`--onefile --windowed`)

### Configuração e setup

- [x] Diálogo de configuração SQL (testa ligação antes de aceitar)
- [x] Verificação do ODBC Driver 17 for SQL Server ao arrancar (com proposta de download)
- [x] `save_config()` / `load_config()` com password em texto plano
- [x] Config (`config.json`) guardada ao lado do `.exe` quando congelado
- [x] Botão "Reconfigurar ligação SQL" no painel Definições

### Core — ambiente e infraestrutura

- [x] Ligação SQL Server (`database.py`, `config_loader.py`)
- [x] Verificação serviço MyTeam (Windows)
- [x] Verificação WebAPI (serviço, status, API Keys)
- [x] Porta do otimizador
- [x] World Geometries
- [x] Google Maps API, moeda e histórico de sincronização (MSS)

### Módulo Sage 50

- [x] Query e validação de **documentos de encomenda** (`queries_encomendas.py`)
- [x] Query e validação de **vendedores** (`queries_vendedores.py`)
- [x] Mapeamento MSS → ERP com deteção de divergências

### Interface gráfica (PySide6)

- [x] Janela principal com sidebar e 6 painéis (Ambiente, Encomendas, Vendedores, Vendas, Exportação, Definições)
- [x] Painel de ambiente (10 cartões + validação completa)
- [x] Painel de documentos de encomendas (layout com 5 secções + resumo numérico)
- [x] Painel de vendedores (tabela MSS + log de divergências)
- [x] Validações em thread separada (UI responsiva)
- [x] Estados OK / Warning / Erro nos cartões
- [x] Exportação Excel (.xlsx) por painel
- [x] Documentação interna do `main_window.py` (16 fases)

---

## Em curso / Por fazer

### Configuração local (cada instalador)

- [ ] Criar `config/config.json` a partir do exemplo
- [ ] Confirmar driver ODBC SQL Server no Windows
- [ ] Validar acesso às bases MSS e Sage 50 do cliente

### Módulo Sage 50 — vendas

- [ ] Criar `queries_vendas.py`
- [ ] Implementar validação no painel **Vendas**
- [ ] Testar com dados reais ou base de teste

### Módulo Sage 50 — indicadores futuros

- [ ] Query de faturação do período
- [ ] Query de encomendas em aberto (indicadores dashboard)
- [ ] Checklist Sage 50 completo em documentação

### Aplicação — melhorias

- [ ] Seleção de ERP (atualmente só Sage 50)
- [ ] Seleção de período para indicadores numéricos

### Documentação

- [ ] Manual de utilizador
- [ ] Artigo KB interno
- [ ] Processo para adicionar novo ERP
- [ ] Limitações conhecidas

### Roadmap

- [ ] Estrutura Sage 100
- [ ] Estrutura Primavera
- [ ] Estrutura PHC
