"""Diálogo de configuração — testa a ligação SQL antes de aceitar."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMoveEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from core.database import Database

class ConfigDialog(QDialog):
    """Formulário que testa a ligação SQL antes de deixar prosseguir."""

    def __init__(self, existing_config: dict | None = None):
        super().__init__()
        self.setWindowTitle("Ligação ao SQL Server — Kit de Validação")
        self.setFixedSize(540, 480)
        self.setWindowFlags(self.windowFlags() | Qt.MSWindowsFixedSizeDialogHint)
        self.setModal(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_STYLE)

        self._result: dict | None = None

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

        self.sage_edit = self._add_field(layout, "Base ERP (Sage 50):")
        self.sage_edit.setPlaceholderText("ex: Sage50_1")

        self.mss_edit = self._add_field(layout, "Base MSS:")
        self.mss_edit.setPlaceholderText("ex: MSS")

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
            self._show_error(f"{friendly}\n\n{msg}")
            return

        self._result = {
            "sql_server": {"server": server, "user": user, "password": password},
            "databases": {"sage50": sage, "mss": mss},
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
"""
