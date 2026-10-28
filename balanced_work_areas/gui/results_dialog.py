# -*- coding: utf-8 -*-
"""Diálogo de resultados (Etapa 7): tabela de lotes, CV e exportar CSV."""

import csv

from qgis.PyQt.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

_COLUNAS = (
    ("Operador", lambda l: l.operador),
    ("ej", lambda l: "%.2f" % l.fator_experiencia),
    ("Carga-alvo", lambda l: "%.1f" % l.carga_alvo),
    ("Carga final", lambda l: "%.1f" % l.carga_total),
    ("Desvio (%)", lambda l: "%+.1f" % l.desvio_percentual),
    ("Pontos", lambda l: str(l.n_pontos)),
    ("Linhas", lambda l: str(l.n_linhas)),
    ("Polígonos", lambda l: str(l.n_poligonos)),
)


class DialogoResultados(QDialog):
    """Relatório resumo pós-execução, com opção de exportar CSV."""

    def __init__(self, resultado, parent=None):
        super().__init__(parent)
        self.resultado = resultado
        self.setWindowTitle("Resultado — Divisão Balanceada de Áreas")
        self.setMinimumSize(560, 360)

        coluna = QVBoxLayout(self)
        nome_metodo = (
            "Voronoi adaptativo ponderado por densidade"
            if resultado.metodo == "voronoi"
            else "Grade regular (quadrados)"
        )
        coluna.addWidget(
            QLabel(
                "<b>Método:</b> %s &nbsp;|&nbsp; <b>Células:</b> %d "
                "&nbsp;|&nbsp; <b>Pontos de esforço:</b> %d"
                % (
                    nome_metodo,
                    resultado.n_celulas,
                    resultado.n_pontos_esforco,
                )
            )
        )

        self.tabela = QTableWidget(len(resultado.lotes), len(_COLUNAS))
        self.tabela.setHorizontalHeaderLabels([c[0] for c in _COLUNAS])
        self.tabela.horizontalHeader().setStretchLastSection(True)
        self.tabela.setEditTriggers(QTableWidget.NoEditTriggers)
        for linha, lote in enumerate(resultado.lotes):
            for coluna_indice, (_, extrator) in enumerate(_COLUNAS):
                self.tabela.setItem(
                    linha,
                    coluna_indice,
                    QTableWidgetItem(extrator(lote)),
                )
        self.tabela.resizeColumnsToContents()
        coluna.addWidget(self.tabela)

        rotulo_cv = QLabel(
            "<b>Coeficiente de variação das cargas: CV = σ/μ = %.4f</b>"
            % resultado.cv
        )
        coluna.addWidget(rotulo_cv)
        if resultado.avisos:
            avisos = QLabel(
                "<i>Avisos:</i><br>%s" % "<br>".join(resultado.avisos)
            )
            avisos.setWordWrap(True)
            coluna.addWidget(avisos)

        linha_botoes = QHBoxLayout()
        botao_csv = QPushButton("Exportar CSV…")
        botao_csv.clicked.connect(self._exportar_csv)
        botao_fechar = QPushButton("Fechar")
        botao_fechar.clicked.connect(self.accept)
        linha_botoes.addWidget(botao_csv)
        linha_botoes.addStretch()
        linha_botoes.addWidget(botao_fechar)
        coluna.addLayout(linha_botoes)

    def _exportar_csv(self) -> None:
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Exportar relatório", "relatorio_lotes.csv", "CSV (*.csv)"
        )
        if not caminho:
            return
        try:
            with open(
                caminho, "w", newline="", encoding="utf-8-sig"
            ) as arquivo:
                escritor = csv.writer(arquivo, delimiter=";")
                escritor.writerow(
                    [
                        "operador",
                        "fator_experiencia",
                        "carga_alvo",
                        "carga_total",
                        "desvio_percentual",
                        "n_pontos",
                        "n_linhas",
                        "n_poligonos",
                    ]
                )
                for lote in self.resultado.lotes:
                    escritor.writerow(
                        [
                            lote.operador,
                            "%.4f" % lote.fator_experiencia,
                            "%.4f" % lote.carga_alvo,
                            "%.4f" % lote.carga_total,
                            "%.4f" % lote.desvio_percentual,
                            lote.n_pontos,
                            lote.n_linhas,
                            lote.n_poligonos,
                        ]
                    )
                escritor.writerow([])
                escritor.writerow(["CV", "%.6f" % self.resultado.cv])
        except OSError as exc:
            QMessageBox.warning(
                self, "Exportar CSV", "Falha ao gravar: %s" % exc
            )
            return
        QMessageBox.information(
            self, "Exportar CSV", "Relatório exportado para %s." % caminho
        )
