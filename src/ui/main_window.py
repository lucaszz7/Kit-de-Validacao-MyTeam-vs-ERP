"""
Interface gráfica do Kit de Validação MyTeam vs ERP.

Este ficheiro concentra TODA a camada visual da aplicação (PySide6/Qt).
A lógica de negócio fica nos módulos core/ e modulos/sage50/ — aqui só
se monta a janela, se disparam validações e se mostram os resultados.

MAPA DO FICHEIRO (ordem de leitura recomendada)
────────────────────────────────────────────────
  FASE 1  → Imports (Qt + funções de validação externas)
  FASE 2  → Widgets reutilizáveis (cartões, contadores, worker)
  FASE 3  → Arranque da janela principal (MainWindow.__init__)
  FASE 4  → Estrutura visual: sidebar + área de conteúdo
  FASE 5  → Os 4 painéis: ambiente | encomendas | vendas | vendedores
  FASE 6  → Componentes de resultados (tabela genérica + layout encomendas)
  FASE 7  → Navegação entre painéis e exportação Excel
  FASE 8  → Ações do utilizador (clique em cartão / botão validar)
  FASE 9  → Motor assíncrono (validações em thread separada)
  FASE 10 → Coleta de dados (chama core/ e modulos/sage50/)
  FASE 11 → Infraestrutura (config.json + ligação SQL)
  FASE 12 → Renderização (preenche tabelas, listas e logs na UI)
  FASE 13 → Formatação de valores para exibição
  FASE 14 → Gestão dos widgets de resultado (limpar, inserir linhas)
  FASE 15 → Geração de ficheiros Excel
  FASE 16 → Estilos visuais (folha QSS)

FLUXO TÍPICO DE UMA VALIDAÇÃO
──────────────────────────────
  1. Utilizador clica num cartão ou botão  →  run_*()
  2. run_task() lança TaskWorker numa thread
  3. collect_*() executa queries/verificações (fora da UI)
  4. render_*_results() atualiza cartões, tabelas e logs
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.config_loader import load_config
from core.database import Database
from core.verifications import (
    get_currency_symbol_info,
    get_google_maps_api_info,
    get_historical_sync_start_info,
    get_myteam_service_info,
    get_optimizer_port_info,
    get_webapi_apikey_info,
    get_webapi_service_info,
    get_webapi_status_info,
    get_world_geometries_info,
)
from modulos.sage50.queries_encomendas import validate_order_documents
from modulos.sage50.queries_vendedores import get_salesmen_mapping, validate_salesmen


# =============================================================================
# FASE 1 — IMPORTS E DEPENDÊNCIAS EXTERNAS
# =============================================================================
# PySide6  → widgets da interface (janelas, botões, tabelas)
# core.*   → verificações de ambiente (serviços Windows, WebAPI, SQL, MSS)
# modulos  → validações específicas Sage 50 (encomendas, vendedores)
#
# Regra: este ficheiro NÃO contém queries SQL nem regras de negócio.
#        Apenas consome os dicts devolvidos pelos módulos acima.
# =============================================================================


# =============================================================================
# FASE 2 — WIDGETS REUTILIZÁVEIS
# =============================================================================
# Pequenos componentes visuais partilhados por todos os painéis.
# Criados uma vez e reutilizados em build_cards_group / build_orders_*.
# =============================================================================


class TaskWorker(QObject):
    """
    Worker que corre numa QThread.

    Porquê existe: consultas SQL e chamadas HTTP podem demorar segundos.
    Se correrem na thread principal, a janela congela. Este worker executa
    a função collect_*() em background e devolve o resultado via Signal.
    """
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Callable[[], Any]):
        super().__init__()
        self.task = task

    def run(self):
        try:
            self.finished.emit(self.task())
        except Exception as error:
            self.failed.emit(str(error))


class StatusCard(QFrame):
    """
    Cartão clicável de cada verificação (ex.: MyTeam, SQL Server, Vendedores).

    Mostra: título | estado (OK/Warning/Erro) | detalhe curto.
    Ao clicar, dispara a validação individual daquele item.
    """
    clicked = Signal()

    def __init__(self, title: str, detail: str = "Clique para validar."):
        super().__init__()
        self.setObjectName("statusCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")

        self.status_label = QLabel("Pendente")
        self.status_label.setObjectName("statusPill")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("cardDetail")
        self.detail_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(self.title_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.detail_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_loading(self):
        self.set_status("A validar...", "Aguarde enquanto a verificação está em curso.")

    def set_status(self, status: str, detail: str = ""):
        # Traduz texto do estado para cor visual (verde / amarelo / vermelho)
        normalized = str(status).lower()

        if normalized in {"ok", "running", "true", "online"}:
            state = "ok"
        elif normalized in {"warning", "missing", "different", "closed", "no data", "por fazer"}:
            state = "warning"
        elif normalized in {"error", "stopped", "false", "offline"}:
            state = "error"
        elif normalized == "a validar...":
            state = "loading"
        else:
            state = "neutral"

        self.status_label.setProperty("state", state)
        self.status_label.setText(str(status))
        self.detail_label.setText(detail or "Sem detalhes adicionais.")
        self.style().unpolish(self.status_label)
        self.style().polish(self.status_label)


class CountStatCard(QFrame):
    """
    Cartão numérico do painel de encomendas (BackOffice, ERP, Integrados, Divergências).

    Usado apenas em build_orders_results_section — resumo rápido no topo.
    """
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("countStatCard")

        self.title_label = QLabel(title)
        self.title_label.setObjectName("countStatTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.value_label = QLabel("0")
        self.value_label.setObjectName("countStatValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: int | str):
        self.value_label.setText(str(value))


class MainWindow(QMainWindow):
    """
    Janela principal da aplicação.

    Responsabilidades:
      - Montar os 4 painéis de validação
      - Ligar botões/cartões às funções collect_* do backend
      - Mostrar resultados em tabelas, listas e logs
      - Exportar relatórios para Excel
    """

    # =========================================================================
    # FASE 3 — ARRANQUE DA APLICAÇÃO
    # =========================================================================
    # Cria variáveis de estado, monta a UI e abre o painel de ambiente.
    # =========================================================================

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kit de Validação MyTeam vs ERP")
        self.resize(1180, 760)

        # --- Conexões SQL (criadas só na 1.ª validação que precisar delas) ---
        self.config: dict[str, Any] | None = None
        self.db_sage: Database | None = None   # base Sage 50 (ERP)
        self.db_mss: Database | None = None    # base MSS (BackOffice / MyTeam)

        # --- Controlo da thread de validação ---
        self.thread: QThread | None = None
        self.worker: TaskWorker | None = None
        self.current_success_callback: Callable[[Any], None] | None = None
        self.current_page_key = "environment"  # painel visível no momento
        self.loading_card_keys: list[str] = [] # cartões em estado "A validar..."

        # --- Registos criados em build_ui (acesso rápido depois) ---
        self.cards: dict[str, StatusCard] = {}              # cartões por chave
        self.result_widgets: dict[str, dict[str, Any]] = {} # tabelas/logs por painel
        self.nav_buttons: dict[str, QPushButton] = {}       # botões da sidebar
        self.validation_controls: list[QWidget] = []        # tudo que bloqueia durante validação

        self.build_ui()
        self.apply_styles()
        self.show_page("environment")

    # =========================================================================
    # FASE 4 — ESTRUTURA VISUAL (LAYOUT BASE)
    # =========================================================================
    # Monta sidebar (menu lateral) + área de conteúdo com scroll.
    # A sidebar tem os 4 botões de navegação e o botão Exportar Excel.
    # =========================================================================

    def build_ui(self):
        """Raiz da interface: sidebar à esquerda, conteúdo à direita."""
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self.build_sidebar())
        root_layout.addWidget(self.build_content(), 1)
        self.setCentralWidget(root)

    def build_sidebar(self):
        """Menu lateral com navegação entre os 4 painéis e exportação."""
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(260)

        title = QLabel("MyTeam vs ERP")
        title.setObjectName("appTitle")

        subtitle = QLabel("Interface V1")
        subtitle.setObjectName("appSubtitle")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(14)

        # Botões de navegação — cada um troca o painel visível (show_page)
        self.nav_buttons["environment"] = self.create_nav_button(
            "Verificações de ambiente",
            lambda: self.show_page("environment"),
        )
        self.nav_buttons["orders"] = self.create_nav_button(
            "Documentos de encomendas",
            lambda: self.show_page("orders"),
        )
        self.nav_buttons["sales"] = self.create_nav_button(
            "Vendas",
            lambda: self.show_page("sales"),
        )
        self.nav_buttons["salesmen"] = self.create_nav_button(
            "Vendedores",
            lambda: self.show_page("salesmen"),
        )

        layout.addWidget(self.nav_buttons["environment"])
        layout.addWidget(self.nav_buttons["orders"])
        layout.addWidget(self.nav_buttons["sales"])
        layout.addWidget(self.nav_buttons["salesmen"])

        layout.addStretch()

        # Exporta os resultados do painel atualmente aberto
        self.export_button = self.create_validation_button(
            "Exportar para Excel",
            self.export_current_results,
        )
        self.export_button.setProperty("export", True)
        layout.addWidget(self.export_button)

        hint = QLabel("Cada caixa também executa a sua própria validação.")
        hint.setObjectName("sidebarHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        return sidebar

    def build_content(self):
        """Área principal: título + subtítulo + stack com os 4 painéis."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("contentScroll")

        content = QWidget()
        content.setObjectName("contentPage")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)

        self.page_title = QLabel()
        self.page_title.setObjectName("pageTitle")

        self.page_subtitle = QLabel()
        self.page_subtitle.setObjectName("pageSubtitle")
        self.page_subtitle.setWordWrap(True)

        # QStackedWidget: só um painel visível de cada vez (índice 0–3)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.build_environment_page())
        self.stack.addWidget(self.build_orders_page())
        self.stack.addWidget(self.build_sales_page())
        self.stack.addWidget(self.build_salesmen_page())

        layout.addWidget(self.page_title)
        layout.addWidget(self.page_subtitle)
        layout.addWidget(self.stack, 1)

        scroll.setWidget(content)
        return scroll

    # =========================================================================
    # FASE 5 — OS 4 PAINÉIS DE VALIDAÇÃO
    # =========================================================================
    # Cada painel segue o mesmo padrão:
    #   [ grelha de StatusCards ] + [ botão Validar tudo ] + [ secção resultados ]
    #
    #  Painel 0 — Ambiente    → 10 verificações (serviços, SQL, MSS)
    #  Painel 1 — Encomendas  → compara BO vs ERP vs MyTeam vs vendas
    #  Painel 2 — Vendas      → placeholder (queries ainda por implementar)
    #  Painel 3 — Vendedores  → mapeamento MSS ↔ Sage 50
    # =========================================================================

    def build_environment_page(self):
        """Painel 0: serviços Windows, WebAPI, SQL Server e configs MSS."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        cards = [
            # Serviços Windows e conectividade
            ("myteam", "MyTeam", self.run_myteam_check),
            ("webapi_service", "WebAPI", self.run_webapi_service_check),
            ("webapi_status", "Status WebAPI", self.run_webapi_status_check),
            ("apikeys", "API Keys da WebAPI", self.run_apikeys_check),
            ("optimizer", "Otimizador", self.run_optimizer_check),
            # SQL Server e bases de dados
            ("sql", "SQL Server", self.run_sql_check),
            ("world", "World Geometries", self.run_world_check),
            # Configurações guardadas na base MSS
            ("maps", "Google Maps API", self.run_maps_check),
            ("currency", "Moeda", self.run_currency_check),
            ("historical", "Histórico", self.run_historical_check),
        ]

        validate_button = self.create_validation_button(
            "Validar ambiente",
            self.run_environment_checks,
            primary=True,
        )
        validate_button.setMinimumHeight(82)
        layout.addWidget(
            self.build_cards_group(
                "Verificações de ambiente",
                cards,
                "environment",
                action_widget=validate_button,
            )
        )
        layout.addWidget(self.build_results_section("environment"), 1)
        return page

    def build_orders_page(self):
        """Painel 1: documentos de encomenda (layout especial com 5 secções)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        cards = [
            ("orders", "Documentos de encomendas", self.run_order_checks),
        ]

        layout.addWidget(self.build_cards_group("Documentos de encomendas", cards, "orders"))

        validate_button = self.create_validation_button(
            "Validar documentos de encomendas",
            self.run_order_checks,
            primary=True,
        )
        layout.addWidget(validate_button)
        layout.addWidget(self.build_orders_results_section(), 1)
        return page

    def build_sales_page(self):
        """Painel 2: vendas (ainda por implementar — mostra placeholder)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        cards = [
            ("sales", "Vendas", self.run_sales_checks),
        ]

        layout.addWidget(self.build_cards_group("Vendas", cards, "sales"))

        validate_button = self.create_validation_button(
            "Validar vendas",
            self.run_sales_checks,
            primary=True,
        )
        layout.addWidget(validate_button)
        layout.addWidget(self.build_results_section("sales"), 1)
        return page

    def build_salesmen_page(self):
        """Painel 3: mapeamento de vendedores MSS → ERP."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        cards = [
            ("salesmen", "Vendedores", self.run_salesmen_checks),
        ]

        layout.addWidget(self.build_cards_group("Vendedores", cards, "salesmen"))

        validate_button = self.create_validation_button(
            "Validar vendedores",
            self.run_salesmen_checks,
            primary=True,
        )
        layout.addWidget(validate_button)
        layout.addWidget(self.build_results_section("salesmen"), 1)
        return page

    # =========================================================================
    # FASE 6 — COMPONENTES DE RESULTADOS
    # =========================================================================
    # Dois layouts possíveis:
    #   build_results_section      → tabela + log (ambiente, vendas, vendedores)
    #   build_orders_results_section → 5 secções + resumo numérico (encomendas)
    # =========================================================================

    def build_cards_group(
        self,
        title: str,
        cards: list[tuple[str, str, Callable[[], None]]],
        page_key: str,
        action_widget: QWidget | None = None,
    ):
        """Grelha de StatusCards. Ambiente usa 4 colunas; restantes usam 2."""
        group = QGroupBox(title)
        grid = QGridLayout(group)
        grid.setContentsMargins(14, 18, 14, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        columns = 4 if page_key == "environment" else 2

        for index, (key, card_title, callback) in enumerate(cards):
            card = StatusCard(card_title)
            card.clicked.connect(callback)
            self.cards[key] = card
            self.validation_controls.append(card)  # desativados durante validação
            grid.addWidget(card, index // columns, index % columns)

        if action_widget is not None:
            action_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            row = len(cards) // columns
            column = len(cards) % columns
            column_span = max(1, columns - column)
            grid.addWidget(action_widget, row, column, 1, column_span)

        return group

    def build_results_section(self, page_key: str):
        """
        Layout padrão de resultados: resumo + barra progresso + tabela + log.

        Usado nos painéis: environment, sales, salesmen.
        """
        group = QGroupBox("Resultados da validação")
        group.setObjectName("resultsGroup")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(10)

        summary = QLabel("Clique numa caixa acima ou no botão de validação.")
        summary.setObjectName("summaryLabel")
        summary.setWordWrap(True)

        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.hide()

        table_label = QLabel("Resumo técnico")
        table_label.setObjectName("sectionLabel")

        table_headers = self.get_table_headers(page_key)
        table = QTableWidget(0, len(table_headers))
        table.setHorizontalHeaderLabels(table_headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        
        # Sem scroll interno — a página inteira faz scroll via QScrollArea.
        
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setShowGrid(True)
        table.setGridStyle(Qt.PenStyle.SolidLine)
        table.setWordWrap(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        for column in range(len(table_headers)):
            resize_mode = QHeaderView.ResizeMode.Stretch if column == len(table_headers) - 1 else QHeaderView.ResizeMode.ResizeToContents
            table.horizontalHeader().setSectionResizeMode(column, resize_mode)
        table.setFixedHeight(96)

        log_label = QLabel("Log de execução")
        log_label.setObjectName("sectionLabel")

        log_box = QTextEdit()
        log_box.setReadOnly(True)
        log_box.setMinimumHeight(110)
        log_box.setPlaceholderText("As mensagens da validação aparecem aqui.")

        layout.addWidget(summary)
        layout.addWidget(progress)
        layout.addWidget(table_label)
        layout.addWidget(table)
        layout.addWidget(log_label)
        layout.addWidget(log_box)

        self.result_widgets[page_key] = {
            "summary": summary,
            "progress": progress,
            "table": table,
            "log": log_box,
        }
        return group

    def build_orders_results_section(self):
        """
        Layout exclusivo do painel de encomendas.

        Estrutura apresentada ao utilizador:
          [ Resumo: BO | ERP | Integrados | Divergências ]
          [ 1. Docs configurados no BackOffice ]
          [ 2. Docs de encomenda no ERP ]
          [ 3. Docs integrados no MyTeam (tabela) ]
          [ 4. Docs na tabela de vendas ]
          [ 5. Divergências encontradas ]
        """
        group = QGroupBox("Resultados da validação")
        group.setObjectName("resultsGroup")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(12)

        summary = QLabel("Clique na caixa acima ou no botão de validação.")
        summary.setObjectName("summaryLabel")
        summary.setWordWrap(True)

        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.hide()

        # Resumo numérico no topo
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        stat_bo = CountStatCard("BackOffice")
        stat_erp = CountStatCard("ERP")
        stat_integrated = CountStatCard("Integrados")
        stat_issues = CountStatCard("Divergências")
        stats_row.addWidget(stat_bo)
        stats_row.addWidget(stat_erp)
        stats_row.addWidget(stat_integrated)
        stats_row.addWidget(stat_issues)

        # Secções 1 a 5 do relatório de encomendas
        section_bo, bo_list = self.build_doc_list_section(
            "1. Documentos configurados no BackOffice para os Dashboards"
        )
        section_erp, erp_list = self.build_doc_list_section(
            "2. Documentos de encomenda existentes no ERP"
        )

        section_integrated = QGroupBox("3. Tipos de documentos já integrados no MyTeam")
        integrated_layout = QVBoxLayout(section_integrated)
        integrated_table = QTableWidget(0, 3)
        integrated_table.setHorizontalHeaderLabels(["Documento", "Quantidade", "Total Líquido"])
        integrated_table.setAlternatingRowColors(True)
        integrated_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        integrated_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        integrated_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        integrated_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        integrated_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        integrated_table.verticalHeader().setVisible(False)
        integrated_table.verticalHeader().setDefaultSectionSize(34)
        integrated_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        integrated_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        integrated_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        integrated_table.setFixedHeight(96)
        integrated_layout.addWidget(integrated_table)

        section_sales, sales_list = self.build_doc_list_section(
            "4. Tipos de documentos existentes na tabela de vendas"
        )

        section_issues = QGroupBox("5. Divergências encontradas")
        issues_layout = QVBoxLayout(section_issues)
        issues_box = QTextEdit()
        issues_box.setReadOnly(True)
        issues_box.setObjectName("issuesBox")
        issues_box.setMinimumHeight(90)
        issues_box.setPlaceholderText("As divergências aparecem aqui após a validação.")
        issues_layout.addWidget(issues_box)

        layout.addWidget(summary)
        layout.addWidget(progress)
        layout.addLayout(stats_row)
        layout.addWidget(section_bo)
        layout.addWidget(section_erp)
        layout.addWidget(section_integrated)
        layout.addWidget(section_sales)
        layout.addWidget(section_issues)

        self.result_widgets["orders"] = {
            "summary": summary,
            "progress": progress,
            "stat_bo": stat_bo,
            "stat_erp": stat_erp,
            "stat_integrated": stat_integrated,
            "stat_issues": stat_issues,
            "bo_list": bo_list,
            "erp_list": erp_list,
            "integrated_table": integrated_table,
            "sales_list": sales_list,
            "issues": issues_box,
            "has_results": False,
        }
        return group

    def build_doc_list_section(self, title: str) -> tuple[QGroupBox, QTextEdit]:
        """Lista de documentos, um por linha."""
        group = QGroupBox(title)
        section_layout = QVBoxLayout(group)
        doc_list = QTextEdit()
        doc_list.setReadOnly(True)
        doc_list.setObjectName("docListBox")
        doc_list.setMinimumHeight(72)
        doc_list.setMaximumHeight(160)
        doc_list.setPlaceholderText("Sem dados.")
        section_layout.addWidget(doc_list)
        return group, doc_list

    def get_table_headers(self, page_key: str) -> list[str]:
        """Colunas da tabela de resultados conforme o painel."""
        if page_key == "salesmen":
            return ["Origem", "Código", "Nome", "Código ERP"]

        return ["Área", "Item", "Estado", "Detalhe"]

    # =========================================================================
    # FASE 7 — NAVEGAÇÃO E EXPORTAÇÃO
    # =========================================================================

    def create_nav_button(self, text: str, callback: Callable[[], None]):
        """Botão da sidebar para mudar de painel."""
        button = QPushButton(text)
        button.clicked.connect(callback)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def create_validation_button(self, text: str, callback: Callable[[], None], primary: bool = False):
        """Botão verde 'Validar ...' de cada painel."""
        button = QPushButton(text)
        button.clicked.connect(callback)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("primary", primary)
        self.validation_controls.append(button)
        return button

    def export_current_results(self):
        """Exporta o painel aberto. Encomendas gera relatório multi-secção."""
        if self.current_page_key == "orders":
            if not self.result_widgets["orders"].get("has_results"):
                QMessageBox.information(
                    self,
                    "Exportar Excel",
                    "Ainda não existem dados para exportar neste painel.",
                )
                return
        else:
            table = self.result_widgets[self.current_page_key]["table"]
            if table.rowCount() == 0:
                QMessageBox.information(
                    self,
                    "Exportar Excel",
                    "Ainda não existem dados para exportar neste painel.",
                )
                return

        default_name = f"validacao_{self.current_page_key}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar relatório Excel",
            default_name,
            "Excel (*.xlsx)",
        )

        if not file_path:
            return

        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"

        if self.current_page_key == "orders":
            self.export_orders_to_excel(file_path)
        else:
            self.export_table_to_excel(file_path)
        QMessageBox.information(
            self,
            "Exportar Excel",
            "Ficheiro Excel criado com sucesso.",
        )

    def show_page(self, page_key: str):
        """Troca o painel visível no QStackedWidget e atualiza título/subtítulo."""
        pages = {
            "environment": {
                "index": 0,
                "title": "Verificações de ambiente",
                "subtitle": "Valida serviços, WebAPI, SQL Server, World Geometries e configurações MSS.",
            },
            "orders": {
                "index": 1,
                "title": "Documentos de encomendas",
                "subtitle": "Valida a configuração de documentos de encomenda entre BackOffice, ERP, MyTeam e tabela de vendas.",
            },
            "sales": {
                "index": 2,
                "title": "Vendas",
                "subtitle": "Validação de vendas entre MyTeam e ERP.",
            },
            "salesmen": {
                "index": 3,
                "title": "Vendedores",
                "subtitle": "Valida o mapeamento entre vendedores do MSS e do Sage 50.",
            },
        }

        page = pages[page_key]
        self.current_page_key = page_key
        self.stack.setCurrentIndex(page["index"])
        self.page_title.setText(page["title"])
        self.page_subtitle.setText(page["subtitle"])

        for key, button in self.nav_buttons.items():
            button.setProperty("active", key == page_key)
            button.style().unpolish(button)
            button.style().polish(button)

    # =========================================================================
    # FASE 8 — AÇÕES DO UTILIZADOR (disparo das validações)
    # =========================================================================
    # Cada método run_* é ligado a um cartão ou botão.
    # Todos delegam em run_task() → collect_*() → render_*_results().
    # =========================================================================

    # --- Painel Ambiente: validação completa ou cartão individual ---

    def run_environment_checks(self):
        """Valida TODOS os 10 itens de ambiente de uma vez."""
        self.show_page("environment")
        self.run_task(
            "verificações de ambiente",
            self.collect_environment_checks,
            self.render_environment_results,
            "environment",
            [
                "myteam",
                "webapi_service",
                "webapi_status",
                "apikeys",
                "optimizer",
                "sql",
                "world",
                "maps",
                "currency",
                "historical",
            ],
        )

    def run_myteam_check(self):
        self.run_environment_card("MyTeam", "myteam", lambda: {"myteam": get_myteam_service_info()})

    def run_webapi_service_check(self):
        self.run_environment_card("WebAPI", "webapi_service", lambda: {"webapi_service": get_webapi_service_info()})

    def run_webapi_status_check(self):
        self.run_environment_card("Status WebAPI", "webapi_status", lambda: {"webapi_status": get_webapi_status_info()})

    def run_apikeys_check(self):
        self.run_environment_card("API Keys da WebAPI", "apikeys", lambda: {"apikeys": get_webapi_apikey_info()})

    def run_optimizer_check(self):
        self.run_environment_card("Otimizador", "optimizer", lambda: {"optimizer": get_optimizer_port_info()})

    def run_sql_check(self):
        self.run_environment_card("SQL Server", "sql", lambda: {"sql": self.collect_sql_only()})

    def run_world_check(self):
        self.run_environment_card("World Geometries", "world", lambda: {"world": self.collect_world_only()})

    def run_maps_check(self):
        self.run_environment_card("Google Maps API", "maps", lambda: {"maps": self.collect_maps_only()})

    def run_currency_check(self):
        self.run_environment_card("Moeda", "currency", lambda: {"currency": self.collect_currency_only()})

    def run_historical_check(self):
        self.run_environment_card("Histórico", "historical", lambda: {"historical": self.collect_historical_only()})

    def run_environment_card(self, title: str, card_key: str, task: Callable[[], dict[str, Any]]):
        """Valida um único cartão do painel de ambiente (ex.: só MyTeam)."""
        self.show_page("environment")
        self.run_task(
            title,
            task,
            self.render_environment_results,
            "environment",
            [card_key],
        )

    # --- Painéis Encomendas, Vendas e Vendedores ---

    def run_order_checks(self):
        """Valida documentos de encomenda (BO, ERP, MyTeam, tabela vendas)."""
        self.show_page("orders")
        self.run_task(
            "documentos de encomendas",
            lambda: {"orders": self.collect_order_checks()},
            self.render_orders_results,
            "orders",
            ["orders"],
        )

    def run_sales_checks(self):
        """Valida vendas — placeholder até queries_vendas existir."""
        self.show_page("sales")
        self.run_task(
            "vendas",
            lambda: {"sales": self.collect_sales_placeholder()},
            self.render_sales_results,
            "sales",
            ["sales"],
        )

    def run_salesmen_checks(self):
        """Valida mapeamento MSS ↔ ERP e mostra tabela de utilizadores MSS."""
        self.show_page("salesmen")
        self.run_task(
            "vendedores",
            lambda: {"salesmen": self.collect_salesmen_checks()},
            self.render_salesmen_results,
            "salesmen",
            ["salesmen"],
        )

    # =========================================================================
    # FASE 9 — MOTOR ASSÍNCRONO (THREAD)
    # =========================================================================
    # Impede que a UI congele durante SQL/HTTP.
    # Fluxo: run_task → TaskWorker.run → finish_task → render_*_results
    # =========================================================================

    def run_task(
        self,
        title: str,
        task: Callable[[], Any],
        on_success: Callable[[Any], None],
        page_key: str,
        loading_card_keys: list[str],
    ):
        """Orquestra uma validação: bloqueia UI, corre em thread, renderiza resultado."""
        if self.thread is not None:
            QMessageBox.information(self, "Validação em curso", "Aguarde a validação atual terminar.")
            return

        self.current_page_key = page_key
        self.current_success_callback = on_success
        self.loading_card_keys = loading_card_keys
        self.set_busy(True, f"A validar {title}...", page_key)

        self.thread = QThread()
        self.worker = TaskWorker(task)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.finish_task)
        self.worker.failed.connect(self.fail_task)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.cleanup_thread)
        self.thread.start()

    @Slot(object)
    def finish_task(self, result: Any):
        """Chamado quando a thread termina com sucesso — atualiza a UI."""
        if self.current_success_callback is not None:
            self.current_success_callback(result)
        self.set_busy(False, page_key=self.current_page_key)

    @Slot(str)
    def fail_task(self, message: str):
        """Chamado quando a thread falha — mostra erro no log/divergências."""
        self.set_busy(False, page_key=self.current_page_key)
        self.clear_results(self.current_page_key)
        self.set_summary(self.current_page_key, "Ocorreu um erro durante a validação.")

        for key in self.loading_card_keys:
            self.cards[key].set_status("Erro", "Ver log de execução.")

        self.add_detail(self.current_page_key, f"Erro: {message}")
        QMessageBox.critical(self, "Erro", message)

    def cleanup_thread(self):
        self.worker = None
        self.thread = None
        self.current_success_callback = None
        self.loading_card_keys = []

    def set_busy(self, busy: bool, message: str = "", page_key: str | None = None):
        """Ativa/desativa cursor de espera, barra de progresso e botões."""
        page_key = page_key or self.current_page_key
        widgets = self.result_widgets[page_key]

        if message:
            widgets["summary"].setText(message)

        widgets["progress"].setVisible(busy)

        if busy:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            for key in self.loading_card_keys:
                self.cards[key].set_loading()
        else:
            QApplication.restoreOverrideCursor()

        for control in self.validation_controls:
            control.setEnabled(not busy)

        QApplication.processEvents()

    # =========================================================================
    # FASE 10 — COLETA DE DADOS (camada entre UI e backend)
    # =========================================================================
    # Estas funções correm DENTRO da thread (via TaskWorker).
    # Chamam core.verifications e modulos.sage50 — devolvem dicts prontos
    # para a renderização. Não tocam em widgets Qt.
    # =========================================================================

    def collect_environment_checks(self):
        """Agrega todas as verificações do painel de ambiente num único dict."""
        return {
            "myteam": get_myteam_service_info(),
            "webapi_service": get_webapi_service_info(),
            "apikeys": get_webapi_apikey_info(),
            "webapi_status": get_webapi_status_info(),
            "optimizer": get_optimizer_port_info(),
            "sql": self.collect_sql_only(),
            "world": self.collect_world_only(),
            "maps": self.collect_maps_only(),
            "currency": self.collect_currency_only(),
            "historical": self.collect_historical_only(),
        }

    # --- Verificações individuais (cada cartão chama core.verifications) ---

    def collect_sql_only(self):
        """Testa ligação ao SQL Server usando config.json."""
        config = self.ensure_config()
        db_sage, _ = self.ensure_databases()
        db_sage.execute("SELECT 1")
        return {"status": "OK", "server": config["sql_server"]["server"]}

    def collect_world_only(self):
        config = self.ensure_config()
        return get_world_geometries_info(
            server=config["sql_server"]["server"],
            user=config["sql_server"]["user"],
            password=config["sql_server"]["password"],
        )

    def collect_maps_only(self):
        _, db_mss = self.ensure_databases()
        return get_google_maps_api_info(db_mss)

    def collect_currency_only(self):
        _, db_mss = self.ensure_databases()
        return get_currency_symbol_info(db_mss)

    def collect_historical_only(self):
        _, db_mss = self.ensure_databases()
        return get_historical_sync_start_info(db_mss)

    def collect_order_checks(self):
        """Chama validate_order_documents — compara BO, ERP, MyTeam e vendas."""
        db_sage, db_mss = self.ensure_databases()
        return validate_order_documents(db_sage, db_mss)

    def collect_sales_placeholder(self):
        """Placeholder do painel de vendas até existir queries_vendas.py."""
        return {
            "status": "Por fazer",
            "implemented": False,
            "message": "As queries de vendas ainda não foram implementadas.",
        }

    def collect_salesmen_checks(self):
        """Valida vendedores e traz mapeamento bruto para exibir na tabela."""
        db_sage, _ = self.ensure_databases()
        result = validate_salesmen(db_sage)
        result["mapping"] = get_salesmen_mapping(db_sage)
        return result

    # =========================================================================
    # FASE 11 — INFRAESTRUTURA (config + bases de dados)
    # =========================================================================
    # Ligações criadas uma vez e reutilizadas em todas as validações SQL.
    # =========================================================================

    def ensure_config(self):
        """Carrega config.json uma única vez por sessão."""
        if self.config is None:
            self.config = load_config()
        return self.config

    def ensure_databases(self):
        """Abre ligações Sage 50 e MSS reutilizáveis durante a sessão."""
        config = self.ensure_config()

        if self.db_sage is None:
            self.db_sage = Database(
                server=config["sql_server"]["server"],
                database=config["databases"]["sage50"],
                user=config["sql_server"]["user"],
                password=config["sql_server"]["password"],
            )

        if self.db_mss is None:
            self.db_mss = Database(
                server=config["sql_server"]["server"],
                database=config["databases"]["mss"],
                user=config["sql_server"]["user"],
                password=config["sql_server"]["password"],
            )

        return self.db_sage, self.db_mss

    # =========================================================================
    # FASE 12 — RENDERIZAÇÃO (backend → widgets na tela)
    # =========================================================================
    # Cada render_* recebe o dict de collect_* e preenche cartões/tabelas/logs.
    # Corre na thread principal (após finish_task).
    # =========================================================================

    def render_environment_results(self, result: dict[str, Any]):
        """Preenche cartões e tabela do painel de ambiente."""
        page_key = "environment"
        self.clear_results(page_key)

        if "myteam" in result:
            # Serviço Windows do MyTeam (Running / Stopped)
            myteam = result["myteam"]
            self.cards["myteam"].set_status(
                myteam["status"],
                f"Serviço: {myteam['service_name'] or 'não encontrado'}",
            )
            self.add_table_row(page_key, "Ambiente", "MyTeam", myteam["status"], myteam["service_name"] or "")
            if myteam["status"] != "Running":
                self.add_detail(page_key, f"O serviço MyTeam não está em execução. Serviço detetado: {myteam['service_name'] or 'não encontrado'}.")

        if "webapi_service" in result:
            # Serviço Windows da WebAPI + endpoint de status online/offline
            webapi = result["webapi_service"]
            self.cards["webapi_service"].set_status(webapi["status"], f"Serviço: {webapi['service_name']}")
            self.add_table_row(page_key, "Ambiente", "WebAPI", webapi["status"], webapi["service_name"])
            if webapi["status"] != "Running":
                self.add_detail(page_key, f"O serviço WebAPI não está em execução. Serviço detetado: {webapi['service_name']}.")

        if "webapi_status" in result:
            status = result["webapi_status"]
            card_status = "Online" if status["online"] else "Offline"
            detail = self.build_webapi_status_detail(status)
            if status["online"]:
                card_detail = detail
                table_detail = detail
            else:
                card_detail = "Ver log de execução."
                table_detail = "Ver log de execução."
            self.cards["webapi_status"].set_status(card_status, card_detail)
            self.add_table_row(page_key, "Ambiente", "Status WebAPI", card_status, table_detail)
            if not status["online"]:
                self.add_detail(page_key, status.get("message") or "O endpoint Status WebAPI respondeu como offline ou não devolveu detalhe do erro.")

        if "apikeys" in result:
            apikeys = result["apikeys"]
            apikey_detail = "Chaves da WebAPI consistentes."
            if apikeys["status"] != "OK":
                apikey_detail = "Ver log de execução."
                self.add_detail(page_key, "As API Keys da WebAPI estão diferentes entre MSSBO.INI e appsettings.json.")
            self.cards["apikeys"].set_status(apikeys["status"], apikey_detail)
            self.add_table_row(page_key, "Ambiente", "API Keys da WebAPI", apikeys["status"], apikey_detail)

        if "optimizer" in result:
            optimizer = result["optimizer"]
            self.cards["optimizer"].set_status(optimizer["status"], f"Porta {optimizer['port']}")
            self.add_table_row(page_key, "Ambiente", "Otimizador", optimizer["status"], f"Porta {optimizer['port']}")
            if optimizer["status"] != "OK":
                self.add_detail(page_key, f"A porta {optimizer['port']} do otimizador está {optimizer['status']}.")

        if "sql" in result:
            # Teste SELECT 1 na base Sage 50
            sql = result["sql"]
            self.cards["sql"].set_status(sql["status"], f"Servidor: {sql['server']}")
            self.add_table_row(page_key, "SQL", "Ligação", sql["status"], sql["server"])

        if "world" in result:
            world = result["world"]
            detail = self.build_world_detail(world)
            card_detail = "Base de dados encontrada." if world["exists"] else "Ver log de execução."
            self.cards["world"].set_status(world["status"], card_detail)
            self.add_table_row(
                page_key,
                "SQL",
                world["database_name"],
                world["status"],
                detail if world["exists"] else "Ver log de execução.",
            )
            if not world["exists"]:
                self.add_detail(page_key, detail)

        if "maps" in result:
            # Parâmetros Google Maps na base MSS
            maps = result["maps"]
            detail = f"Parâmetros encontrados: {len(maps['parameters'])}"
            card_detail = detail if maps["status"] == "OK" else "Ver log de execução."
            self.cards["maps"].set_status(maps["status"], card_detail)
            self.add_table_row(
                page_key,
                "MSS",
                "Google Maps API",
                maps["status"],
                ", ".join(maps["parameters"]) if maps["status"] == "OK" else "Ver log de execução.",
            )
            if maps["status"] != "OK":
                self.add_detail(page_key, "A configuração da Google Maps API não foi encontrada no MSS.")

        if "currency" in result:
            currency = result["currency"]
            detail = "Todos os terminais têm símbolo."
            if currency["missing_terminals"]:
                detail = "Terminais em falta: " + ", ".join(currency["missing_terminals"])
                self.add_detail(page_key, detail)
            card_detail = detail if currency["status"] == "OK" else "Ver log de execução."
            self.cards["currency"].set_status(currency["status"], card_detail)
            self.add_table_row(
                page_key,
                "MSS",
                "Moeda",
                currency["status"],
                detail if currency["status"] == "OK" else "Ver log de execução.",
            )

        if "historical" in result:
            historical = result["historical"]
            if historical["start_date_formatted"]:
                detail = (
                    "Data do documento mais antigo sincronizado no MSS: "
                    f"{historical['start_date_formatted']}"
                )
                card_detail = f"Doc. mais antigo sincronizado: {historical['start_date_formatted']}"
            else:
                detail = "Não foi encontrado nenhum documento sincronizado no MSS para determinar a data mais antiga."
                card_detail = "Sem dados históricos."
            self.cards["historical"].set_status(historical["status"], card_detail)
            self.add_table_row(page_key, "MSS", "Histórico", historical["status"], detail)

        self.fit_table_to_contents(page_key)
        self.add_no_issues_message(page_key)
        self.set_summary(page_key, "Verificação de ambiente concluída.")

    def render_orders_results(self, result: dict[str, Any]):
        """Preenche as 5 secções e o resumo numérico de encomendas."""
        page_key = "orders"
        self.clear_results(page_key)

        orders = result["orders"]
        status = "OK" if orders["success"] else "Warning"
        detail = (
            "Sem divergências."
            if orders["success"]
            else f"{orders['total_issues']} divergência(s) encontrada(s)."
        )

        self.cards["orders"].set_status(status, detail)

        bo_docs = sorted(orders.get("documents_configured_bo", []))
        erp_order_docs = sorted(orders.get("documents_erp", []))
        integrated_docs = orders.get("documents_integrated", [])
        sales_docs = sorted(orders.get("documents_sales", []))
        total_issues = orders["total_issues"]

        widgets = self.result_widgets[page_key]

        # Resumo numérico (4 cartões no topo)
        widgets["stat_bo"].set_value(len(bo_docs))
        widgets["stat_erp"].set_value(len(erp_order_docs))
        widgets["stat_integrated"].set_value(len(integrated_docs))
        widgets["stat_issues"].set_value(total_issues)

        # Secções 1 a 4 — listas e tabela de integrados
        self.set_doc_list(widgets["bo_list"], bo_docs)
        self.set_doc_list(widgets["erp_list"], erp_order_docs)
        self.populate_integrated_table(widgets["integrated_table"], integrated_docs)
        self.set_doc_list(widgets["sales_list"], sales_docs)

        # Secção 5 — divergências (ou mensagem de sucesso)
        if orders["success"]:
            widgets["issues"].setPlainText("Nenhuma divergência encontrada.")
        else:
            issue_lines = [f"⚠ {issue['message']}" for issue in orders["issues"]]
            widgets["issues"].setPlainText("\n".join(issue_lines))

        widgets["has_results"] = True

        if orders["success"]:
            summary_text = "Validação de documentos de encomendas concluída sem divergências."
        else:
            summary_text = (
                f"Validação concluída com {total_issues} divergência(s). "
                "Consulte a secção 5 para o detalhe."
            )

        self.set_summary(page_key, summary_text)

    def render_sales_results(self, result: dict[str, Any]):
        """Placeholder — informa que vendas ainda não foi implementado."""
        page_key = "sales"
        self.clear_results(page_key)

        sales = result["sales"]
        self.cards["sales"].set_status(sales["status"], "Ainda não implementado.")
        self.add_table_row(page_key, "Vendas", "Estado", sales["status"], sales["message"])
        self.add_detail(page_key, sales["message"])

        self.fit_table_to_contents(page_key)
        self.set_summary(page_key, "Validação de vendas concluída.")

    def render_salesmen_results(self, result: dict[str, Any]):
        """Tabela só com utilizadores MSS (sem ERP, sem ADMIN). Divergências no log."""
        page_key = "salesmen"
        self.clear_results(page_key)

        salesmen = result["salesmen"]
        mapping = self.filter_mss_salesmen_mapping(salesmen.get("mapping", []))
        total_issues = salesmen["total_issues"]
        detail = (
            f"{len(mapping)} utilizadores MSS analisados."
            if salesmen["success"]
            else "Ver log de execução."
        )
        status = "OK" if salesmen["success"] else "Warning"

        self.cards["salesmen"].set_status(status, detail)

        for row in mapping:
            self.add_salesman_mapping_row(page_key, row)

        for issue in salesmen["issues"]:
            self.add_detail(page_key, issue["message"])

        self.fit_table_to_contents(page_key)
        self.add_no_issues_message(page_key)

        if total_issues:
            summary_text = (
                f"Validação de vendedores concluída com {total_issues} "
                f"divergência(s). Foram analisados {len(mapping)} "
                "utilizadores MSS. Consulte o log de execução para o detalhe."
            )
        else:
            summary_text = (
                f"Validação de vendedores concluída sem divergências. "
                f"Foram analisados {len(mapping)} utilizadores MSS."
            )

        self.set_summary(page_key, summary_text)

    # =========================================================================
    # FASE 13 — FORMATAÇÃO DE VALORES PARA EXIBIÇÃO
    # =========================================================================

    def build_webapi_status_detail(self, status: dict[str, Any]):
        parts = []

        if status.get("api_version"):
            parts.append(f"Versão API: {status['api_version']}")

        if status.get("date_on_server_formatted"):
            parts.append(f"Servidor: {status['date_on_server_formatted']}")

        return " | ".join(parts) or "Sem detalhes."

    def build_world_detail(self, world: dict[str, Any]):
        if world["exists"]:
            return "Base de dados encontrada."

        return f"A base de dados {world['database_name']} não foi encontrada. Suporte: {world['support_link']}"

    def format_currency(self, value: Any) -> str:
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return "-"

        formatted = f"{numeric_value:,.2f}"
        formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{formatted} €"

    def format_amount(self, value: Any) -> str:
        """Total líquido na tabela de integrados (ex.: 155 000)."""
        try:
            numeric_value = int(round(float(value)))
        except (TypeError, ValueError):
            return "-"

        formatted = f"{numeric_value:,}"
        return formatted.replace(",", " ")

    def set_doc_list(self, widget: QTextEdit, documents: list[str]):
        if documents:
            widget.setPlainText("\n".join(documents))
        else:
            widget.setPlainText("Nenhum documento encontrado.")

    def populate_integrated_table(self, table: QTableWidget, integrated_docs: list[dict[str, Any]]):
        table.setRowCount(0)

        for item in integrated_docs:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(item.get("documento", ""))))
            table.setItem(row, 1, QTableWidgetItem(str(item.get("total_documentos", 0))))
            table.setItem(row, 2, QTableWidgetItem(self.format_amount(item.get("total_liquido"))))

        table.resizeRowsToContents()
        header_height = table.horizontalHeader().height()
        rows_height = sum(table.rowHeight(row_index) for row_index in range(table.rowCount()))
        frame = table.frameWidth() * 2
        total_height = header_height + rows_height + frame + 6
        total_height = max(total_height, header_height + 50)
        table.setFixedHeight(total_height)

    # =========================================================================
    # FASE 14 — GESTÃO DOS WIDGETS DE RESULTADO
    # =========================================================================
    # Limpar painéis, inserir linhas nas tabelas, escrever logs e ajustar altura.
    # =========================================================================

    def clear_results(self, page_key: str):
        """Repor painel ao estado inicial antes de uma nova validação."""
        widgets = self.result_widgets[page_key]

        if page_key == "orders":
            # Layout especial de encomendas — repor cada secção
            widgets["stat_bo"].set_value(0)
            widgets["stat_erp"].set_value(0)
            widgets["stat_integrated"].set_value(0)
            widgets["stat_issues"].set_value(0)
            widgets["bo_list"].clear()
            widgets["erp_list"].clear()
            widgets["sales_list"].clear()
            widgets["integrated_table"].setRowCount(0)
            widgets["integrated_table"].setFixedHeight(96)
            widgets["issues"].clear()
            widgets["has_results"] = False
            return

        # Layout padrão — tabela + log de execução
        widgets["table"].setRowCount(0)
        widgets["log"].clear()
        widgets["table"].setFixedHeight(96)

    def fit_table_to_contents(self, page_key: str):
        """Ajusta a altura da tabela ao conteúdo; scroll fica na página."""
        table = self.result_widgets[page_key]["table"]
        table.resizeRowsToContents()

        header_height = table.horizontalHeader().height()
        rows_height = sum(table.rowHeight(row) for row in range(table.rowCount()))
        frame = table.frameWidth() * 2

        total_height = header_height + rows_height + frame + 6
        total_height = max(total_height, header_height + 50)

        table.setFixedHeight(total_height)

    def set_summary(self, page_key: str, text: str):
        self.result_widgets[page_key]["summary"].setText(text)

    def add_detail(self, page_key: str, text: str):
        """Escreve no log (painéis normais) ou na caixa de divergências (encomendas)."""
        widgets = self.result_widgets[page_key]
        if page_key == "orders":
            current = widgets["issues"].toPlainText().strip()
            if current:
                widgets["issues"].append(f"\n{text}")
            else:
                widgets["issues"].setPlainText(text)
            return

        widgets["log"].append(text)

    def add_no_issues_message(self, page_key: str):
        if page_key == "orders":
            return

        if not self.result_widgets[page_key]["log"].toPlainText().strip():
            self.add_detail(page_key, "Nenhuma divergência encontrada.")

    def add_table_row(self, page_key: str, area: str, item: str, status: str, detail: str):
        self.add_table_values(
            page_key,
            [area, item, self.format_status_text(str(status)), detail],
            status_column=2,
            status_value=str(status),
        )

    def filter_mss_salesmen_mapping(self, mapping: list[dict[str, str]]) -> list[dict[str, str]]:
        # Tabela mostra só MSS; vendedores ERP e utilizador ADMIN ficam de fora
        return [
            row
            for row in mapping
            if row["origem"].upper() == "MSS"
            and row["codigo_vendedor"].strip().upper() != "ADMIN"
        ]

    def add_salesman_mapping_row(self, page_key: str, row: dict[str, str]):
        self.add_table_values(
            page_key,
            [
                row["origem"],
                row["codigo_vendedor"],
                row["nome_vendedor"],
                row["codigo_vendedor_erp"],
            ],
        )

    def add_table_values(
        self,
        page_key: str,
        values: list[str],
        status_column: int | None = None,
        status_value: str | None = None,
    ):
        table = self.result_widgets[page_key]["table"]
        row = table.rowCount()
        table.insertRow(row)

        for column, value in enumerate(values):
            table_item = QTableWidgetItem(str(value))
            if status_column is not None and column == status_column:
                table_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table_item.setForeground(self.status_text_color(status_value or str(value)))
                font = table_item.font()
                font.setBold(True)
                table_item.setFont(font)
            table.setItem(row, column, table_item)

        table.resizeColumnsToContents()
        table.resizeRowsToContents()

    def format_status_text(self, status: str):
        return status

    def status_text_color(self, status: str):
        """Verde para estados positivos, vermelho para avisos/erros."""
        normalized = status.strip().lower()

        if normalized in {"ok", "running", "true", "online"}:
            return QColor("#1a7f37")

        if normalized in {
            "warning", "missing", "different", "closed", "no data", "por fazer",
            "error", "stopped", "false", "offline",
        }:
            return QColor("#c62828")

        return QColor("#20242a")

    # =========================================================================
    # FASE 15 — EXPORTAÇÃO EXCEL
    # =========================================================================
    # Gera .xlsx sem dependências externas (XML + ZIP manual).
    # Encomendas exporta as 5 secções; restantes exportam a tabela visível.
    # =========================================================================

    def export_orders_to_excel(self, file_path: str):
        """Monta Excel multi-secção a partir dos widgets de encomendas."""
        widgets = self.result_widgets["orders"]
        rows = [
            ["BackOffice", widgets["stat_bo"].value_label.text()],
            ["ERP", widgets["stat_erp"].value_label.text()],
            ["Integrados", widgets["stat_integrated"].value_label.text()],
            ["Divergências", widgets["stat_issues"].value_label.text()],
            [],
            ["1. Documentos configurados no BackOffice"],
            *[[doc] for doc in widgets["bo_list"].toPlainText().splitlines() if doc.strip()],
            [],
            ["2. Documentos de encomenda no ERP"],
            *[[doc] for doc in widgets["erp_list"].toPlainText().splitlines() if doc.strip()],
            [],
            ["3. Documentos integrados no MyTeam"],
            ["Documento", "Quantidade", "Total Líquido"],
        ]

        table = widgets["integrated_table"]
        for row_index in range(table.rowCount()):
            rows.append([
                table.item(row_index, column).text() if table.item(row_index, column) else ""
                for column in range(table.columnCount())
            ])

        rows.extend([
            [],
            ["4. Documentos na tabela de vendas"],
            *[[doc] for doc in widgets["sales_list"].toPlainText().splitlines() if doc.strip()],
            [],
            ["5. Divergências"],
            *[[line] for line in widgets["issues"].toPlainText().splitlines() if line.strip()],
        ])

        self.write_xlsx(Path(file_path), rows)

    def export_table_to_excel(self, file_path: str):
        """Exporta a tabela visível do painel atual (ambiente/vendas/vendedores)."""
        table = self.result_widgets[self.current_page_key]["table"]
        rows = []

        headers = []
        for column in range(table.columnCount()):
            item = table.horizontalHeaderItem(column)
            headers.append(item.text() if item else "")
        rows.append(headers)

        for row in range(table.rowCount()):
            values = []
            for column in range(table.columnCount()):
                item = table.item(row, column)
                values.append(item.text() if item else "")
            rows.append(values)

        self.write_xlsx(Path(file_path), rows)

    def write_xlsx(self, file_path: Path, rows: list[list[str]]):
        """Escreve ficheiro Excel (.xlsx) a partir de linhas de texto."""
        sheet_rows = []

        for row_index, row in enumerate(rows, start=1):
            cells = []
            for column_index, value in enumerate(row, start=1):
                cell = self.excel_cell_name(row_index, column_index)
                safe_value = escape(str(value))
                cells.append(
                    f'<c r="{cell}" t="inlineStr"><is><t>{safe_value}</t></is></c>'
                )
            sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

        sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {"".join(sheet_rows)}
  </sheetData>
