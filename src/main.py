import sys
import webbrowser

import pyodbc
from PySide6.QtWidgets import QApplication, QMessageBox

from core.config_loader import load_config, save_config
from ui.config_dialog import ConfigDialog
from ui.main_window import MainWindow

ODBC_URL = "https://go.microsoft.com/fwlink/?linkid=2216184"


def _check_odbc_driver():
    drivers = pyodbc.drivers()
    if any("ODBC Driver 17" in d for d in drivers):
        return True

    msg = QMessageBox()
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle("Driver ODBC em falta")
    msg.setText("O Driver ODBC 17 for SQL Server não está instalado no sistema.")
    msg.setInformativeText(
        "A aplicação necessita deste driver para se ligar ao SQL Server.\n\n"
        "Prima 'Descarregar' para abrir a página de instalação da Microsoft."
    )
    download_btn = msg.addButton("Descarregar", QMessageBox.ButtonRole.AcceptRole)
    msg.addButton("Sair", QMessageBox.ButtonRole.RejectRole)
    msg.exec()

    if msg.clickedButton() == download_btn:
        webbrowser.open(ODBC_URL)
    sys.exit(0)


def main():
    app = QApplication(sys.argv)

    _check_odbc_driver()

    existing = None
    try:
        existing = load_config()
    except Exception:
        pass

    dialog = ConfigDialog(existing_config=existing)
    if dialog.exec() != ConfigDialog.DialogCode.Accepted:
        sys.exit(0)

    config = dialog.get_config()
    save_config(config)

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
