from PySide6.QtWidgets import QApplication, QWidget

app = QApplication([])

janela = QWidget()
janela.setWindowTitle("Kit de Validação MyTeam vs ERP")
janela.resize(800, 500)
janela.show()

app.exec()