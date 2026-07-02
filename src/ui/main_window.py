"""Interface PySide6 do Kit de Validação MyTeam vs ERP.

A lógica de validação fica em core/ e modulos/; este ficheiro monta a janela,
executa as validações em background e apresenta resultados, logs e exportações.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from PySide6.QtCore import QDate, QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
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
    get_expenses_version_info,
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
from modulos.sage50.queries_vendedores import get_erp_salesmen, get_integrated_salesmen, get_salesmen_mapping, validate_salesmen
from modulos.sage50.queries_vendas import validate_sales_documents


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
        normalized = str(status).lower()

        if normalized in {"ok", "running", "true", "online", "v1", "v2"}:
            state = "ok"
        elif normalized in {"warning", "missing", "different", "closed", "no data", "por fazer", "pendente"}:
            state = "warning"
        elif normalized in {"error", "stopped", "false", "offline"}:
            state = "error"
        elif normalized == "a validar...":
            state = "loading"
        else:
            state = "neutral"

        self.setProperty("cardState", state)
        self.status_label.setProperty("state", state)
        self.status_label.setText(str(status))
        self.detail_label.setText(detail or "Sem detalhes adicionais.")
        self.style().unpolish(self)
        self.style().polish(self)
        self.style().unpolish(self.status_label)
        self.style().polish(self.status_label)


class CountStatCard(QFrame):
    """
    Cartão numérico do painel de encomendas (BackOffice, ERP, Integrados, Divergências).
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

    def set_state(self, state: str | None):
        self.value_label.setProperty("state", state)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)


