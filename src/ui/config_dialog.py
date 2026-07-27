"""Diálogo de configuração — testa a ligação SQL antes de aceitar."""
from __future__ import annotations
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QMoveEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

import configparser
import json

from core.database import Database

class ConfigDialog(QDialog):
    """Formulário que testa a ligação SQL antes de deixar prosseguir."""

    def __init__(self, existing_config: dict | None = None):
        super().__init__()
        self.setWindowTitle("Ligação ao SQL Server — Kit de Validação")
        self.setFixedSize(580, 720)
        self.setWindowFlags(self.windowFlags() | Qt.MSWindowsFixedSizeDialogHint)
        self.setModal(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_STYLE)

        self._result: dict | None = None

        self.ini_path = (
            existing_config.get("mss_ini_path", "C:\\MIS\\MSSV5\\Backoffice\\MSSBO.INI")
            if existing_config else "C:\\MIS\\MSSV5\\Backoffice\\MSSBO.INI"
        )
        self.appsettings_path = (
            existing_config.get("mss_appsettings_path", "C:\\MIS\\MSSV5\\MSSWebAPI\\appsettings.json")
            if existing_config else "C:\\MIS\\MSSV5\\MSSWebAPI\\appsettings.json"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        title = QLabel("Ligação ao SQL Server")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "Introduza os dados de ligação ao SQL Server e clique em \"Ligar\". "
            "Só depois de uma ligação bem-sucedida poderá continuar."
        )
        subtitle.setObjectName("subtitleLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addSpacing(6)

        self.server_edit = self._add_field(layout, "Servidor SQL:")
        self.server_edit.setPlaceholderText("ex: SERVIDOR\\INSTANCIA ou IP,porta")

        self.user_edit = self._add_field(layout, "Utilizador:")
        self.user_edit.setPlaceholderText("ex: sa")

        self.password_edit = self._add_field(layout, "Password:")
        self.password_edit.setPlaceholderText("Password do SQL Server")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        # ── Seleção de ERP ──
        erp_label = QLabel("ERP:")
        erp_label.setObjectName("fieldLabel")
        layout.addWidget(erp_label)
        self.erp_combo = QComboBox()
        self.erp_combo.addItems([
            "Sage 50",
            "Primavera",
            "PHC",
            "Eticadata",
            "Sage 100",
            "ERP XD",
            "Outros",
        ])
        self.erp_combo.currentTextChanged.connect(self._on_erp_changed)
        layout.addWidget(self.erp_combo)

        self.erp_custom_label = QLabel("Nome do ERP:")
        self.erp_custom_label.setObjectName("fieldLabel")
        self.erp_custom_label.hide()
        layout.addWidget(self.erp_custom_label)
        self.erp_custom_edit = QLineEdit()
        self.erp_custom_edit.setPlaceholderText("Indique o nome do ERP")
        self.erp_custom_edit.hide()
        layout.addWidget(self.erp_custom_edit)

        self.sage_edit = self._add_field(layout, "Base ERP (Sage 50):")
        self.sage_edit.setPlaceholderText("ex: Sage50_1")

        self.mss_edit = self._add_field(layout, "Base MSS:")
        self.mss_edit.setPlaceholderText("ex: MSS")

        # ── Guardar credenciais ──
        from PySide6.QtWidgets import QCheckBox
        self.save_checkbox = QCheckBox("Guardar credenciais para o próximo login")
        self.save_checkbox.setChecked(True)
        layout.addWidget(self.save_checkbox)
        layout.addSpacing(4)

        # ── Caminho do MSSBO.INI ──
        ini_label = QLabel("Ficheiro MSSBO.INI:")
        ini_label.setObjectName("fieldLabel")
        layout.addWidget(ini_label)
        ini_row = QHBoxLayout()
        self.ini_edit = QLineEdit(self.ini_path)
        self.ini_edit.setPlaceholderText("C:\\MIS\\MSSV5\\Backoffice\\MSSBO.INI")
        ini_browse = QPushButton("Procurar...")
        ini_browse.setObjectName("browseBtn")
        ini_browse.clicked.connect(self._browse_ini)
        ini_row.addWidget(self.ini_edit, 1)
        ini_row.addWidget(ini_browse)
        layout.addLayout(ini_row)

        # ── Caminho do appsettings.json ──
        app_label = QLabel("Ficheiro appsettings.json da WebAPI:")
        app_label.setObjectName("fieldLabel")
        layout.addWidget(app_label)
        app_row = QHBoxLayout()
        self.app_edit = QLineEdit(self.appsettings_path)
        self.app_edit.setPlaceholderText("C:\\MIS\\MSSV5\\MSSWebAPI\\appsettings.json")
        app_browse = QPushButton("Procurar...")
        app_browse.setObjectName("browseBtn")
        app_browse.clicked.connect(self._browse_appsettings)
        app_row.addWidget(self.app_edit, 1)
        app_row.addWidget(app_browse)
        layout.addLayout(app_row)

        self.feedback_label = QLabel("")
        self.feedback_label.setObjectName("errorLabel")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.hide()
        layout.addWidget(self.feedback_label)

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.setSpacing(10)

        self.save_btn = QPushButton("Ligar")
        self.save_btn.setObjectName("saveBtn")
        self.save_btn.clicked.connect(self._on_save)
        buttons.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("Sair")
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)

        layout.addLayout(buttons)

        if existing_config:
            self._populate(existing_config)

    def _add_field(self, layout: QVBoxLayout, label_text: str) -> QLineEdit:
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        edit = QLineEdit()
        layout.addWidget(edit)
        return edit

    def _on_erp_changed(self, text: str):
        custom_visible = text == "Outros"
        self.erp_custom_label.setVisible(custom_visible)
        self.erp_custom_edit.setVisible(custom_visible)

    def _browse_ini(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar ficheiro MSSBO.INI",
            os.path.dirname(self.ini_edit.text()) or "C:\\MIS",
            "INI files (*.ini);;All files (*.*)"
        )
        if path:
            self.ini_edit.setText(path)

    def _browse_appsettings(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar ficheiro appsettings.json",
            os.path.dirname(self.app_edit.text()) or "C:\\MIS",
            "JSON files (*.json);;All files (*.*)"
        )
        if path:
            self.app_edit.setText(path)

    def _populate(self, cfg: dict):
        sql = cfg.get("sql_server", {})
        dbs = cfg.get("databases", {})
        if sql.get("server"):
            self.server_edit.setText(sql["server"])
        if sql.get("user"):
            self.user_edit.setText(sql["user"])
        if sql.get("password"):
            self.password_edit.setText(sql["password"])
        if dbs.get("sage50"):
            self.sage_edit.setText(dbs["sage50"])
        if dbs.get("mss"):
            self.mss_edit.setText(dbs["mss"])
        if cfg.get("mss_ini_path"):
            self.ini_edit.setText(cfg["mss_ini_path"])
        if cfg.get("mss_appsettings_path"):
            self.app_edit.setText(cfg["mss_appsettings_path"])
        if cfg.get("erp"):
            erp = cfg["erp"]
            idx = self.erp_combo.findText(erp)
            if idx >= 0:
                self.erp_combo.setCurrentIndex(idx)
            else:
                self.erp_combo.setCurrentText("Outros")
                self.erp_custom_edit.setText(erp)
        self.save_checkbox.setChecked(cfg.get("save_credentials", False))

    def _validate_ini_file(self, path: str) -> str | None:
        label = "MSSBO.INI"
        try:
            if not os.path.exists(path):
                return f"{label} — ficheiro não encontrado:\n{path}"

            config = configparser.ConfigParser()
            config.read(path, encoding="cp1252")

            if "WebApi" not in config:
                return (
                    f"{label} — não tem a secção [WebApi].\n{path}\n\n"
                    "Certifique-se de que escolheu o MSSBO.INI correto."
                )

            for key in ("apikey", "apikeylog", "apikeyinternal"):
                if key not in config["WebApi"]:
                    return (
                        f"{label} — falta a chave '{key}' em [WebApi].\n{path}\n\n"
                        "O MSSBO.INI pode estar corrompido ou incompleto."
                    )
            return None

        except configparser.Error as e:
            return f"{label} — erro ao ler o INI:\n{path}\n\n{e}"
        except PermissionError:
            return f"{label} — sem permissão para ler:\n{path}"
        except Exception as e:
            return f"{label} — erro inesperado:\n{path}\n\n{e}"

    def _validate_appsettings_file(self, path: str) -> str | None:
        label = "appsettings.json"
        try:
            if not os.path.exists(path):
                return f"{label} — ficheiro não encontrado:\n{path}"

            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            for key in ("ApiKey", "ApiKeyLog", "ApiKeyInternal"):
                if key not in data:
                    return (
                        f"{label} — falta a chave '{key}'.\n{path}\n\n"
                        "O appsettings.json pode estar incompleto."
                    )
            return None

        except json.JSONDecodeError as e:
            return f"{label} — não é um JSON válido:\n{path}\n\n{e}"
        except PermissionError:
            return f"{label} — sem permissão para ler:\n{path}"
        except Exception as e:
            return f"{label} — erro inesperado:\n{path}\n\n{e}"

    def _on_save(self):
        server = self.server_edit.text().strip()
        user = self.user_edit.text().strip()
        password = self.password_edit.text()
        sage = self.sage_edit.text().strip()
        mss = self.mss_edit.text().strip()

        if not server or not user or not password or not sage or not mss:
            self._show_error("Preencha todos os campos antes de ligar.")
            return

        self._set_busy(True)
        self.feedback_label.hide()

        try:
            db = Database(server=server, database=sage, user=user, password=password)
            db.execute("SELECT 1")

            db2 = Database(server=server, database=mss, user=user, password=password)
            db2.execute("SELECT 1")
        except Exception as exc:
            msg = str(exc).strip()
            friendly = self._friendly_error(msg, server)
            self._set_busy(False)
            self._show_error(friendly)
            return

        ini_path = self.ini_edit.text().strip()
        app_path = self.app_edit.text().strip()

        ini_error = self._validate_ini_file(ini_path)
        if ini_error:
            self._set_busy(False)
            self._show_error(ini_error)
            return

        app_error = self._validate_appsettings_file(app_path)
        if app_error:
            self._set_busy(False)
            self._show_error(app_error)
            return

        erp = self.erp_combo.currentText()
        if erp == "Outros":
            custom = self.erp_custom_edit.text().strip()
            if not custom:
                self._show_error("Indique o nome do ERP.")
                return
            erp = custom

        self._result = {
            "sql_server": {"server": server, "user": user, "password": password},
            "databases": {"sage50": sage, "mss": mss},
            "erp": erp,
            "mss_ini_path": ini_path,
            "mss_appsettings_path": app_path,
            "save_credentials": self.save_checkbox.isChecked(),
        }
        self._set_busy(False)
        self.accept()

    def _friendly_error(self, msg: str, server: str) -> str:
        msg_lower = msg.lower()
        if "login failed" in msg_lower:
            return "Falha de autenticação. Verifique o utilizador e a password."
        if "cannot open database" in msg_lower:
            return "Base de dados não encontrada. Verifique o nome da base."
        if "could not open database" in msg_lower:
            return "Base de dados não encontrada. Verifique o nome da base."
        if "network-related" in msg_lower or "could not open connection" in msg_lower:
            return f"Não foi possível contactar o servidor \"{server}\". Verifique o nome do servidor e se o SQL Server está a correr."
        if "timeout" in msg_lower:
            return f"Tempo limite excedido ao contactar \"{server}\". Verifique se o servidor está acessível."
        return "Erro ao ligar ao SQL Server."

    def _show_error(self, msg: str):
        self.feedback_label.setObjectName("errorLabel")
        self.feedback_label.setText(msg)
        self.feedback_label.show()
        self.feedback_label.style().unpolish(self.feedback_label)
        self.feedback_label.style().polish(self.feedback_label)

    def _set_busy(self, busy: bool):
        self.save_btn.setEnabled(not busy)
        self.save_btn.setText("A ligar..." if busy else "Ligar")
        self.cancel_btn.setEnabled(not busy)
        for edit in (self.server_edit, self.user_edit, self.password_edit, self.sage_edit, self.mss_edit):
            edit.setReadOnly(busy)
        if busy:
            from PySide6.QtWidgets import QApplication
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents()
        else:
            from PySide6.QtWidgets import QApplication
            QApplication.restoreOverrideCursor()

    def get_config(self) -> dict:
        return self._result

    def moveEvent(self, event: QMoveEvent):
        super().moveEvent(event)
        self.update()