</worksheet>"""

        with ZipFile(file_path, "w", ZIP_DEFLATED) as workbook:
            workbook.writestr(
                "[Content_Types].xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
            )
            workbook.writestr(
                "_rels/.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
            )
            workbook.writestr(
                "xl/workbook.xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Resumo" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
            )
            workbook.writestr(
                "xl/_rels/workbook.xml.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
            )
            workbook.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    def excel_cell_name(self, row: int, column: int):
        name = ""
        while column:
            column, remainder = divmod(column - 1, 26)
            name = chr(65 + remainder) + name
        return f"{name}{row}"

    # =========================================================================
    # FASE 16 — ESTILOS VISUAIS (QSS)
    # =========================================================================
    # Folha de estilos global: cores, bordas, estados dos cartões e tabelas.
    # =========================================================================

    def apply_styles(self):
        self.setStyleSheet(
            """
            QWidget {
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 13px;
                color: #20242a;
            }

            #sidebar {
                background: #16202a;
                color: white;
            }

            #contentScroll,
            #contentPage {
                background: #f4f7fa;
            }

            QScrollArea {
                border: none;
            }

            #appTitle {
                color: white;
                font-size: 22px;
                font-weight: 700;
            }

            #appSubtitle,
            #sidebarHint {
                color: #b8c2cc;
            }

            QPushButton {
                min-height: 36px;
                padding: 8px 12px;
                border-radius: 6px;
                border: 1px solid #c9d2dc;
                background: #f8fafc;
                text-align: left;
            }

            QPushButton:hover {
                background: #eef4f8;
            }

            QPushButton[active="true"] {
                color: white;
                border: 1px solid #21866f;
                background: #21866f;
                font-weight: 700;
            }

            QPushButton[primary="true"] {
                color: white;
                border: 2px solid #0d2b22;
                background: #21866f;
                font-weight: 700;
                text-align: center;
            }

            QPushButton[primary="true"]:hover {
                background: #1b6f5c;
                border: 2px solid #0d2b22;
            }

            QPushButton[export="true"] {
                color: #10251f;
                border: 1px solid #9ccbb9;
                background: #dff5ea;
                font-weight: 700;
            }

            QPushButton[export="true"]:hover {
                background: #cceedd;
            }

            QPushButton:disabled {
                color: #89939f;
                background: #e7ebef;
            }

            #pageTitle {
                font-size: 24px;
                font-weight: 700;
            }

            #pageSubtitle {
                color: #59636f;
            }

            #summaryLabel {
                color: #23303b;
                background: #eaf5ef;
                border: 1px solid #cce7da;
                border-radius: 6px;
                padding: 8px 10px;
                font-weight: 600;
            }

            #sectionLabel {
                font-weight: 700;
                color: #20242a;
            }

            QGroupBox {
                border: 1px solid #d9e1e8;
                border-radius: 8px;
                margin-top: 12px;
                font-weight: 700;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }

            #resultsGroup {
                border: 1px solid #cbd8e4;
                background: #ffffff;
            }

            #resultsGroup::title {
                color: #0f1720;
                font-size: 14px;
            }

            #statusCard {
                border: 1px solid #d9e1e8;
                border-radius: 8px;
                background: white;
            }

            #statusCard:hover {
                border: 1px solid #21866f;
                background: #fbfefd;
            }

            #countStatCard {
                border: 1px solid #cbd8e4;
                border-radius: 8px;
                background: #ffffff;
                min-width: 120px;
            }

            #countStatTitle {
                color: #59636f;
                font-weight: 600;
                font-size: 12px;
            }

            #countStatValue {
                color: #0f1720;
                font-size: 28px;
                font-weight: 700;
            }

            #docListBox,
            #issuesBox {
                color: #24303a;
                background: #fbfcfd;
                border: 1px solid #d9e1e8;
                border-radius: 4px;
            }

            #statusCard:disabled {
                background: #f1f4f7;
            }

            #cardTitle {
                font-weight: 700;
            }

            #cardDetail {
                color: #59636f;
            }

            #statusPill {
                border-radius: 6px;
                padding: 5px 8px;
                font-weight: 700;
                background: #e7ebef;
                color: #39414a;
            }

            #statusPill[state="ok"] {
                background: #dff5ea;
                color: #14633f;
            }

            #statusPill[state="warning"] {
                background: #fff2cc;
                color: #795400;
            }

            #statusPill[state="error"] {
                background: #fde2e1;
                color: #9b1c1c;
            }

            #statusPill[state="loading"] {
                background: #dceeff;
                color: #155a9a;
            }

            QTableWidget,
            QTextEdit {
                border: 1px solid #d9e1e8;
                border-radius: 6px;
                background: white;
            }

            QTableWidget {
                alternate-background-color: #f7fafc;
                gridline-color: #3c4a58;
                selection-background-color: #cfe8df;
                selection-color: #142027;
            }

            QTableWidget::item {
                padding: 6px;
                border-right: 2px solid #3c4a58;
                border-bottom: 2px solid #3c4a58;
            }

            QHeaderView::section {
                color: white;
                background: #263441;
                border-right: 2px solid #0f1720;
                border-bottom: 3px solid #0f1720;
                padding: 7px;
                font-weight: 700;
            }

            QTextEdit {
                color: #24303a;
                background: #fbfcfd;
            }

            QProgressBar {
                border: 1px solid #d9e1e8;
                border-radius: 5px;
                min-height: 10px;
                background: #edf2f6;
            }

            QProgressBar::chunk {
                border-radius: 5px;
                background: #21866f;
            }
            """
        )