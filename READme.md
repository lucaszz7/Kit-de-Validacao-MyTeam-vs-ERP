# Kit de Validação MyTeam vs ERP

Ferramenta de diagnóstico para comparar valores apresentados nos dashboards do MyTeam com os valores existentes no ERP do cliente.

O objetivo é ajudar a equipa técnica a encontrar divergências causadas por documentos, vendedores, séries, datas de sincronização ou mapeamentos incorretos.

## Decisão Técnica

Este projeto vai ser desenvolvido em **Python**.

Entre C++ e Python, Python é a opção mais indicada para esta fase porque:

- permite criar a primeira versão mais rapidamente;
- liga facilmente a SQL Server com `pyodbc`;
- facilita exportação para CSV e Excel;
- é mais simples de manter e explicar no relatório de estágio;
- pode ser empacotado como `.exe` para Windows com PyInstaller.

C++ só faria sentido se o projeto exigisse desempenho muito alto, controlo nativo de baixo nível ou integração pesada com bibliotecas C/C++. Para esta ferramenta, o gargalo será quase sempre a base de dados, não a linguagem.

## Funcionalidades Previstas

- Seleção do ERP.
- Seleção do indicador a validar.
- Comparação entre valores MyTeam e valores ERP.
- Identificação de diferenças.
- Queries de diagnóstico por ERP.
- Checklists de configuração inicial.
- Exportação de resultados.
- Documentação modular para adicionar novos ERPs.

## Módulo Inicial

A versão 1.0 foca-se no ERP **Sage 50**.

Indicadores iniciais:

- Faturação do período.
- Encomendas em aberto.
- Vendas por vendedor.

## Estrutura

```text
.
├── config/
├── docs/
├── modulos/
│   ├── sage50/
│   ├── sage100/
│   ├── primavera/
│   └── phc/
├── src/
│   └── kit_validacao/
├── READme.md
├── TODO.md
└── requirements.txt
```

## Como Começar

1. Criar e ativar um ambiente virtual.
2. Instalar as dependências.
3. Copiar `config/config.example.json` para `config/config.json`.
4. Ajustar as ligações às bases de dados.
5. Executar a aplicação.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.kit_validacao.main
```

## Entregáveis

- Ferramenta de comparação v1.
- Módulo Sage 50 com queries e checklist.
- Documentação modular.
- Artigo KB interno.
- Roadmap para Sage 100, Primavera e PHC.
