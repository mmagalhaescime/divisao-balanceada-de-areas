# -*- coding: utf-8 -*-
"""Diálogo principal do plugin (construído programaticamente em PyQt).

Três abas (Área e divisão / Dados de entrada / Parâmetros da metodologia)
e rodapé com Executar, Cancelar, Ajuda, barra de progresso e resumo
pós-execução (CV). A opção por construção programática (em vez de arquivo
``.ui``) é deliberada e consistente em todo o plugin.
"""

import os
import tempfile

from qgis.core import QgsFeatureRequest, QgsMapLayerProxyModel, QgsProject
from qgis.gui import (
    QgsFileWidget,
    QgsMapLayerComboBox,
    QgsProjectionSelectionWidget,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import data_acquisition, edgv_classes, qgis_utils
from ..core.algorithms import defaults_por_escala
from ..core.pipeline import (
    METODO_GRADE,
    METODO_VORONOI,
    ParametrosPipeline,
)

ESCALAS = (
    ("1:25.000", 25000),
    ("1:50.000", 50000),
    ("1:100.000", 100000),
    ("1:250.000", 250000),
)

_TEXTO_AJUDA = """<h3>Divisão Balanceada de Áreas — SAP</h3>
<p>O plugin divide a <b>moldura</b> selecionada em <b>k</b> áreas de
trabalho com carga cartográfica equilibrada, usando dados vetoriais de
fontes abertas (ou camadas locais) como proxy de complexidade.</p>
<ol>
<li><b>Área e divisão</b>: escolha a camada de moldura, o número de
áreas (k) e o método — Voronoi adaptativo ponderado por densidade
(metodologia principal) ou grade regular de quadrados;</li>
<li><b>Dados de entrada</b>: marque as fontes de download automático
(OSM, ANA, IBGE, Google Open Buildings) e/ou adicione camadas locais do
projeto; selecione as classes ET-EDGV que entram no cálculo;</li>
<li><b>Parâmetros</b>: escala de trabalho (preenche d e r), pesos
&alpha; &le; &beta; &le; &gamma;, tabela de operadores com fator de
experiência e<sub>j</sub> &ge; 1, CRS de saída e seed.</li>
</ol>
<p>O resultado é uma camada GeoPackage de lotes com metadados de carga
(<code>operador, carga_alvo, carga_total, desvio_percentual, ...</code>)
e um relatório com o coeficiente de variação CV = &sigma;/&mu;.</p>
<p>O processamento roda em segundo plano (QgsTask) e pode ser cancelado;
mensagens detalhadas ficam na aba <i>Divisão Balanceada de Áreas</i> do painel de
log. Consulte o README.md do plugin para detalhes.</p>"""


class DialogoPrincipal(QDialog):
    """Janela principal (modal-menos, aberta pelo botão do plugin)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Divisão Balanceada de Áreas — SAP")
        self.setMinimumSize(640, 640)
        self._m_editado_pelo_usuario = False

        raiz = QVBoxLayout(self)
        self.abas = QTabWidget()
        raiz.addWidget(self.abas)
        self.abas.addTab(self._criar_aba_area(), "Área e divisão")
        self.abas.addTab(self._criar_aba_dados(), "Dados de entrada")
        self.abas.addTab(self._criar_aba_parametros(), "Parâmetros")
        raiz.addLayout(self._criar_rodape())

        self._conectar_sinais()
        self._sincronizar_operadores()
        self._aplicar_defaults_escala()
        self._alternar_metodo()

    # ------------------------------------------------------------ Aba 1

    def _criar_aba_area(self) -> QWidget:
        aba = QWidget()
        formulario = QFormLayout(aba)

        self.combo_moldura = QgsMapLayerComboBox()
        self.combo_moldura.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        formulario.addRow("Camada de moldura:", self.combo_moldura)

        self.check_selecionadas = QCheckBox(
            "Usar somente feições selecionadas"
        )
        formulario.addRow("", self.check_selecionadas)

        self.spin_k = QSpinBox()
        self.spin_k.setRange(2, 200)
        self.spin_k.setValue(4)
        formulario.addRow("Quantidade de áreas de trabalho (k):", self.spin_k)

        self.combo_metodo = QComboBox()
        self.combo_metodo.addItem(
            "Voronoi adaptativo ponderado por densidade", METODO_VORONOI
        )
        self.combo_metodo.addItem(
            "Grade regular (quadrados)", METODO_GRADE
        )
        formulario.addRow("Método de divisão:", self.combo_metodo)

        # Parâmetros condicionais ao método.
        self.pilha_metodo = QStackedWidget()

        pagina_voronoi = QWidget()
        formulario_voronoi = QFormLayout(pagina_voronoi)
        self.spin_multiplicador = QSpinBox()
        self.spin_multiplicador.setRange(5, 500)
        self.spin_multiplicador.setValue(30)
        self.spin_multiplicador.setToolTip(
            "Número de geradores N = multiplicador × k. Valores maiores "
            "aumentam a granularidade (e o custo) da partição."
        )
        formulario_voronoi.addRow(
            "Multiplicador de geradores (N/k):", self.spin_multiplicador
        )
        self.pilha_metodo.addWidget(pagina_voronoi)

        pagina_grade = QWidget()
        formulario_grade = QFormLayout(pagina_grade)
        self.spin_m = QSpinBox()
        self.spin_m.setRange(1, 1000)
        self.spin_m.setValue(self.spin_k.value())
        self.spin_m.setToolTip(
            "Número de quadrados por área final (m). A grade terá "
            "aproximadamente m × k quadrados; padrão m = k (ex.: k = 6 → "
            "36 quadrados)."
        )
        formulario_grade.addRow(
            "Fator de subdivisão da grade (m):", self.spin_m
        )
        self.pilha_metodo.addWidget(pagina_grade)

        formulario.addRow(self.pilha_metodo)
        return aba

    # ------------------------------------------------------------ Aba 2

    def _criar_aba_dados(self) -> QWidget:
        aba = QWidget()
        coluna = QVBoxLayout(aba)

        grupo_fontes = QGroupBox(
            "Fontes de dados abertas (download automático)"
        )
        leiaute_fontes = QVBoxLayout(grupo_fontes)
        self.check_osm = QCheckBox("OpenStreetMap (API Overpass)")
        self.check_osm.setChecked(True)
        self.check_ana = QCheckBox("Hidrografia ANA (WFS/SNIRH)")
        self.check_ibge = QCheckBox("Malhas IBGE (WFS)")
        self.check_ob = QCheckBox("Google Open Buildings")
        for caixa in (
            self.check_osm,
            self.check_ana,
            self.check_ibge,
            self.check_ob,
        ):
            leiaute_fontes.addWidget(caixa)
        linha_ob = QHBoxLayout()
        rotulo_ob = QLabel("Arquivo local Open Buildings (opcional):")
        self.arquivo_ob = QgsFileWidget()
        self.arquivo_ob.setFilter(
            "CSV Open Buildings (*.csv *.csv.gz);;Todos (*)"
        )
        self.arquivo_ob.setToolTip(
            "Os tiles S2 do Open Buildings podem ter centenas de MB; se "
            "já tiver o CSV baixado, aponte-o aqui para evitar o download."
        )
        linha_ob.addWidget(rotulo_ob)
        linha_ob.addWidget(self.arquivo_ob)
        leiaute_fontes.addLayout(linha_ob)
        linha_cache = QHBoxLayout()
        self.check_cache = QCheckBox(
            "Usar cache local (downloads.gpkg) em reexecuções"
        )
        self.check_cache.setChecked(True)
        self.botao_limpar_cache = QPushButton("Limpar cache")
        linha_cache.addWidget(self.check_cache)
        linha_cache.addStretch()
        linha_cache.addWidget(self.botao_limpar_cache)
        leiaute_fontes.addLayout(linha_cache)
        linha_buffer = QHBoxLayout()
        linha_buffer.addWidget(
            QLabel("Buffer da bounding box de download (m):")
        )
        self.spin_buffer = QDoubleSpinBox()
        self.spin_buffer.setRange(0.0, 10000.0)
        self.spin_buffer.setValue(500.0)
        linha_buffer.addWidget(self.spin_buffer)
        linha_buffer.addStretch()
        leiaute_fontes.addLayout(linha_buffer)
        coluna.addWidget(grupo_fontes)

        grupo_locais = QGroupBox("Camadas locais (insumo adicional)")
        leiaute_locais = QVBoxLayout(grupo_locais)
        self.lista_locais = QListWidget()
        self.lista_locais.setMaximumHeight(90)
        leiaute_locais.addWidget(self.lista_locais)
        linha_botoes = QHBoxLayout()
        self.botao_adicionar_local = QPushButton(
            "Adicionar camada do projeto…"
        )
        self.botao_remover_local = QPushButton("Remover selecionada")
        linha_botoes.addWidget(self.botao_adicionar_local)
        linha_botoes.addWidget(self.botao_remover_local)
        linha_botoes.addStretch()
        leiaute_locais.addLayout(linha_botoes)
        coluna.addWidget(grupo_locais)

        grupo_classes = QGroupBox(
            "Classes de feições (ET-EDGV) usadas no cálculo de complexidade"
        )
        leiaute_classes = QVBoxLayout(grupo_classes)
        self.arvore_classes = QTreeWidget()
        self.arvore_classes.setHeaderHidden(True)
        padrao = set(edgv_classes.ids_padrao())
        for primitiva, classes in edgv_classes.classes_por_primitiva().items():
            item_raiz = QTreeWidgetItem(
                [edgv_classes.ROTULOS_PRIMITIVA[primitiva]]
            )
            item_raiz.setFlags(
                item_raiz.flags()
                | Qt.ItemIsUserCheckable
                | Qt.ItemIsAutoTristate
            )
            for classe in classes:
                filho = QTreeWidgetItem(
                    ["%s — %s" % (classe["categoria"], classe["nome"])]
                )
                filho.setFlags(filho.flags() | Qt.ItemIsUserCheckable)
                filho.setData(0, Qt.UserRole, classe["id"])
                filho.setCheckState(
                    0,
                    Qt.Checked if classe["id"] in padrao else Qt.Unchecked,
                )
                item_raiz.addChild(filho)
            self.arvore_classes.addTopLevelItem(item_raiz)
            item_raiz.setExpanded(True)
        leiaute_classes.addWidget(self.arvore_classes)
        coluna.addWidget(grupo_classes, stretch=1)
        return aba

    # ------------------------------------------------------------ Aba 3

    def _criar_aba_parametros(self) -> QWidget:
        aba = QWidget()
        formulario = QFormLayout(aba)

        self.combo_escala = QComboBox()
        for rotulo, denominador in ESCALAS:
            self.combo_escala.addItem(rotulo, denominador)
        self.combo_escala.setCurrentIndex(1)  # 1:50.000
        formulario.addRow("Escala de trabalho:", self.combo_escala)

        self.spin_d = QDoubleSpinBox()
        self.spin_d.setRange(1.0, 100000.0)
        self.spin_d.setSuffix(" m")
        formulario.addRow(
            "d — segmentação de linhas:", self.spin_d
        )

        self.spin_r = QDoubleSpinBox()
        self.spin_r.setRange(10.0, 1000000.0)
        self.spin_r.setSuffix(" m")
        formulario.addRow(
            "r — resolução da grade auxiliar:", self.spin_r
        )

        linha_pesos = QHBoxLayout()
        self.spin_alfa = QDoubleSpinBox()
        self.spin_beta = QDoubleSpinBox()
        self.spin_gama = QDoubleSpinBox()
        for spin, valor, rotulo in (
            (self.spin_alfa, 1.0, "α (ponto)"),
            (self.spin_beta, 2.0, "β (linha)"),
            (self.spin_gama, 3.0, "γ (polígono)"),
        ):
            spin.setRange(0.0, 1000.0)
            spin.setDecimals(2)
            spin.setValue(valor)
            linha_pesos.addWidget(QLabel(rotulo + ":"))
            linha_pesos.addWidget(spin)
        linha_pesos.addStretch()
        contenedor_pesos = QWidget()
        contenedor_pesos.setLayout(linha_pesos)
        formulario.addRow("Pesos de aquisição (α ≤ β ≤ γ):", contenedor_pesos)

        self.tabela_operadores = QTableWidget(0, 2)
        self.tabela_operadores.setHorizontalHeaderLabels(
            ["Operador", "Fator de experiência (ej ≥ 1)"]
        )
        self.tabela_operadores.horizontalHeader().setStretchLastSection(True)
        self.tabela_operadores.setMinimumHeight(120)
        formulario.addRow(
            "Operadores (uma linha por área):", self.tabela_operadores
        )
        self.botao_ej_iguais = QPushButton(
            "Todos iguais (ej = 1 — sem ponderação)"
        )
        formulario.addRow("", self.botao_ej_iguais)

        linha_delta = QHBoxLayout()
        linha_delta.addWidget(
            QLabel("δ = √(Ai/ni) por célula × fator de ajuste:")
        )
        self.spin_fator_delta = QDoubleSpinBox()
        self.spin_fator_delta.setRange(0.1, 5.0)
        self.spin_fator_delta.setSingleStep(0.1)
        self.spin_fator_delta.setValue(1.0)
        linha_delta.addWidget(self.spin_fator_delta)
        linha_delta.addStretch()
        contenedor_delta = QWidget()
        contenedor_delta.setLayout(linha_delta)
        formulario.addRow(
            "Distância mínima do disco de Poisson:", contenedor_delta
        )

        self.check_crs_auto = QCheckBox(
            "Detectar SIRGAS 2000 / UTM automaticamente pelo centroide"
        )
        self.check_crs_auto.setChecked(True)
        formulario.addRow("CRS de saída:", self.check_crs_auto)
        self.seletor_crs = QgsProjectionSelectionWidget()
        self.seletor_crs.setEnabled(False)
        formulario.addRow("", self.seletor_crs)

        linha_seed = QHBoxLayout()
        self.check_seed = QCheckBox("Seed aleatória (reprodutibilidade):")
        self.spin_seed = QSpinBox()
        self.spin_seed.setRange(0, 2147483647)
        self.spin_seed.setValue(42)
        self.spin_seed.setEnabled(False)
        linha_seed.addWidget(self.check_seed)
        linha_seed.addWidget(self.spin_seed)
        linha_seed.addStretch()
        contenedor_seed = QWidget()
        contenedor_seed.setLayout(linha_seed)
        formulario.addRow("", contenedor_seed)
        return aba

    # ----------------------------------------------------------- Rodapé

    def _criar_rodape(self) -> QVBoxLayout:
        rodape = QVBoxLayout()
        self.barra_progresso = QProgressBar()
        self.barra_progresso.setRange(0, 100)
        self.barra_progresso.setValue(0)
        rodape.addWidget(self.barra_progresso)
        self.rotulo_resumo = QLabel("")
        self.rotulo_resumo.setWordWrap(True)
        rodape.addWidget(self.rotulo_resumo)
        linha = QHBoxLayout()
        self.botao_ajuda = QPushButton("Ajuda")
        self.botao_cancelar = QPushButton("Cancelar")
        self.botao_cancelar.setEnabled(False)
        self.botao_executar = QPushButton("Executar")
        self.botao_executar.setDefault(True)
        linha.addWidget(self.botao_ajuda)
        linha.addStretch()
        linha.addWidget(self.botao_cancelar)
        linha.addWidget(self.botao_executar)
        rodape.addLayout(linha)
        return rodape

    # ----------------------------------------------------------- Sinais

    def _conectar_sinais(self) -> None:
        self.spin_k.valueChanged.connect(self._sincronizar_operadores)
        self.spin_k.valueChanged.connect(self._sincronizar_m_padrao)
        self.spin_m.valueChanged.connect(self._marcar_m_editado)
        self.combo_metodo.currentIndexChanged.connect(self._alternar_metodo)
        self.combo_escala.currentIndexChanged.connect(
            self._aplicar_defaults_escala
        )
        self.botao_ej_iguais.clicked.connect(self._zerar_ponderacao)
        self.botao_ajuda.clicked.connect(self._mostrar_ajuda)
        self.botao_adicionar_local.clicked.connect(self._adicionar_local)
        self.botao_remover_local.clicked.connect(self._remover_local)
        self.botao_limpar_cache.clicked.connect(self._limpar_cache)
        self.check_crs_auto.toggled.connect(
            lambda auto: self.seletor_crs.setEnabled(not auto)
        )
        self.check_seed.toggled.connect(self.spin_seed.setEnabled)

    def _alternar_metodo(self) -> None:
        self.pilha_metodo.setCurrentIndex(
            0 if self.combo_metodo.currentData() == METODO_VORONOI else 1
        )

    def _marcar_m_editado(self) -> None:
        if self.spin_m.value() != self.spin_k.value():
            self._m_editado_pelo_usuario = True

    def _sincronizar_m_padrao(self) -> None:
        """Mantém o padrão m = k enquanto o usuário não editar m."""
        if not self._m_editado_pelo_usuario:
            self.spin_m.blockSignals(True)
            self.spin_m.setValue(self.spin_k.value())
            self.spin_m.blockSignals(False)

    def _aplicar_defaults_escala(self) -> None:
        padroes = defaults_por_escala(self.combo_escala.currentData())
        self.spin_d.setValue(padroes["d"])
        self.spin_r.setValue(padroes["r"])

    def _sincronizar_operadores(self) -> None:
        """Tabela de operadores sempre com k linhas."""
        k = self.spin_k.value()
        atual = self.tabela_operadores.rowCount()
        self.tabela_operadores.setRowCount(k)
        from qgis.PyQt.QtWidgets import QTableWidgetItem

        for linha in range(atual, k):
            self.tabela_operadores.setItem(
                linha, 0, QTableWidgetItem("Operador %d" % (linha + 1))
            )
            spin = QDoubleSpinBox()
            spin.setRange(1.0, 100.0)
            spin.setDecimals(2)
            spin.setValue(1.0)
            self.tabela_operadores.setCellWidget(linha, 1, spin)

    def _zerar_ponderacao(self) -> None:
        for linha in range(self.tabela_operadores.rowCount()):
            widget = self.tabela_operadores.cellWidget(linha, 1)
            if widget is not None:
                widget.setValue(1.0)

    def _mostrar_ajuda(self) -> None:
        QMessageBox.information(self, "Ajuda — Divisão Balanceada de Áreas", _TEXTO_AJUDA)

    def _adicionar_local(self) -> None:
        """Menu com as camadas vetoriais do projeto ainda não adicionadas."""
        menu = QMenu(self)
        ja_adicionadas = {
            self.lista_locais.item(i).data(Qt.UserRole)
            for i in range(self.lista_locais.count())
        }
        for camada in QgsProject.instance().mapLayers().values():
            if camada.type() != camada.VectorLayer:
                continue
            if camada.id() in ja_adicionadas:
                continue
            acao = menu.addAction(camada.name())
            acao.setData(camada.id())
        if menu.isEmpty():
            QMessageBox.information(
                self,
                "Camadas locais",
                "Não há camadas vetoriais disponíveis no projeto.",
            )
            return
        acao = menu.exec_(
            self.botao_adicionar_local.mapToGlobal(
                self.botao_adicionar_local.rect().bottomLeft()
            )
        )
        if acao is not None:
            camada = QgsProject.instance().mapLayer(acao.data())
            if camada is not None:
                item = QListWidgetItem(camada.name())
                item.setData(Qt.UserRole, camada.id())
                self.lista_locais.addItem(item)

    def _remover_local(self) -> None:
        for item in self.lista_locais.selectedItems():
            self.lista_locais.takeItem(self.lista_locais.row(item))

    def _limpar_cache(self) -> None:
        pasta = self.pasta_trabalho()
        if data_acquisition.limpar_cache(pasta):
            QMessageBox.information(
                self, "Cache", "Cache removido (%s)." % pasta
            )
        else:
            QMessageBox.warning(
                self,
                "Cache",
                "Não foi possível remover o cache — feche as camadas do "
                "cache carregadas no projeto e tente novamente.",
            )

    # ---------------------------------------------------- Coleta/estado

    def pasta_trabalho(self) -> str:
        """Pasta do projeto (cache e saídas); temp se projeto não salvo."""
        base = QgsProject.instance().homePath()
        if not base:
            base = os.path.join(
                tempfile.gettempdir(), "balanced_work_areas"
            )
        return base

    def ids_classes_marcadas(self):
        """Classes ET-EDGV marcadas na árvore."""
        ids = []
        for i in range(self.arvore_classes.topLevelItemCount()):
            raiz = self.arvore_classes.topLevelItem(i)
            for j in range(raiz.childCount()):
                filho = raiz.child(j)
                if filho.checkState(0) == Qt.Checked:
                    ids.append(filho.data(0, Qt.UserRole))
        return ids

    def montar_parametros(self) -> ParametrosPipeline:
        """Coleta e valida os parâmetros da interface.

        Materializa as camadas locais (clones em memória) no thread
        principal — exigência de segurança do ``QgsTask``.

        :raises ValueError: com mensagem amigável se algo estiver errado.
        """
        parametros = ParametrosPipeline()
        camada_moldura = self.combo_moldura.currentLayer()
        if camada_moldura is None:
            raise ValueError("Selecione uma camada de moldura.")
        parametros.moldura = qgis_utils.moldura_unificada(
            camada_moldura, self.check_selecionadas.isChecked()
        )
        parametros.crs_moldura = camada_moldura.crs()
        parametros.k = self.spin_k.value()
        parametros.metodo = self.combo_metodo.currentData()
        parametros.multiplicador_n = self.spin_multiplicador.value()
        parametros.fator_subdivisao_m = self.spin_m.value()

        parametros.fontes = []
        if self.check_osm.isChecked():
            parametros.fontes.append("osm")
        if self.check_ana.isChecked():
            parametros.fontes.append("ana")
        if self.check_ibge.isChecked():
            parametros.fontes.append("ibge")
        if self.check_ob.isChecked():
            parametros.fontes.append("google_open_buildings")
        parametros.ids_classes = self.ids_classes_marcadas()
        arquivo_ob = self.arquivo_ob.filePath().strip()
        parametros.arquivo_open_buildings = arquivo_ob or None
        parametros.usar_cache = self.check_cache.isChecked()
        parametros.buffer_bbox_m = self.spin_buffer.value()
        parametros.pasta_trabalho = self.pasta_trabalho()

        parametros.camadas_locais = []
        for i in range(self.lista_locais.count()):
            item = self.lista_locais.item(i)
            camada = QgsProject.instance().mapLayer(item.data(Qt.UserRole))
            if camada is None:
                continue
            clone = camada.materialize(QgsFeatureRequest())
            parametros.camadas_locais.append((clone, camada.name()))

        parametros.denominador_escala = self.combo_escala.currentData()
        parametros.d = self.spin_d.value()
        parametros.r = self.spin_r.value()
        parametros.alfa = self.spin_alfa.value()
        parametros.beta = self.spin_beta.value()
        parametros.gama = self.spin_gama.value()
        parametros.fator_delta = self.spin_fator_delta.value()

        parametros.operadores = []
        for linha in range(self.tabela_operadores.rowCount()):
            item = self.tabela_operadores.item(linha, 0)
            nome = (
                item.text().strip()
                if item is not None and item.text().strip()
                else "Operador %d" % (linha + 1)
            )
            widget = self.tabela_operadores.cellWidget(linha, 1)
            fator = widget.value() if widget is not None else 1.0
            parametros.operadores.append((nome, fator))

        if not self.check_crs_auto.isChecked():
            crs = self.seletor_crs.crs()
            if not crs.isValid():
                raise ValueError("Escolha um CRS de saída válido.")
            parametros.crs_saida = crs
        if self.check_seed.isChecked():
            parametros.seed = self.spin_seed.value()

        parametros.validar()
        return parametros

    def definir_execucao(self, em_andamento: bool) -> None:
        """Alterna o estado dos controles durante a execução da tarefa."""
        self.botao_executar.setEnabled(not em_andamento)
        self.botao_cancelar.setEnabled(em_andamento)
        self.abas.setEnabled(not em_andamento)
        if em_andamento:
            self.barra_progresso.setValue(0)
            self.rotulo_resumo.setText("Executando em segundo plano…")
