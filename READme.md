# Kit de Validação MyTeam vs ERP

Ferramenta de diagnóstico para validar a integração entre **MyTeam**, **BackOffice (MSS)** e **Sage 50 (ERP)**.

O objetivo é ajudar a equipa técnica a encontrar divergências causadas por documentos mal configurados, vendedores não mapeados, serviços parados, configs MSS em falta ou datas de sincronização incorretas.

## Estado Atual (V1 — Interface Gráfica)

A aplicação corre em **Python + PySide6** com 4 painéis na barra lateral:

| Painel | O que valida | Estado |
|--------|----------------|--------|
| **Verificações de ambiente** | MyTeam, WebAPI, SQL Server, World Geometries, Google Maps, moeda, histórico | Implementado |
| **Documentos de encomendas** | BO vs ERP vs MyTeam vs tabela de vendas | Implementado |
| **Vendas** | Comparação de vendas MyTeam vs ERP | Por implementar |
| **Vendedores** | Mapeamento MSS ↔ Sage 50 | Implementado |

Cada painel permite validar tudo de uma vez (botão verde) ou clicar num cartão individual. Os resultados podem ser exportados para **Excel** (.xlsx).

## Decisão Técnica

Este projeto é desenvolvido em **Python** porque:

- permite criar a primeira versão mais rapidamente;
- liga facilmente a SQL Server com `pyodbc`;
- facilita exportação para Excel;
- é mais simples de manter e explicar no relatório de estágio;
- pode ser empacotado como `.exe` para Windows com PyInstaller.

## Funcionalidades Implementadas

### Ambiente

- Estado do serviço Windows MyTeam (`MSSBO.INI`)
- Serviço WebAPI, endpoint de status e consistência de API Keys
- Porta do otimizador (288)
- Ligação SQL Server
- Existência da base World Geometries
- Configuração Google Maps API no MSS
- Símbolo de moeda por terminal
- Data do documento histórico mais antigo sincronizado

### Documentos de encomendas

Compara 4 origens de dados e lista divergências:

1. Documentos configurados no BackOffice (`DOCS_ENC`)
2. Documentos de encomenda no ERP (natureza = Encomenda)
3. Tipos já integrados no MyTeam (quantidade + total líquido)
4. Tipos existentes na tabela de vendas do ERP

### Vendedores

- Tabela de mapeamento: utilizadores **MSS** com respetivo código ERP
- Validação automática: vendedores ERP sem MSS, MSS sem ERP, mapeamentos inválidos
- Utilizador `ADMIN` ignorado na validação

### Vendas

Painel reservado — queries ainda por implementar.

## Estrutura do Projeto

```text
.
├── config/
│   └── config.example.json      # Modelo de ligação SQL
├── src/
│   ├── main.py                  # Ponto de entrada da aplicação
│   ├── core/
│   │   ├── config_loader.py     # Leitura do config.json
│   │   ├── database.py          # Ligação ODBC ao SQL Server
│   │   ├── verifications.py     # Verificações de ambiente e MSS
│   │   ├── webapi_checks.py     # WebAPI e API Keys
│   │   └── port_checks.py       # Porta do otimizador
│   ├── modulos/
│   │   └── sage50/
│   │       ├── queries_encomendas.py
│   │       └── queries_vendedores.py
│   └── ui/
│       └── main_window.py       # Interface gráfica (4 painéis)
├── READme.md
├── TODO.md
└── requirements.txt
```

## Requisitos

- Windows 10/11
- Python 3.10+
- Driver ODBC para SQL Server
- Acesso às bases MSS e Sage 50 do cliente
- Ficheiro `C:\MIS\MSSV5\Backoffice\MSSBO.INI` (para verificações de serviço)

## Como Começar

1. Criar e ativar um ambiente virtual.
2. Instalar dependências.
3. Copiar `config/config.example.json` para `config/config.json`.
4. Ajustar servidor, utilizador, password e nomes das bases.
5. Executar a aplicação a partir da pasta `src`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config\config.example.json config\config.json
cd src
python main.py
```

## Arquitetura da Interface

O ficheiro `src/ui/main_window.py` está organizado em fases:

1. Widgets reutilizáveis (`TaskWorker`, cartões de estado)
2. Layout (sidebar + 4 painéis)
3. Disparo de validações (`run_*`)
4. Execução assíncrona em thread (UI não congela)
5. Coleta de dados (`collect_*` → `core/` e `modulos/sage50/`)
6. Renderização dos resultados na tela
7. Exportação Excel

A lógica de negócio **não** fica na UI — apenas consome os dicionários devolvidos pelos módulos de validação.

## Roadmap

- [ ] Implementar validação de **vendas**
- [ ] Empacotamento `.exe` com PyInstaller
- [ ] Suporte a Sage 100, Primavera e PHC
- [ ] Manual de utilizador e artigo KB interno

## Entregáveis Previstos

- Ferramenta de validação v1 com interface gráfica
- Módulo Sage 50 com queries de encomendas e vendedores
- Checklist de ambiente automatizado
- Documentação modular para novos ERPs
