# -*- coding: utf-8 -*-
"""Classe principal do plugin Divisão Balanceada de Áreas.

Registra a ação no menu/barra de ferramentas, abre o diálogo principal e
orquestra a execução do pipeline em segundo plano (``QgsTask``), a carga
do resultado no canvas (simbologia categorizada por operador + rótulos) e
o diálogo de relatório.
"""

import os

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsFillSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRendererCategory,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox

from .core import qgis_utils
from .core.pipeline import PipelineTask


class BalancedWorkAreas:
    """Plugin QGIS — Divisão Balanceada de Áreas (SAP)."""

    def __init__(self, iface):
        self.iface = iface
        self.acao = None
        self.dialogo = None
        self.tarefa = None

    # ------------------------------------------------- ciclo de vida

    def initGui(self):  # noqa: N802 - contrato QGIS
        """Cria a ação no menu Vetor e na barra de ferramentas."""
        icone = QIcon(
            os.path.join(os.path.dirname(__file__), "icons", "icon.svg")
        )
        self.acao = QAction(
            icone,
            "Divisão Balanceada de Áreas…",
            self.iface.mainWindow(),
        )
        self.acao.triggered.connect(self.abrir_dialogo)
        self.iface.addPluginToVectorMenu("&Divisão Balanceada de Áreas", self.acao)
        self.iface.addToolBarIcon(self.acao)

    def unload(self):
        """Remove ações e cancela tarefa pendente ao descarregar."""
        if self.tarefa is not None:
            try:
                self.tarefa.cancel()
            except RuntimeError:
                pass  # tarefa já finalizada/destruída
            self.tarefa = None
        if self.acao is not None:
            self.iface.removePluginVectorMenu(
                "&Divisão Balanceada de Áreas", self.acao
            )
            self.iface.removeToolBarIcon(self.acao)
            self.acao = None
        if self.dialogo is not None:
            self.dialogo.close()
            self.dialogo = None

    # ------------------------------------------------------ execução

    def abrir_dialogo(self):
        """Abre (ou traz à frente) o diálogo principal."""
        from .gui.main_dialog import DialogoPrincipal

        if self.dialogo is None:
            self.dialogo = DialogoPrincipal(self.iface.mainWindow())
            self.dialogo.botao_executar.clicked.connect(self.executar)
            self.dialogo.botao_cancelar.clicked.connect(self.cancelar)
        self.dialogo.show()
        self.dialogo.raise_()
        self.dialogo.activateWindow()

    def executar(self):
        """Coleta parâmetros, valida e dispara a tarefa em segundo plano."""
        try:
            parametros = self.dialogo.montar_parametros()
        except ValueError as exc:
            QMessageBox.warning(self.dialogo, "Parâmetros inválidos", str(exc))
            return
        self.tarefa = PipelineTask(parametros)
        self.tarefa.progressChanged.connect(
            lambda p: self.dialogo.barra_progresso.setValue(int(p))
        )
        self.tarefa.concluido.connect(self._ao_concluir)
        self.dialogo.definir_execucao(True)
        QgsApplication.taskManager().addTask(self.tarefa)
        self.iface.messageBar().pushMessage(
            "Divisão Balanceada de Áreas",
            "Divisão iniciada em segundo plano — acompanhe o progresso.",
            level=Qgis.Info,
        )

    def cancelar(self):
        """Cancelamento cooperativo da tarefa em andamento."""
        if self.tarefa is not None:
            self.tarefa.cancel()

    def _ao_concluir(self, ok):
        """Trata o término da tarefa (thread principal)."""
        tarefa, self.tarefa = self.tarefa, None
        self.dialogo.definir_execucao(False)
        if not ok or tarefa is None or tarefa.resultado is None:
            mensagem = (
                tarefa.erro if tarefa is not None and tarefa.erro
                else "Falha desconhecida — consulte o log Divisão Balanceada de Áreas."
            )
            self.dialogo.rotulo_resumo.setText("Falha: %s" % mensagem)
            self.iface.messageBar().pushMessage(
                "Divisão Balanceada de Áreas", mensagem, level=Qgis.Critical
            )
            return
        resultado = tarefa.resultado
        camada = self._carregar_resultado(resultado)
        resumo = (
            "Concluído: %d lotes; CV = σ/μ = %.4f. Camada: %s"
            % (
                sum(
                    1 for l in resultado.lotes if not l.geometria.isEmpty()
                ),
                resultado.cv,
                resultado.caminho_gpkg,
            )
        )
        self.dialogo.rotulo_resumo.setText(resumo)
        nivel = Qgis.Success if camada is not None else Qgis.Warning
        self.iface.messageBar().pushMessage(
            "Divisão Balanceada de Áreas", resumo, level=nivel
        )
        for aviso in resultado.avisos:
            self.iface.messageBar().pushMessage(
                "Divisão Balanceada de Áreas", aviso, level=Qgis.Warning
            )
        from .gui.results_dialog import DialogoResultados

        DialogoResultados(resultado, self.dialogo).exec_()

    # -------------------------------------------------------- canvas

    def _carregar_resultado(self, resultado):
        """Carrega o GeoPackage de lotes no canvas com simbologia/rótulos."""
        camada = QgsVectorLayer(
            "%s|layername=lotes_trabalho" % resultado.caminho_gpkg,
            "Lotes de trabalho (SAP)",
            "ogr",
        )
        if not camada.isValid():
            qgis_utils.log(
                "Não foi possível carregar %s." % resultado.caminho_gpkg
            )
            return None
        camada.setRenderer(self._simbologia(camada))
        self._rotulos(camada)
        QgsProject.instance().addMapLayer(camada)
        return camada

    @staticmethod
    def _simbologia(camada):
        """Simbologia categorizada por operador (cores igualmente espaçadas)."""
        operadores = sorted(
            {f["operador"] for f in camada.getFeatures()}
        )
        categorias = []
        total = max(len(operadores), 1)
        for indice, operador in enumerate(operadores):
            cor = QColor.fromHsv(
                int(360.0 * indice / total) % 360, 160, 230, 160
            )
            simbolo = QgsFillSymbol.createSimple(
                {
                    "color": "%d,%d,%d,%d"
                    % (cor.red(), cor.green(), cor.blue(), cor.alpha()),
                    "outline_color": "35,35,35,255",
                    "outline_width": "0.5",
                }
            )
            categorias.append(
                QgsRendererCategory(operador, simbolo, str(operador))
            )
        return QgsCategorizedSymbolRenderer("operador", categorias)

    @staticmethod
    def _rotulos(camada):
        """Rótulos com o nome do operador em cada lote."""
        configuracao = QgsPalLayerSettings()
        configuracao.fieldName = "operador"
        configuracao.placement = QgsPalLayerSettings.Horizontal
        formato = QgsTextFormat()
        formato.setSize(10)
        configuracao.setFormat(formato)
        camada.setLabelsEnabled(True)
        camada.setLabeling(QgsVectorLayerSimpleLabeling(configuracao))