_STYLE = """
QDialog {
    background: #ffffff;
}
QLabel#titleLabel {
    font-size: 18px;
    font-weight: 700;
    color: #11161c;
}
QLabel#subtitleLabel {
    font-size: 13px;
    color: #4a5568;
}
QLabel#fieldLabel {
    font-size: 13px;
    font-weight: 600;
    color: #1a202c;
    padding: 0 0 2px 0;
}
QLabel#errorLabel {
    font-size: 12px;
    font-weight: 600;
    color: #c62828;
    background: #fde2e1;
    border: 1px solid #f3b9b7;
    border-radius: 6px;
    padding: 8px 10px;
}
QLineEdit {
    background: #ffffff;
    color: #1a202c;
    border: 1px solid #cbd5e0;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 13px;
    selection-background-color: #21866f;
    selection-color: #ffffff;
}
QLineEdit:focus {
    border: 1px solid #21866f;
}
QLineEdit:disabled {
    background: #f7fafc;
    color: #a0aec0;
}
QComboBox {
    background: #ffffff;
    color: #1a202c;
    border: 1px solid #cbd5e0;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 13px;
}
QComboBox:focus {
    border: 1px solid #21866f;
}
QComboBox::drop-down {
    width: 24px;
    border: none;
}
QComboBox::down-arrow {
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #1a202c;
    border: 1px solid #cbd5e0;
    selection-background-color: #21866f;
    selection-color: #ffffff;
}
QCheckBox {
    color: #1a202c;
    font-size: 13px;
    spacing: 6px;
}
QPushButton#saveBtn {
    background: #21866f;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 10px 20px;
    font-weight: 700;
    font-size: 14px;
}
QPushButton#saveBtn:hover {
    background: #1b6f5c;
}
QPushButton#saveBtn:disabled {
    background: #a0c4ba;
}
QPushButton#cancelBtn {
    background: #edf2f7;
    color: #2d3748;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 10px 20px;
    font-weight: 600;
    font-size: 14px;
}
QPushButton#cancelBtn:hover {
    background: #e2e8f0;
}
QPushButton#browseBtn {
    background: #edf2f7;
    color: #2d3748;
    border: 1px solid #cbd5e0;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 600;
    font-size: 12px;
}
QPushButton#browseBtn:hover {
    background: #e2e8f0;
}
"""