class MainWindow(QMainWindow):
    """
    Janela principal da aplicação.

    Responsabilidades:
      - Montar os 6 painéis de validação (incluindo Definições e Logs)
      - Ligar botões/cartões às funções collect_* do backend
      - Mostrar resultados em tabelas, listas e logs
      - Exportar relatórios para Excel
    """

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        self.setWindowTitle("Kit de Validação MyTeam vs ERP")
        self.resize(1180, 760)
        self.setMinimumSize(1040, 680)

        # As ligações SQL só são criadas quando uma validação precisa delas.
        self.config: dict[str, Any] | None = config
        self.db_sage: Database | None = None
        self.db_mss: Database | None = None

        self.thread: QThread | None = None
        self.worker: TaskWorker | None = None
        self.current_success_callback: Callable[[Any], None] | None = None
        self.current_page_key = "environment"
        self.loading_card_keys: list[str] = []

        self.cards: dict[str, StatusCard] = {}
        self.result_widgets: dict[str, dict[str, Any]] = {}
        self.filter_widgets: dict[str, dict[str, Any]] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        self.validation_controls: list[QWidget] = []

        self.global_log_widget: QTextEdit | None = None

        self.expenses_result: dict | None = None

        self.build_ui()
        self.apply_styles()
        self.show_page("environment")
        self._refresh_settings_panel()

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
        """Menu lateral com navegação entre os 6 painéis e exportação."""
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

        sep_validations = QLabel("VALIDAÇÕES")
        sep_validations.setObjectName("sidebarSectionLabel")
        layout.addWidget(sep_validations)

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

        layout.addSpacing(6)
        sep_system = QLabel("SISTEMA")
        sep_system.setObjectName("sidebarSectionLabel")
        layout.addWidget(sep_system)

        self.nav_buttons["settings"] = self.create_nav_button(
            "Definições",
            lambda: self.show_page("settings"),
        )
        self.nav_buttons["logs"] = self.create_nav_button(
            "Logs",
            lambda: self.show_page("logs"),
        )
        layout.addWidget(self.nav_buttons["settings"])
        layout.addWidget(self.nav_buttons["logs"])

        layout.addStretch()

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
        """Área principal: título + subtítulo + stack com os 6 painéis."""
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

        header_divider = QFrame()
        header_divider.setObjectName("headerDivider")
        header_divider.setFixedHeight(2)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.build_environment_page())   # 0
        self.stack.addWidget(self.build_orders_page())        # 1
        self.stack.addWidget(self.build_sales_page())         # 2
        self.stack.addWidget(self.build_salesmen_page())      # 3
        self.stack.addWidget(self.build_settings_page())      # 4
        self.stack.addWidget(self.build_logs_page())          # 5

        layout.addWidget(self.page_title)
        layout.addWidget(self.page_subtitle)
        layout.addWidget(header_divider)
        layout.addWidget(self.stack, 1)

        scroll.setWidget(content)
        return scroll

    def build_environment_page(self):
        """Painel 0: serviços Windows, WebAPI, SQL Server e configs MSS."""
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        cards = [
            ("myteam", "MyTeam", self.run_myteam_check),
            ("webapi_service", "WebAPI", self.run_webapi_service_check),
            ("webapi_status", "Status WebAPI", self.run_webapi_status_check),
            ("apikeys", "API Keys da WebAPI", self.run_apikeys_check),
            ("optimizer", "Otimizador", self.run_optimizer_check),
            ("sql", "SQL Server", self.run_sql_check),
            ("world", "World Geometries", self.run_world_check),
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

        layout.addWidget(self.build_filter_bar("orders", include_salesman=True))
        layout.addWidget(self.build_cards_group("Documentos de encomendas", cards, "orders"))

        validate_button = self.create_validation_button(
            "Validar documentos de encomendas",
            self.run_order_checks,
            primary=True,
        )
        layout.addWidget(validate_button)
        layout.addWidget(self.build_orders_results_section("orders"), 1)
        return page

    def build_sales_page(self):
        """Painel 2: vendas (ainda por implementar)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        cards = [
            ("sales", "Vendas", self.run_sales_checks),
        ]

        layout.addWidget(self.build_filter_bar("sales", include_salesman=True))
        layout.addWidget(self.build_cards_group("Vendas", cards, "sales"))

        validate_button = self.create_validation_button(
            "Validar vendas",
            self.run_sales_checks,
            primary=True,
        )
        layout.addWidget(validate_button)
        layout.addWidget(self.build_orders_results_section("sales"), 1)
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

    def build_filter_bar(self, page_key: str, include_salesman: bool):
        """Filtros visuais usados antes das validações documentais."""
        group = QGroupBox("Filtros")
        group.setObjectName("filterGroup")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(12)

        start_date = self.create_date_filter()
        start_date.setMaximumDate(QDate.currentDate())
        end_date = self.create_date_filter()

        layout.addWidget(self.create_labeled_control("Data início", start_date))
        layout.addWidget(self.create_labeled_control("Data fim", end_date))

        widgets: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
        }

        if include_salesman:
            salesman_combo = QComboBox()
            salesman_combo.setObjectName("filterCombo")
            salesman_combo.addItem("Todos os vendedores", None)
            salesman_combo.setMinimumWidth(240)
            salesman_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.validation_controls.append(salesman_combo)
            layout.addWidget(self.create_labeled_control("Vendedor", salesman_combo), 1)
            widgets["salesman"] = salesman_combo

        layout.addStretch()
        self.filter_widgets[page_key] = widgets
        return group

    def create_date_filter(self):
        date_edit = QDateEdit()
        date_edit.setObjectName("filterDate")
        date_edit.setCalendarPopup(True)
        date_edit.setDisplayFormat("dd/MM/yyyy")
        date_edit.setDate(QDate.currentDate())
        date_edit.setMinimumWidth(132)
        self.validation_controls.append(date_edit)
        return date_edit

    def create_labeled_control(self, label_text: str, control: QWidget):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        label = QLabel(label_text)
        label.setObjectName("filterLabel")
        layout.addWidget(label)
        layout.addWidget(control)
        return container

    def build_settings_page(self):
        """
        Painel 4: Definições — mostra informação de ligação carregada do config.json.
        Não mostra o caminho do ficheiro.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        
        group = QGroupBox("Consola de definições")
        group.setObjectName("settingsGroup")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(16, 16, 16, 16)
        group_layout.setSpacing(12)
        
        subtitle = QLabel("Parâmetros de conectividade ativos obtidos a partir do ficheiro de configuração local.")
        subtitle.setObjectName("settingsSubtitle")
        subtitle.setWordWrap(True)
        group_layout.addWidget(subtitle)
        
        info_frame = QFrame()
        info_frame.setObjectName("settingsInfoFrame")
        info_frame.setFixedHeight(160)
        
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(16, 14, 16, 14)
        info_layout.setSpacing(8)
        
        self.settings_sql_label = QLabel("Servidor SQL: —")
        self.settings_sql_label.setObjectName("settingsInfoLine")
        self.settings_erp_label = QLabel("Base ERP (Sage 50): —")
        self.settings_erp_label.setObjectName("settingsInfoLine")
        self.settings_mss_label = QLabel("Base MSS: —")
        self.settings_mss_label.setObjectName("settingsInfoLine")
        for lbl in (self.settings_sql_label, self.settings_erp_label, self.settings_mss_label):
            info_layout.addWidget(lbl)
            
        group_layout.addWidget(info_frame)

        self.settings_expenses_card = StatusCard("Versão de Despesas", "Clique para verificar a versão de despesas em uso.")
        self.settings_expenses_card.clicked.connect(self.run_expenses_version_check)
        self.apply_soft_shadow(self.settings_expenses_card, blur=14, alpha=22, y_offset=2)
        self.cards["expenses_version"] = self.settings_expenses_card
        self.validation_controls.append(self.settings_expenses_card)
        group_layout.addWidget(self.settings_expenses_card)

        reconfigure_btn = QPushButton("Reconfigurar ligação SQL")
        reconfigure_btn.setObjectName("reconfigureBtn")
        reconfigure_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reconfigure_btn.setFixedHeight(44)
        reconfigure_btn.clicked.connect(self._reconfigure_sql)
        self.validation_controls.append(reconfigure_btn)
        group_layout.addWidget(reconfigure_btn)

        layout.addWidget(group)
        layout.addStretch()
        return page

    def _reconfigure_sql(self):
        from core.config_loader import save_config
        from ui.config_dialog import ConfigDialog

        existing = None
        try:
            existing = load_config()
        except Exception:
            pass

        dialog = ConfigDialog(existing_config=existing)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        config = dialog.get_config()
        save_config(config)
        self.config = config
        self._refresh_settings_panel()
        self.append_global_log("Ligação SQL reconfigurada com sucesso.", level="ok")

    def build_logs_page(self):
        """
        Painel 5: Logs — consola estilo VSCode com todas as verificações executadas.
        Cada entrada tem prefixo [HH:MM:SS] e cor por nível (info / ok / warning / error).
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        
        group = QGroupBox("Consola de logs")
        group.setObjectName("logsGroup")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(16, 16, 16, 16)
        group_layout.setSpacing(12)
        
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        
        subtitle = QLabel("Registo cronológico das validações executadas nesta sessão.")
        subtitle.setObjectName("logsSubtitle")
        subtitle.setWordWrap(True)
        top_row.addWidget(subtitle, 1)
        
        clear_btn = QPushButton("Limpar logs")
        clear_btn.setObjectName("clearLogsButton")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setFixedSize(110, 32)
        clear_btn.clicked.connect(self.clear_global_log)
        top_row.addWidget(clear_btn)

        export_logs_btn = QPushButton("Exportar TXT")
        export_logs_btn.setObjectName("exportLogsButton")
        export_logs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_logs_btn.setFixedSize(120, 32)
        export_logs_btn.clicked.connect(self.export_logs_to_txt)
        top_row.addWidget(export_logs_btn)
        
        group_layout.addLayout(top_row)
        
        log_terminal = QTextEdit()
        log_terminal.setReadOnly(True)
        log_terminal.setObjectName("logTerminal")
        log_terminal.setFixedHeight(480)
        log_terminal.setPlaceholderText("Nenhuma validação executada ainda nesta sessão.")
        
        mono_font = QFont("Consolas", 12)
        if not mono_font.exactMatch():
            mono_font = QFont("Courier New", 12)
        log_terminal.setFont(mono_font)
        
        group_layout.addWidget(log_terminal)
        layout.addWidget(group)
        layout.addStretch()
        
        self.global_log_widget = log_terminal
        return page

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
            self.apply_soft_shadow(card, blur=14, alpha=22, y_offset=2)
            self.cards[key] = card
            self.validation_controls.append(card)
            grid.addWidget(card, index // columns, index % columns)

        if action_widget is not None:
            action_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            row = len(cards) // columns
            column = len(cards) % columns
            column_span = max(1, columns - column)
            grid.addWidget(action_widget, row, column, 1, column_span)

        return group

    def build_results_section(self, page_key: str):
        """Layout padrão de resultados: resumo + barra progresso + tabela + log."""
        group = QGroupBox("Resultados da validação")
        group.setObjectName("resultsGroup")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(10)
        
        summary = QLabel("Clique numa caixa acima ou no botão de validação.")
        summary.setObjectName("summaryLabel")
        summary.setWordWrap(True)
        
        updated_label = QLabel("")
        updated_label.setObjectName("updatedLabel")
        updated_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        updated_font = QFont("Segoe UI", 12, QFont.Weight.Bold)
        if not updated_font.exactMatch():
            updated_font = QFont("Arial", 12, QFont.Weight.Bold)
        updated_label.setFont(updated_font)
        updated_label.setStyleSheet("color: #000000; padding-right: 4px;")
        
        summary_row = QHBoxLayout()
        summary_row.setSpacing(10)
        summary_row.addWidget(summary, 1)
        summary_row.addWidget(updated_label)
        
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
        
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        table.setMinimumHeight(160)
        table.setMaximumHeight(260)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        table.setShowGrid(True)
        table.setGridStyle(Qt.PenStyle.SolidLine)
        table.setWordWrap(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        
        for column in range(len(table_headers)):
            resize_mode = (
                QHeaderView.ResizeMode.Stretch
                if column == len(table_headers) - 1
                else QHeaderView.ResizeMode.ResizeToContents
            )
            table.horizontalHeader().setSectionResizeMode(column, resize_mode)
            
        log_label = QLabel("Log de execução")
        log_label.setObjectName("sectionLabel")
        
        log_box = QTextEdit()
        log_box.setReadOnly(True)
        log_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_box.setMinimumHeight(140)
        log_box.setPlaceholderText("As mensagens da validação aparecem aqui.")
        
        layout.addLayout(summary_row)
        layout.addWidget(progress)
        layout.addWidget(table_label)
        layout.addWidget(table)
        layout.addWidget(log_label)
        layout.addWidget(log_box)
        
        self.result_widgets[page_key] = {
            "summary": summary,
            "updated_label": updated_label,
            "progress": progress,
            "table": table,
            "log": log_box,
        }
        return group

    def build_orders_results_section(self, page_key: str = "orders"):
        """Layout de validação documental usado por encomendas e vendas."""
        erp_section_title = (
            "2. Documentos de venda existentes no ERP"
            if page_key == "sales"
            else "2. Documentos de encomenda existentes no ERP"
        )

        group = QGroupBox("Resultados da validação")
        group.setObjectName("resultsGroup")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(12)
        summary = QLabel("Clique na caixa acima ou no botão de validação.")
        summary.setObjectName("summaryLabel")
        summary.setWordWrap(True)
        
        updated_label = QLabel("")
        updated_label.setObjectName("updatedLabel")
        updated_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        updated_font = QFont("Segoe UI", 12, QFont.Weight.Bold)
        if not updated_font.exactMatch():
            updated_font = QFont("Arial", 12, QFont.Weight.Bold)
        updated_label.setFont(updated_font)
        updated_label.setStyleSheet("color: #000000; padding-right: 4px;")

        summary_row = QHBoxLayout()
        summary_row.setSpacing(10)
        summary_row.addWidget(summary, 1)
        summary_row.addWidget(updated_label)
        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.hide()
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        stat_bo = CountStatCard("BackOffice")
        stat_erp = CountStatCard("ERP")
        stat_integrated = CountStatCard("Integrados")
        stat_issues = CountStatCard("Divergências")
        for stat_card in (stat_bo, stat_erp, stat_integrated, stat_issues):
            self.apply_soft_shadow(stat_card, blur=14, alpha=22, y_offset=2)
        stats_row.addWidget(stat_bo)
        stats_row.addWidget(stat_erp)
        stats_row.addWidget(stat_integrated)
        stats_row.addWidget(stat_issues)
        section_bo, bo_list = self.build_doc_list_section(
            "1. Documentos configurados no BackOffice para os Dashboards"
        )
        section_erp, erp_list = self.build_doc_list_section(erp_section_title)
        
        section_integrated = QGroupBox("3. Tipos de documentos já integrados no MyTeam")
        integrated_layout = QVBoxLayout(section_integrated)

        if page_key == "sales":
            info_text = (
                "MSS: TotalDocumentos = COUNT(*) na STMSDCC (DOCS_VEN)  |  "
                "TotalLiquido = SUM(DCCVLL) na STMSDCC<br>"
                "ERP: TotalDocumentos = COUNT(*) na SaleTransaction  |  "
                "TotalLiquido = SUM(TotalNetAmount) na SaleTransaction"
            )
        else:
            info_text = (
                "MSS: TotalDocumentos = COUNT(*) na STMSDCC (DOCS_ENC)  |  "
                "TotalLiquido = SUM(DCCVLL) na STMSDCC<br>"
                "ERP: TotalDocumentos = COUNT(*) na SaleTransaction  |  "
                "TotalLiquido = SUM(TotalNetAmount) na SaleTransaction"
            )
        integrated_info = QLabel(info_text)
        integrated_info.setObjectName("integratedInfo")
        integrated_info.setWordWrap(True)
        integrated_info.setStyleSheet("color: #555; font-size: 12px; padding: 4px 0;")
        integrated_layout.addWidget(integrated_info)

        integrated_table = QTableWidget(0, 8)
        integrated_table.setHorizontalHeaderLabels([
            "Vendedor", "Código Vendedor", "Documento",
            "Qt. MSS", "Total Líq. MSS",
            "Qt. ERP", "Total Líq. ERP", "Diferença"
        ])
        integrated_table.setAlternatingRowColors(True)
        integrated_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        integrated_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        integrated_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        integrated_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        integrated_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        integrated_table.verticalHeader().setVisible(False)
        integrated_table.verticalHeader().setDefaultSectionSize(34)
        for col in range(8):
            integrated_table.horizontalHeader().setSectionResizeMode(
                col,
                QHeaderView.ResizeMode.ResizeToContents if col != 0 else QHeaderView.ResizeMode.Stretch
            )
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
        layout.addLayout(summary_row)
        layout.addWidget(progress)
        layout.addLayout(stats_row)
        layout.addWidget(section_bo)
        layout.addWidget(section_erp)
        layout.addWidget(section_integrated)
        layout.addWidget(section_sales)
        layout.addWidget(section_issues)
        self.result_widgets[page_key] = {
            "summary": summary,
            "updated_label": updated_label,
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
        if page_key == "salesmen":
            return ["Origem", "Código", "Nome", "Código ERP"]
        return ["Área", "Item", "Estado", "Detalhe"]

    def create_nav_button(self, text: str, callback: Callable[[], None]):
        button = QPushButton(text)
        button.clicked.connect(callback)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def apply_soft_shadow(self, widget: QWidget, blur: int = 18, alpha: int = 30, y_offset: int = 2):
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(blur)
        effect.setOffset(0, y_offset)
        effect.setColor(QColor(15, 23, 32, alpha))
        widget.setGraphicsEffect(effect)

    def create_validation_button(self, text: str, callback: Callable[[], None], primary: bool = False):
        button = QPushButton(text)
        button.clicked.connect(callback)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("primary", primary)
        self.validation_controls.append(button)
        return button

    def export_current_results(self):
        """Exporta o painel aberto. Definições e Logs não têm exportação."""
        if self.current_page_key in ("settings", "logs"):
            QMessageBox.information(
                self,
                "Exportar Excel",
                "Este painel não possui resultados em Excel para exportar. Use a exportação própria do painel quando existir.",
            )
            return

        if self.current_page_key in ("orders", "sales"):
            widgets = self.result_widgets.get(self.current_page_key)
            if not widgets or not widgets.get("has_results"):
                QMessageBox.information(
                    self,
                    "Exportar Excel",
                    "Ainda não existem resultados para exportar neste painel. Execute primeiro uma validação.",
                )
                return
        else:
            widgets = self.result_widgets.get(self.current_page_key)
            table = widgets.get("table") if widgets else None
            if table is None or table.rowCount() == 0:
                QMessageBox.information(
                    self,
                    "Exportar Excel",
                    "Ainda não existem resultados para exportar neste painel. Execute primeiro uma validação.",
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

        try:
            if self.current_page_key in ("orders", "sales"):
                self.export_orders_to_excel(file_path, self.current_page_key)
            else:
                self.export_table_to_excel(file_path)
        except Exception as error:
            self.show_export_error(error)
            return

        QMessageBox.information(self, "Exportar Excel", "Ficheiro Excel criado com sucesso.")

    def show_export_error(self, error: Exception):
        detail = str(error).strip()
        message = "Não foi possível exportar o ficheiro Excel."
        if detail:
            message = f"{message}\n\nDetalhe técnico: {detail}"

        QMessageBox.critical(self, "Exportar Excel", message)

    def show_page(self, page_key: str):
        """Troca o painel visível e atualiza título/subtítulo da área de conteúdo."""
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
            "settings": {
                "index": 4,
                "title": "Definições",
                "subtitle": "Configuração de ligação carregada pelo kit de validação.",
            },
            "logs": {
                "index": 5,
                "title": "Logs",
                "subtitle": "Consola com o registo cronológico de todas as validações executadas nesta sessão.",
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

        if page_key == "settings":
            self._refresh_settings_panel()

        if page_key in ("orders", "sales"):
            self.ensure_salesman_filter_options(page_key)

    def ensure_salesman_filter_options(self, page_key: str):
        """Carrega a lista de vendedores dos documentos integrados para os filtros."""
        combo = self.filter_widgets.get(page_key, {}).get("salesman")
        if combo is None or combo.property("loaded"):
            return

        try:
            db_sage, _ = self.ensure_databases()
            salesmen = get_erp_salesmen(db_sage)
        except Exception as error:
            self.append_global_log(
                f"Não foi possível carregar vendedores para o filtro: {error}",
                level="warning",
            )
            return

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Todos os vendedores", None)
        for salesman in salesmen:
            name = salesman['salesman_name']
            code = salesman['salesman_id']
            label = f"{code} - {name}" if name else code
            combo.addItem(label, code)
        combo.setProperty("loaded", True)
        combo.blockSignals(False)

    def get_panel_filters(self, page_key: str) -> dict[str, Any] | None:
        widgets = self.filter_widgets.get(page_key, {})
        start_widget = widgets.get("start_date")
        end_widget = widgets.get("end_date")

        if start_widget is None or end_widget is None:
            return {}

        start_date = start_widget.date()
        end_date = end_widget.date()

        if start_date > end_date:
            QMessageBox.warning(
                self,
                "Filtros inválidos",
                "A data de início não pode ser posterior à data de fim.",
            )
            return None

        filters = {
            "start_date": start_date.toString("yyyy-MM-dd"),
            "end_date": end_date.toString("yyyy-MM-dd"),
        }

        salesman_combo = widgets.get("salesman")
        if salesman_combo is not None:
            filters["salesman_id"] = salesman_combo.currentData()

        return filters

    def _refresh_settings_panel(self):
        """Lê config (se já carregada) e atualiza os labels de Definições."""
        if self.config is None:
            try:
                self.config = load_config()
            except Exception:
                pass

        if self.config:
            sql = self.config.get("sql_server", {})
            dbs = self.config.get("databases", {})
            server = sql.get("server", "—")
            sage = dbs.get("sage50", "—")
            mss = dbs.get("mss", "—")
        else:
            server = "—"
            sage = "—"
            mss = "—"

        self.settings_sql_label.setText(f"Servidor SQL: {server}")
        self.settings_erp_label.setText(f"Base ERP (Sage 50): {sage}")
        self.settings_mss_label.setText(f"Base MSS: {mss}")

        if self.expenses_result is None:
            self.settings_expenses_card.set_status("Pendente", "Clique para verificar.")
        else:
            self._apply_expenses_result()

    def run_environment_checks(self):
        self.show_page("environment")
        self.run_task(
            "verificações de ambiente",
            self.collect_environment_checks,
            self.render_environment_results,
            "environment",
            [
                "myteam", "webapi_service", "webapi_status", "apikeys",
                "optimizer", "sql", "world", "maps", "currency", "historical",
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
        self.show_page("environment")
        self.run_task(
            title,
            task,
            self.render_environment_results,
            "environment",
            [card_key],
        )

    def run_expenses_version_check(self):
        self.show_page("settings")
        self.run_task(
            "versão de despesas",
            self.collect_expenses_version_check,
            self.render_expenses_version_result,
            "settings",
            ["expenses_version"],
        )

    def collect_expenses_version_check(self):
        _, db_mss = self.ensure_databases()
        return {"expenses_version": get_expenses_version_info(db_mss)}

    def render_expenses_version_result(self, result):
        self.expenses_result = result["expenses_version"]
        self._apply_expenses_result()
        self.append_global_log(f"Despesas → {self.expenses_result['version']} ({self.expenses_result['table']}, {self.expenses_result['total']} registos)", level="ok")

    def _apply_expenses_result(self):
        if self.expenses_result is None:
            return
        exp = self.expenses_result
        registos = (
            f"Não existem registos na tabela {exp['table']}."
            if exp["total"] == 0
            else f"Consulte a tabela {exp['table']} para visualizar registos."
        )
        self.settings_expenses_card.set_status(
            exp["version"],
            f"O cliente usa Despesas {exp['version']}. {registos}"
        )

    def run_order_checks(self):
        self.show_page("orders")
        filters = self.get_panel_filters("orders")
        if filters is None:
            return

        self.run_task(
            "documentos de encomendas",
            lambda: {"orders": self.collect_order_checks(filters)},
            self.render_orders_results,
            "orders",
            ["orders"],
        )

    def run_sales_checks(self):
        self.show_page("sales")
        filters = self.get_panel_filters("sales")
        if filters is None:
            return

        self.run_task(
            "vendas",
            lambda: {"sales": self.collect_sales_checks(filters)},
            self.render_sales_results,
            "sales",
            ["sales"],
        )

    def run_salesmen_checks(self):
        self.show_page("salesmen")
        self.run_task(
            "vendedores",
            lambda: {"salesmen": self.collect_salesmen_checks()},
            self.render_salesmen_results,
            "salesmen",
            ["salesmen"],
        )

    def run_task(
        self,
        title: str,
        task: Callable[[], Any],
        on_success: Callable[[Any], None],
        page_key: str,
        loading_card_keys: list[str],
    ):
        if self.thread is not None:
            QMessageBox.information(self, "Validação em curso", "Aguarde a validação atual terminar.")
            return

        self.current_page_key = page_key
        self.current_success_callback = on_success
        self.loading_card_keys = loading_card_keys
        self.set_busy(True, f"A validar {title}...", page_key)

        self.append_global_log(f"A iniciar validação: {title}", level="info")

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
        try:
            if self.current_success_callback is not None:
                self.current_success_callback(result)
        except Exception as error:
            self.append_global_log(f"Erro ao renderizar resultados: {error}", level="error")
            QMessageBox.critical(self, "Erro de Renderização", f"Ocorreu um erro ao apresentar os resultados:\n\n{error}")
        finally:
            self.set_busy(False, page_key=self.current_page_key)

    @Slot(str)
    def fail_task(self, message: str):
        try:
            self.clear_results(self.current_page_key)
            self.set_summary(self.current_page_key, "Ocorreu um erro durante a validação.")

            for key in self.loading_card_keys:
                self.cards[key].set_status("Erro", "Ver log de execução.")

            self.add_detail(self.current_page_key, f"Erro: {message}")
            self.append_global_log(f"ERRO: {message}", level="error")
            QMessageBox.critical(self, "Erro", message)
        finally:
            self.set_busy(False, page_key=self.current_page_key)

    def cleanup_thread(self):
        self.worker = None
        self.thread = None
        self.current_success_callback = None
        self.loading_card_keys = []

    def set_busy(self, busy: bool, message: str = "", page_key: str | None = None):
        page_key = page_key or self.current_page_key
        widgets = self.result_widgets.get(page_key)

        if widgets:
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

    def collect_environment_checks(self):
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

    def collect_sql_only(self):
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

    def collect_order_checks(self, filters: dict[str, Any] | None = None):
        db_sage, db_mss = self.ensure_databases()
        return validate_order_documents(db_sage, db_mss, **(filters or {}))

    def collect_sales_checks(self, filters: dict[str, Any] | None = None):
        db_sage, db_mss = self.ensure_databases()
        return validate_sales_documents(db_sage, db_mss, **(filters or {}))

    def collect_salesmen_checks(self):
        db_sage, _ = self.ensure_databases()
        result = validate_salesmen(db_sage)
        result["mapping"] = get_salesmen_mapping(db_sage)
        return result

    def ensure_config(self):
        if self.config is None:
            self.config = load_config()
        return self.config

    def ensure_databases(self):
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

    def render_environment_results(self, result: dict[str, Any]):
        page_key = "environment"
        self.clear_results(page_key)
        self.append_global_log("── Verificações de ambiente ──", level="section")

        if "myteam" in result:
            myteam = result["myteam"]
            self.cards["myteam"].set_status(
                myteam["status"],
                f"Serviço: {myteam['service_name'] or 'não encontrado'}",
            )
            self.add_table_row(page_key, "Ambiente", "MyTeam", myteam["status"], myteam["service_name"] or "")
            level = "ok" if myteam["status"] == "Running" else "warning"
            self.append_global_log(f"MyTeam → {myteam['status']} ({myteam['service_name'] or 'não encontrado'})", level=level)
            if myteam["status"] != "Running":
                self.add_detail(page_key, f"O serviço MyTeam não está em execução. Serviço detetado: {myteam['service_name'] or 'não encontrado'}.")

        if "webapi_service" in result:
            webapi = result["webapi_service"]
            self.cards["webapi_service"].set_status(webapi["status"], f"Serviço: {webapi['service_name']}")
            self.add_table_row(page_key, "Ambiente", "WebAPI", webapi["status"], webapi["service_name"])
            level = "ok" if webapi["status"] == "Running" else "warning"
            self.append_global_log(f"WebAPI → {webapi['status']} ({webapi['service_name']})", level=level)
            if webapi["status"] != "Running":
                self.add_detail(page_key, f"O serviço WebAPI não está em execução. Serviço detetado: {webapi['service_name']}.")

        if "webapi_status" in result:
            status = result["webapi_status"]
            card_status = "Online" if status["online"] else "Offline"
            detail = self.build_webapi_status_detail(status)
            card_detail = detail if status["online"] else "Ver log de execução."
            self.cards["webapi_status"].set_status(card_status, card_detail)
            self.add_table_row(page_key, "Ambiente", "Status WebAPI", card_status, card_detail)
            level = "ok" if status["online"] else "error"
            self.append_global_log(f"Status WebAPI → {card_status} | {detail}", level=level)
            if not status["online"]:
                self.add_detail(page_key, status.get("message") or "O endpoint Status WebAPI respondeu como offline.")

        if "apikeys" in result:
            apikeys = result["apikeys"]
            apikey_detail = "Chaves da WebAPI consistentes." if apikeys["status"] == "OK" else "Ver log de execução."
            self.cards["apikeys"].set_status(apikeys["status"], apikey_detail)
            self.add_table_row(page_key, "Ambiente", "API Keys da WebAPI", apikeys["status"], apikey_detail)
            level = "ok" if apikeys["status"] == "OK" else "warning"
            self.append_global_log(f"API Keys WebAPI → {apikeys['status']}", level=level)
            if apikeys["status"] != "OK":
                self.add_detail(page_key, "As API Keys da WebAPI estão diferentes entre MSSBO.INI e appsettings.json.")

        if "optimizer" in result:
            optimizer = result["optimizer"]
            self.cards["optimizer"].set_status(optimizer["status"], f"Porta {optimizer['port']}")
            self.add_table_row(page_key, "Ambiente", "Otimizador", optimizer["status"], f"Porta {optimizer['port']}")
            level = "ok" if optimizer["status"] == "OK" else "warning"
            self.append_global_log(f"Otimizador → {optimizer['status']} (porta {optimizer['port']})", level=level)
            if optimizer["status"] != "OK":
                self.add_detail(page_key, f"A porta {optimizer['port']} do otimizador está {optimizer['status']}.")

        if "sql" in result:
            sql = result["sql"]
            self.cards["sql"].set_status(sql["status"], f"Servidor: {sql['server']}")
            self.add_table_row(page_key, "SQL", "Ligação", sql["status"], sql["server"])
            level = "ok" if sql["status"] == "OK" else "error"
            self.append_global_log(f"SQL Server → {sql['status']} ({sql['server']})", level=level)

        if "world" in result:
            world = result["world"]
            detail = self.build_world_detail(world)
            card_detail = "Base de dados encontrada." if world["exists"] else "Ver log de execução."
            self.cards["world"].set_status(world["status"], card_detail)
            self.add_table_row(
                page_key, "SQL", world["database_name"], world["status"],
                detail if world["exists"] else "Ver log de execução.",
            )
            level = "ok" if world["exists"] else "error"
            self.append_global_log(f"World Geometries → {world['status']} | {detail}", level=level)
            if not world["exists"]:
                self.add_detail(page_key, detail)

        if "maps" in result:
            maps = result["maps"]
            detail = f"Parâmetros encontrados: {len(maps['parameters'])}"
            card_detail = detail if maps["status"] == "OK" else "Ver log de execução."
            self.cards["maps"].set_status(maps["status"], card_detail)
            self.add_table_row(
                page_key, "MSS", "Google Maps API", maps["status"],
                ", ".join(maps["parameters"]) if maps["status"] == "OK" else "Ver log de execução.",
            )
            level = "ok" if maps["status"] == "OK" else "warning"
            self.append_global_log(f"Google Maps API → {maps['status']} | {detail}", level=level)
            if maps["status"] != "OK":
                self.add_detail(page_key, "A configuração da Google Maps API não foi encontrada no MSS.")

        if "currency" in result:
            currency = result["currency"]
            detail = "Todos os terminais têm símbolo." if not currency["missing_terminals"] else "Terminais em falta: " + ", ".join(currency["missing_terminals"]) + " | Aceda ao BackOffice -> CONFIGURAÇÃO DO TERMINAL -> CONFIGURAÇÃO AVANÇADA -> DOCUMENTOS -> VISUALIZAÇÃO -> SÍMBOLO DA MOEDA."
            card_detail = detail if currency["status"] == "OK" else "Ver log de execução."
            self.cards["currency"].set_status(currency["status"], card_detail)
            self.add_table_row(
                page_key, "MSS", "Moeda", currency["status"],
                detail if currency["status"] == "OK" else "Ver log de execução.",
            )
            level = "ok" if currency["status"] == "OK" else "warning"
            self.append_global_log(f"Moeda → {currency['status']} | {detail}", level=level)
            if currency["missing_terminals"]:
                self.add_detail(page_key, detail)

        if "historical" in result:
            historical = result["historical"]
            if historical["start_date_formatted"]:
                detail = f"Doc. mais antigo sincronizado: {historical['start_date_formatted']}"
                card_detail = detail
            else:
                detail = "Não foi encontrado nenhum documento sincronizado no MSS para determinar a data mais antiga."
                card_detail = "Sem dados históricos."
            self.cards["historical"].set_status(historical["status"], card_detail)
            self.add_table_row(page_key, "MSS", "Histórico", historical["status"], detail)
            level = "ok" if historical["status"] == "OK" else "warning"
            self.append_global_log(f"Histórico → {historical['status']} | {detail}", level=level)

        self.fit_table_to_contents(page_key)
        self.add_no_issues_message(page_key)
        self.set_summary(page_key, "Verificação de ambiente concluída.")
        self.mark_updated(page_key)
        self.append_global_log("Verificação de ambiente concluída.", level="info")

    def render_orders_results(self, result: dict[str, Any]):
        page_key = "orders"
        self.clear_results(page_key)
        self.append_global_log("── Documentos de encomendas ──", level="section")

        orders = result["orders"]
        status = "OK" if orders["success"] else "Warning"
        total_issues = orders["total_issues"]
        detail = "Sem divergências." if orders["success"] else f"{total_issues} divergência(s) encontrada(s)."

        self.cards["orders"].set_status(status, detail)

        bo_docs = sorted(orders.get("documents_configured_bo", []))
        erp_order_docs = sorted(orders.get("documents_erp", []))
        integrated_docs = orders.get("documents_integrated", [])
        sales_docs = sorted(orders.get("documents_sales", []))

        widgets = self.result_widgets[page_key]
        widgets["stat_bo"].set_value(len(bo_docs))
        widgets["stat_erp"].set_value(len(erp_order_docs))
        widgets["stat_integrated"].set_value(len(integrated_docs))
        widgets["stat_issues"].set_value(total_issues)
        widgets["stat_issues"].set_state("error" if total_issues else "ok")

        erp_values = orders.get("erp_values", {})

        self.set_doc_list(widgets["bo_list"], bo_docs)
        self.set_doc_list(widgets["erp_list"], erp_order_docs)
        self.populate_integrated_table(widgets["integrated_table"], integrated_docs, erp_values)
        self.set_doc_list(widgets["sales_list"], sales_docs)

        if orders["success"]:
            widgets["issues"].setPlainText("Nenhuma divergência encontrada.")
        else:
            issue_lines = [f"⚠ {issue['message']}" for issue in orders["issues"]]
            widgets["issues"].setPlainText("\n".join(issue_lines))

        widgets["has_results"] = True

        level = "ok" if orders["success"] else "warning"
        self.append_global_log(f"Encomendas → BackOffice: {len(bo_docs)} | ERP: {len(erp_order_docs)} | Integrados: {len(integrated_docs)} | Divergências: {total_issues}", level=level)
        if not orders["success"]:
            for issue in orders["issues"]:
                self.append_global_log(f"  ⚠ {issue['message']}", level="warning")

        summary_text = (
            "Validação de documentos de encomendas concluída sem divergências."
            if orders["success"]
            else f"Validação concluída com {total_issues} divergência(s). Consulte a secção 5 para o detalhe."
        )
        self.set_summary(page_key, summary_text)
        self.mark_updated(page_key)
        self.append_global_log("Validação de encomendas concluída.", level="info")

    def render_sales_results(self, result: dict[str, Any]):
        page_key = "sales"
        self.clear_results(page_key)
        self.append_global_log("── Vendas ──", level="section")

        sales = result["sales"]
        status = "OK" if sales["success"] else "Warning"
        total_issues = sales["total_issues"]
        detail = "Sem divergências." if sales["success"] else f"{total_issues} divergência(s) encontrada(s)."

        self.cards["sales"].set_status(status, detail)

        bo_docs = sorted(sales.get("documents_configured_bo", []))
        erp_docs = sorted(sales.get("documents_erp", []))
        integrated_docs = sales.get("documents_integrated", [])
        sales_docs = sorted(sales.get("documents_sales", []))

        widgets = self.result_widgets[page_key]
        widgets["stat_bo"].set_value(len(bo_docs))
        widgets["stat_erp"].set_value(len(erp_docs))
        widgets["stat_integrated"].set_value(len(integrated_docs))
        widgets["stat_issues"].set_value(total_issues)
        widgets["stat_issues"].set_state("error" if total_issues else "ok")

        self.set_doc_list(widgets["bo_list"], bo_docs)
        erp_values = sales.get("erp_values", {})

        self.set_doc_list(widgets["erp_list"], erp_docs)
        self.populate_integrated_table(widgets["integrated_table"], integrated_docs, erp_values)
        self.set_doc_list(widgets["sales_list"], sales_docs)

        if sales["success"]:
            widgets["issues"].setPlainText("Nenhuma divergência encontrada.")
        else:
            issue_lines = [f"⚠ {issue['message']}" for issue in sales["issues"]]
            widgets["issues"].setPlainText("\n".join(issue_lines))

        widgets["has_results"] = True

        level = "ok" if sales["success"] else "warning"
        self.append_global_log(f"Vendas → BackOffice: {len(bo_docs)} | ERP: {len(erp_docs)} | Integrados: {len(integrated_docs)} | Divergências: {total_issues}", level=level)
        if not sales["success"]:
            for issue in sales["issues"]:
                self.append_global_log(f"  ⚠ {issue['message']}", level="warning")

        summary_text = (
            "Validação de vendas concluída sem divergências."
            if sales["success"]
            else f"Validação de vendas concluída com {total_issues} divergência(s). Consulte a secção 5 para o detalhe."
        )
        self.set_summary(page_key, summary_text)
        self.mark_updated(page_key)
        self.append_global_log("Validação de vendas concluída.", level="info")

    def render_salesmen_results(self, result: dict[str, Any]):
        page_key = "salesmen"
        self.clear_results(page_key)
        self.append_global_log("── Vendedores ──", level="section")

        salesmen = result["salesmen"]
        mapping = self.filter_mss_salesmen_mapping(salesmen.get("mapping", []))
        total_issues = salesmen["total_issues"]
        status = "OK" if salesmen["success"] else "Warning"
        detail = f"{len(mapping)} utilizadores MSS analisados." if salesmen["success"] else "Ver log de execução."

        self.cards["salesmen"].set_status(status, detail)

        for row in mapping:
            self.add_salesman_mapping_row(page_key, row)

        for issue in salesmen["issues"]:
            self.add_detail(page_key, issue["message"])
            self.append_global_log(f"  ⚠ {issue['message']}", level="warning")

        level = "ok" if salesmen["success"] else "warning"
        self.append_global_log(f"Vendedores → {status} | {len(mapping)} utilizadores MSS | {total_issues} divergência(s)", level=level)

        self.fit_table_to_contents(page_key)
        self.add_no_issues_message(page_key)

        summary_text = (
            f"Validação de vendedores concluída com {total_issues} divergência(s). "
            f"Foram analisados {len(mapping)} utilizadores MSS. Consulte o log de execução para o detalhe."
            if total_issues
            else f"Validação de vendedores concluída sem divergências. Foram analisados {len(mapping)} utilizadores MSS."
        )
        self.set_summary(page_key, summary_text)
        self.mark_updated(page_key)
        self.append_global_log("Validação de vendedores concluída.", level="info")

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
        try:
            numeric_value = int(round(float(value)))
        except (TypeError, ValueError):
            return "-"
        return f"{numeric_value:,}".replace(",", " ")

    def set_doc_list(self, widget: QTextEdit, documents: list[str]):
        widget.setPlainText("\n".join(documents) if documents else "Nenhum documento encontrado.")

    def populate_integrated_table(self, table: QTableWidget, integrated_docs: list[dict[str, Any]], erp_values: dict[str, dict] | None = None):
        table.setRowCount(0)
        for item in integrated_docs:
            row = table.rowCount()
            table.insertRow(row)
            
            nome = item.get("nome_vendedor") or ""
            codigo = item.get("codigo_vendedor") or ""
            doc = item.get("documento") or ""
            mss_qty = item.get("total_documentos") or 0
            mss_val = item.get("total_liquido") or 0.0

            erp_key = (doc, codigo)
            erp_data = (erp_values or {}).get(erp_key, {})
            erp_qty = erp_data.get("qtd") or 0
            erp_val = float(erp_data.get("total") or 0)
            diff = float(mss_val) - erp_val
            
            table.setItem(row, 0, QTableWidgetItem(str(nome)))
            table.setItem(row, 1, QTableWidgetItem(str(codigo)))
            table.setItem(row, 2, QTableWidgetItem(str(doc)))
            table.setItem(row, 3, QTableWidgetItem(str(mss_qty)))
            table.setItem(row, 4, QTableWidgetItem(self.format_currency(mss_val)))
            table.setItem(row, 5, QTableWidgetItem(str(erp_qty)))
            table.setItem(row, 6, QTableWidgetItem(self.format_currency(erp_val)))
            diff_item = QTableWidgetItem(self.format_currency(diff))
            diff_item.setForeground(QColor("#d32f2f") if diff != 0 else QColor("#388e3c"))
            table.setItem(row, 7, diff_item)
            
        table.resizeRowsToContents()
        header_height = table.horizontalHeader().height()
        rows_height = sum(table.rowHeight(r) for r in range(table.rowCount()))
        frame = table.frameWidth() * 2
        total_height = max(header_height + rows_height + frame + 6, header_height + 50)
        table.setFixedHeight(total_height)

    def clear_results(self, page_key: str):
        widgets = self.result_widgets.get(page_key)
        if not widgets:
            return

        if page_key in ("orders", "sales"):
            widgets["stat_bo"].set_value(0)
            widgets["stat_erp"].set_value(0)
            widgets["stat_integrated"].set_value(0)
            widgets["stat_issues"].set_value(0)
            widgets["stat_issues"].set_state(None)
            widgets["bo_list"].clear()
            widgets["erp_list"].clear()
            widgets["sales_list"].clear()
            widgets["integrated_table"].setRowCount(0)
            widgets["integrated_table"].setFixedHeight(96)
            widgets["issues"].clear()
            widgets["has_results"] = False
            return

        widgets["table"].setRowCount(0)
        widgets["log"].clear()
        widgets["table"].setFixedHeight(96)

    def fit_table_to_contents(self, page_key: str):
        table = self.result_widgets[page_key]["table"]
        table.resizeRowsToContents()
        header_height = table.horizontalHeader().height()
        rows_height = sum(table.rowHeight(r) for r in range(table.rowCount()))
        frame = table.frameWidth() * 2
        total_height = max(header_height + rows_height + frame + 6, header_height + 50)
        table.setFixedHeight(total_height)

    def set_summary(self, page_key: str, text: str):
        widgets = self.result_widgets.get(page_key)
        if widgets:
            widgets["summary"].setText(text)

    def mark_updated(self, page_key: str):
        widgets = self.result_widgets.get(page_key)
        if widgets:
            label = widgets.get("updated_label")
            if label is not None:
                label.setText(f"Última validação: {datetime.now().strftime('%H:%M:%S')}")

    def add_detail(self, page_key: str, text: str):
        widgets = self.result_widgets.get(page_key)
        if not widgets:
            return
        if page_key in ("orders", "sales"):
            current = widgets["issues"].toPlainText().strip()
            if current:
                widgets["issues"].append(f"\n{text}")
            else:
                widgets["issues"].setPlainText(text)
            return
        widgets["log"].append(text)

    def add_no_issues_message(self, page_key: str):
        if page_key in ("orders", "sales"):
            return
        widgets = self.result_widgets.get(page_key)
        if widgets and not widgets["log"].toPlainText().strip():
            self.add_detail(page_key, "Nenhuma divergência encontrada.")

    def add_table_row(self, page_key: str, area: str, item: str, status: str, detail: str):
        self.add_table_values(
            page_key,
            [area, item, str(status), detail],
            status_column=2,
            status_value=str(status),
        )

    def filter_mss_salesmen_mapping(self, mapping: list[dict[str, str]]) -> list[dict[str, str]]:
        return [
            row for row in mapping
            if row["origem"].upper() == "MSS"
            and row["codigo_vendedor"].strip().upper() != "ADMIN"
        ]

    def add_salesman_mapping_row(self, page_key: str, row: dict[str, str]):
        self.add_table_values(
            page_key,
            [row["origem"], row["codigo_vendedor"], row["nome_vendedor"], row["codigo_vendedor_erp"]],
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

    def status_text_color(self, status: str):
        normalized = status.strip().lower()
        if normalized in {"ok", "running", "true", "online"}:
            return QColor("#1a7f37")
        if normalized in {"warning", "missing", "different", "closed", "no data", "por fazer",
                          "error", "stopped", "false", "offline"}:
            return QColor("#c62828")
        return QColor("#20242a")

    _LOG_COLORS = {
        "timestamp": "#6A9955",
        "section": "#569CD6",
        "info": "#D4D4D4",
        "ok": "#4EC9B0",
        "warning": "#CE9178",
        "error": "#F44747",
    }

    def append_global_log(self, text: str, level: str = "info"):
        """Escreve uma linha no terminal global do painel Logs."""
        if self.global_log_widget is None:
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        cursor = self.global_log_widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        def write(txt: str, color: str, bold: bool = False):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(700)
            cursor.setCharFormat(fmt)
            cursor.insertText(txt)

        write(f"[{timestamp}] ", self._LOG_COLORS["timestamp"])

        if level == "section":
            write(text, self._LOG_COLORS["section"], bold=True)
        else:
            write(text, self._LOG_COLORS.get(level, self._LOG_COLORS["info"]))

        plain_fmt = QTextCharFormat()
        plain_fmt.setForeground(QColor(self._LOG_COLORS["info"]))
        cursor.setCharFormat(plain_fmt)
        cursor.insertText("\n")

        self.global_log_widget.setTextCursor(cursor)
        self.global_log_widget.ensureCursorVisible()

    def clear_global_log(self):
        """Limpa o terminal global de logs."""
        if self.global_log_widget is not None:
            self.global_log_widget.clear()

    def export_logs_to_txt(self):
        if self.global_log_widget is None:
            return

        log_text = self.global_log_widget.toPlainText().strip()
        if not log_text:
            QMessageBox.information(
                self,
                "Exportar TXT",
                "Ainda não existem logs para exportar. Execute primeiro uma validação.",
            )
            return

        default_name = f"logs_validacao_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar logs em TXT",
            default_name,
            "Texto (*.txt)",
        )

        if not file_path:
            return

        if not file_path.lower().endswith(".txt"):
            file_path += ".txt"

        try:
            Path(file_path).write_text(log_text + "\n", encoding="utf-8")
        except Exception as error:
            detail = str(error).strip()
            message = "Não foi possível exportar o ficheiro TXT."
            if detail:
                message = f"{message}\n\nDetalhe técnico: {detail}"
            QMessageBox.critical(self, "Exportar TXT", message)
            return

        QMessageBox.information(self, "Exportar TXT", "Ficheiro TXT criado com sucesso.")

    def export_orders_to_excel(self, file_path: str, page_key: str = "orders"):
        widgets = self.result_widgets[page_key]
        erp_section_title = (
            "2. Documentos de venda no ERP"
            if page_key == "sales"
            else "2. Documentos de encomenda no ERP"
        )
        rows = [
            ["BackOffice", widgets["stat_bo"].value_label.text()],
            ["ERP", widgets["stat_erp"].value_label.text()],
            ["Integrados", widgets["stat_integrated"].value_label.text()],
            ["Divergências", widgets["stat_issues"].value_label.text()],
            [],
            ["1. Documentos configurados no BackOffice"],
            *[[doc] for doc in widgets["bo_list"].toPlainText().splitlines() if doc.strip()],
            [],
            [erp_section_title],
            *[[doc] for doc in widgets["erp_list"].toPlainText().splitlines() if doc.strip()],
            [],
            [],
            ["3. Documentos integrados no MyTeam"],
            ["Vendedor", "Código Vendedor", "Documento", "Qt. MSS", "Total Líq. MSS", "Qt. ERP", "Total Líq. ERP", "Diferença"],
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
        sheet_rows = []
        for row_index, row in enumerate(rows, start=1):
            cells = []
            for column_index, value in enumerate(row, start=1):
                cell = self.excel_cell_name(row_index, column_index)
                safe_value = escape(self.clean_excel_text(value))
                cells.append(f'<c r="{cell}" t="inlineStr"><is><t>{safe_value}</t></is></c>')
            sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

        sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {"".join(sheet_rows)}
  </sheetData>
</worksheet>"""

        with ZipFile(file_path, "w", ZIP_DEFLATED) as workbook:
            workbook.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""")
            workbook.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""")
            workbook.writestr("xl/workbook.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Resumo" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""")
            workbook.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""")
            workbook.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    def clean_excel_text(self, value: Any) -> str:
        text = "" if value is None else str(value)
        return "".join(
            char
            for char in text
            if char in "\t\n\r" or ord(char) >= 32
        )

    def excel_cell_name(self, row: int, column: int):
        name = ""
        while column:
            column, remainder = divmod(column - 1, 26)
            name = chr(65 + remainder) + name
        return f"{name}{row}"

    def apply_styles(self):
        self.setStyleSheet(
            """
            QWidget {
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 13px;
                color: #20242a;
            }

            #sidebar {
                background: #111a23;
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
                font-size: 21px;
                font-weight: 700;
            }

            #appSubtitle {
                color: #7d8a98;
                font-size: 12px;
            }

            #sidebarHint {
                color: #6b7785;
                font-size: 11px;
            }

            /* Rótulos de secção na sidebar (VALIDAÇÕES / SISTEMA) */
            #sidebarSectionLabel {
                color: #4a5a6a;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
                padding: 2px 0 0 2px;
            }

            QPushButton {
                min-height: 38px;
                padding: 8px 14px;
                border-radius: 8px;
                border: 1px solid transparent;
                background: rgba(255, 255, 255, 0.05);
                color: #cbd5e0;
                text-align: left;
                font-weight: 600;
            }

            QPushButton:hover {
                background: rgba(255, 255, 255, 0.10);
                color: white;
            }

            QPushButton[active="true"] {
                color: white;
                background: #21866f;
                border: none;
                border-left: 4px solid #4fd8b8;
                font-weight: 700;
                padding-left: 11px;
            }

            QPushButton[primary="true"] {
                color: white;
                border: 2px solid #0d2b22;
                background: #21866f;
                font-weight: 700;
                font-size: 14px;
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
                text-align: center;
            }

            QPushButton[export="true"]:hover {
                background: #cceedd;
            }

            QPushButton:disabled {
                color: #89939f;
                background: #e7ebef;
                border: 1px solid #d7dde3;
            }

            QMessageBox {
                background: #f8fafc;
            }

            QMessageBox QLabel {
                color: #11161c;
                background: transparent;
                font-size: 13px;
                font-weight: 500;
            }

            QMessageBox QPushButton {
                min-width: 70px;
                min-height: 30px;
                padding: 6px 14px;
                border-radius: 6px;
                border: 1px solid #176b58;
                background: #21866f;
                color: white;
                text-align: center;
                font-weight: 700;
            }

            QMessageBox QPushButton:hover {
                background: #1b6f5c;
            }

            #clearLogsButton,
            #exportLogsButton {
                background: #0e639c;
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: 700;
                min-height: 32px;
                padding: 6px 16px;
                text-align: center;
            }

            #clearLogsButton:hover,
            #exportLogsButton:hover {
                background: #1177bb;
            }

            #clearLogsButton:pressed,
            #exportLogsButton:pressed {
                background: #0b4f7e;
            }

            #headerDivider {
                background: rgba(33, 134, 111, 0.30);
                border: none;
                border-radius: 1px;
            }

            #pageTitle {
                font-size: 25px;
                font-weight: 700;
                color: #11161c;
            }

            #pageSubtitle {
                color: #59636f;
            }

            #summaryLabel {
                color: #23303b;
                background: #eaf5ef;
                border: 1px solid #cce7da;
                border-radius: 8px;
                padding: 9px 12px;
                font-weight: 600;
            }

            #updatedLabel {
                color: #6f7d8a;
                font-size: 11px;
                font-style: italic;
                padding-right: 4px;
            }

            #sectionLabel {
                font-weight: 700;
                color: #20242a;
                margin-top: 4px;
            }

            QGroupBox {
                border: 1px solid #d9e1e8;
                border-radius: 10px;
                margin-top: 14px;
                font-weight: 700;
                font-size: 13px;
                color: #1c2733;
                background: #ffffff;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
                color: #135a48;
            }

            #resultsGroup {
                border: 1px solid #cbd8e4;
                background: #ffffff;
            }

            #resultsGroup::title {
                color: #0f1720;
                font-size: 15px;
            }

            /* ── Definições ─────────────────────────────────────────────── */

            #settingsGroup {
                border: 1px solid #cbd8e4;
                background: #ffffff;
            }

            #settingsGroup::title {
                color: #0f1720;
                font-size: 15px;
            }

            #settingsSubtitle {
                color: #21866f;
                font-size: 12px;
                font-style: italic;
            }

            #settingsInfoFrame {
                background: #0d1b2a;
                border: 1px solid #1e3448;
                border-radius: 8px;
            }

            #settingsInfoLine {
                color: #c5d8e8;
                font-family: Consolas, "Courier New", monospace;
                font-size: 13px;
                padding: 5px 0;
                background: transparent;
            }

            #reconfigureBtn {
                color: #10251f;
                border: 1px solid #9ccbb9;
                background: #dff5ea;
                font-weight: 700;
                text-align: center;
                border-radius: 8px;
                min-height: 44px;
            }

            #reconfigureBtn:hover {
                background: #cceedd;
            }

            /* ── Logs ───────────────────────────────────────────────────── */

            #logsGroup {
                border: 1px solid #cbd8e4;
                background: #ffffff;
            }

            #logsGroup::title {
                color: #0f1720;
                font-size: 15px;
            }

            #logsSubtitle {
                color: #59636f;
                font-size: 12px;
                font-style: italic;
            }

            #logTerminal {
                background: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #333333;
                border-radius: 8px;
                selection-background-color: #264f78;
                selection-color: #d4d4d4;
            }

            /* ── Cartões de estado ──────────────────────────────────────── */

            #statusCard {
                border: 1px solid #d9e1e8;
                border-left: 4px solid #c9d2dc;
                border-radius: 10px;
                background: white;
            }

            #statusCard:hover {
                border: 1px solid #21866f;
                border-left: 4px solid #21866f;
                background: #fbfefd;
            }

            #statusCard[cardState="ok"] {
                border-left: 4px solid #1a7f37;
            }

            #statusCard[cardState="warning"] {
                border-left: 4px solid #b8860b;
            }

            #statusCard[cardState="error"] {
                border-left: 4px solid #c62828;
            }

            #statusCard[cardState="loading"] {
                border-left: 4px solid #1f6fb2;
            }

            #countStatCard {
                border: 1px solid #cbd8e4;
                border-radius: 10px;
                background: #ffffff;
                min-width: 120px;
            }

            #countStatTitle {
                color: #59636f;
                font-weight: 600;
                font-size: 12px;
                text-transform: uppercase;
            }

            #countStatValue {
                color: #0f1720;
                font-size: 30px;
                font-weight: 700;
            }

            #countStatValue[state="ok"] {
                color: #1a7f37;
            }

            #countStatValue[state="error"] {
                color: #c62828;
            }

            #docListBox,
            #issuesBox {
                color: #24303a;
                background: #fbfcfd;
                border: 1px solid #d9e1e8;
                border-radius: 6px;
            }

            #statusCard:disabled {
                background: #f1f4f7;
            }

            #cardTitle {
                font-weight: 700;
                color: #16202a;
            }

            #cardDetail {
                color: #59636f;
            }

            #statusPill {
                border-radius: 10px;
                padding: 5px 10px;
                font-weight: 700;
                background: #e7ebef;
                color: #39414a;
                border: 1px solid #d7dde3;
            }

            #statusPill[state="ok"] {
                background: #dff5ea;
                color: #14633f;
                border: 1px solid #b6e3cb;
            }

            #statusPill[state="warning"] {
                background: #fff2cc;
                color: #795400;
                border: 1px solid #f2dd9c;
            }

            #statusPill[state="error"] {
                background: #fde2e1;
                color: #9b1c1c;
                border: 1px solid #f3b9b7;
            }

            #statusPill[state="loading"] {
                background: #dceeff;
                color: #155a9a;
                border: 1px solid #b6d9f7;
            }

            QComboBox,
            QDateEdit {
                color: #20242a;
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 5px 32px 5px 10px;
                min-height: 28px;
            }
            
            QComboBox:hover,
            QDateEdit:hover {
                border: 1px solid #21866f;
            }
            
            QComboBox::drop-down,
            QDateEdit::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 28px;
                border-left: 1px solid #cbd5e1;
                background-color: #f8fafc;
                border-top-right-radius: 5px;
                border-bottom-right-radius: 5px;
            }
            
            QComboBox::down-arrow,
            QDateEdit::down-arrow {
                image: none;
                border: none;
                width: 0;
                height: 0;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #59636f;
            }
            
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #20242a;
                border: 1px solid #cbd5e1;
                selection-background-color: #21866f;
                selection-color: #ffffff;
            }
            
            /* Custom styling for Calendar Widget popup matching reference */
            QCalendarWidget QAbstractItemView {
                background-color: #ffffff;
                color: #20242a;
                selection-background-color: #59636f;
                selection-color: #ffffff;
                alternate-background-color: #f7fafc;
                border: none;
            }
            
            QCalendarWidget QWidget {
                alternate-background-color: #f7fafc;
                background-color: #ffffff;
                color: #20242a;
            }
            
            QCalendarWidget QNavigationBar {
                background-color: #f8fafc;
                border-bottom: 1px solid #cbd5e1;
            }
            
            QCalendarWidget QToolButton {
                color: #20242a;
                background-color: transparent;
                border: none;
                font-weight: bold;
            }
            
            QCalendarWidget QToolButton:hover {
                background-color: #cbd5e1;
            }
            
            QCalendarWidget QMenu {
                background-color: #ffffff;
                color: #20242a;
                border: 1px solid #cbd5e1;
            }
            
            QCalendarWidget QSpinBox {
                color: #20242a;
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
            }

            QTableWidget,
            QTextEdit {
                border: 1px solid #d9e1e8;
                border-radius: 8px;
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
                padding: 8px;
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
