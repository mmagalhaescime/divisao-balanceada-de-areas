# -*- coding: utf-8 -*-
"""Orquestração das etapas metodológicas em segundo plano (``QgsTask``).

``executar_pipeline`` encadeia as 7 etapas do método principal (ou o
método alternativo por grade regular) e é uma função pura de orquestração
— testável sem ``QgsTask``. ``PipelineTask`` a embrulha em uma tarefa do
QGIS com progresso e cancelamento, sem travar a interface.
"""

import datetime
import os
import tempfile
import traceback
from typing import Callable, List, Optional, Tuple

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsTask,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant, pyqtSignal

from . import (
    algorithms,
    clustering,
    data_acquisition,
    density_grid,
    grid_partition,
    load_calculation,
    normalization,
    qgis_utils,
    voronoi_partition,
)

METODO_VORONOI = "voronoi"
METODO_GRADE = "grade"


class ParametrosPipeline:
    """Parâmetros coletados na GUI (apenas tipos seguros para threads)."""

    def __init__(self):
        # Área e divisão
        self.moldura: Optional[QgsGeometry] = None  # CRS original
        self.crs_moldura: Optional[QgsCoordinateReferenceSystem] = None
        self.k: int = 2
        self.metodo: str = METODO_VORONOI
        self.multiplicador_n: int = 30  # N = multiplicador * k (Voronoi)
        self.fator_subdivisao_m: int = 0  # 0 → m = k (grade regular)
        # Dados de entrada
        self.fontes: List[str] = []
        self.ids_classes: List[str] = []
        self.camadas_locais: List[Tuple[QgsVectorLayer, str]] = []
        self.arquivo_open_buildings: Optional[str] = None
        self.usar_cache: bool = True
        self.pasta_trabalho: str = tempfile.gettempdir()
        self.buffer_bbox_m: float = 500.0
        # Parâmetros da metodologia
        self.denominador_escala: int = 50000
        self.d: float = 100.0
        self.r: float = 500.0
        self.alfa: float = 1.0
        self.beta: float = 2.0
        self.gama: float = 3.0
        self.operadores: List[Tuple[str, float]] = []  # (nome, ej)
        self.fator_delta: float = 1.0
        self.crs_saida: Optional[QgsCoordinateReferenceSystem] = None
        self.seed: Optional[int] = None

    def validar(self) -> None:
        """Validações de consistência (:raises ValueError: se inválido)."""
        if self.moldura is None or self.moldura.isEmpty():
            raise ValueError("Selecione uma camada de moldura com feições.")
        if self.k < 2:
            raise ValueError("A quantidade de áreas (k) deve ser >= 2.")
        if not self.fontes and not self.camadas_locais:
            raise ValueError(
                "Marque ao menos uma fonte de dados aberta ou adicione "
                "uma camada local."
            )
        if self.fontes and not self.ids_classes:
            raise ValueError(
                "Marque ao menos uma classe de feição ET-EDGV para as "
                "fontes de download."
            )
        if not (self.alfa <= self.beta <= self.gama):
            raise ValueError(
                "Os pesos devem satisfazer alfa <= beta <= gama."
            )
        if self.d <= 0 or self.r <= 0:
            raise ValueError("Os parâmetros d e r devem ser positivos.")
        if len(self.operadores) != self.k:
            raise ValueError(
                "A tabela de operadores deve ter exatamente k linhas."
            )
        if any(e < 1.0 for _, e in self.operadores):
            raise ValueError(
                "Os fatores de experiência ej devem ser >= 1."
            )


class LoteResultado:
    """Linha do relatório final (um lote por operador)."""

    __slots__ = (
        "operador",
        "fator_experiencia",
        "carga_alvo",
        "carga_total",
        "n_pontos",
        "n_linhas",
        "n_poligonos",
        "desvio_percentual",
        "geometria",
    )

    def __init__(self, operador, fator_experiencia, carga_alvo):
        self.operador = operador
        self.fator_experiencia = fator_experiencia
        self.carga_alvo = carga_alvo
        self.carga_total = 0.0
        self.n_pontos = 0
        self.n_linhas = 0
        self.n_poligonos = 0
        self.desvio_percentual = 0.0
        self.geometria = QgsGeometry()


class ResultadoPipeline:
    """Resultado da execução (consumido no thread principal)."""

    def __init__(self):
        self.caminho_gpkg: str = ""
        self.lotes: List[LoteResultado] = []
        self.cv: float = 0.0
        self.metodo: str = METODO_VORONOI
        self.n_celulas: int = 0
        self.n_pontos_esforco: int = 0
        self.crs: Optional[QgsCoordinateReferenceSystem] = None
        self.avisos: List[str] = []


def executar_pipeline(
    parametros: ParametrosPipeline,
    progresso: Callable[[float], None] = lambda p: None,
    cancelado: Callable[[], bool] = lambda: False,
) -> ResultadoPipeline:
    """Executa as 7 etapas metodológicas e grava o GeoPackage de lotes.

    :param parametros: parâmetros validados (``parametros.validar()``).
    :param progresso: callback 0..100 (ligado a ``QgsTask.setProgress``).
    :param cancelado: callback de cancelamento cooperativo.
    :returns: :class:`ResultadoPipeline` com lotes, CV e avisos.
    """

    def checar_cancelamento():
        if cancelado():
            raise InterruptedError("Cancelado pelo usuário.")

    resultado = ResultadoPipeline()
    resultado.metodo = parametros.metodo

    # ---------------------------------------------------- CRS de trabalho
    moldura_original = qgis_utils.geometria_valida(parametros.moldura)
    crs_trabalho = parametros.crs_saida
    if crs_trabalho is None or not crs_trabalho.isValid():
        crs_trabalho = qgis_utils.crs_utm_automatico(
            moldura_original, parametros.crs_moldura
        )
    resultado.crs = crs_trabalho
    moldura = qgis_utils.transformar_geometria(
        moldura_original, parametros.crs_moldura, crs_trabalho
    )
    moldura = qgis_utils.geometria_valida(moldura)
    qgis_utils.log(
        "CRS de trabalho: %s; área da moldura: %.1f km²."
        % (crs_trabalho.authid(), moldura.area() / 1e6)
    )
    progresso(2.0)
    checar_cancelamento()

    # ------------------------------------------- Etapa 1: aquisição dados
    camadas: List[Tuple[QgsVectorLayer, str, str]] = []
    if parametros.fontes:
        bbox_geo = data_acquisition.bbox_geografica(
            moldura, crs_trabalho, parametros.buffer_bbox_m
        )
        baixadas, avisos = data_acquisition.adquirir_dados(
            parametros.ids_classes,
            parametros.fontes,
            bbox_geo,
            parametros.pasta_trabalho,
            parametros.denominador_escala,
            arquivo_open_buildings=parametros.arquivo_open_buildings,
            usar_cache=parametros.usar_cache,
            cancelado=cancelado,
            progresso=lambda i, n: progresso(2.0 + 33.0 * i / max(n, 1)),
        )
        camadas.extend(baixadas)
        resultado.avisos.extend(avisos)
    for camada, nome in parametros.camadas_locais:
        camadas.append((camada, "local:%s" % nome, "local"))
    if not camadas:
        raise RuntimeError(
            "Nenhum insumo disponível: todas as fontes falharam e não há "
            "camadas locais. Avisos: %s" % "; ".join(resultado.avisos)
        )
    progresso(35.0)
    checar_cancelamento()

    # ---------------------------------------- Etapa 2: pontos de esforço
    pontos_esforco = normalization.normalizar_camadas(
        camadas,
        parametros.d,
        crs_trabalho,
        moldura=moldura,
        callback_progresso=lambda i, n: progresso(
            35.0 + 15.0 * i / max(n, 1)
        ),
    )
    resultado.n_pontos_esforco = pontos_esforco.featureCount()
    qgis_utils.log(
        "Pontos de esforço: %d." % resultado.n_pontos_esforco
    )
    if resultado.n_pontos_esforco == 0:
        resultado.avisos.append(
            "Nenhum ponto de esforço na área: a divisão será apenas "
            "geométrica (cargas nulas)."
        )
    progresso(50.0)
    checar_cancelamento()

    # ------------------------------- Etapas 3-4 (ou grade): particionar
    if parametros.metodo == METODO_VORONOI:
        celulas_grade = density_grid.construir_grade(moldura, parametros.r)
        pesos = density_grid.contar_pontos_por_celula(
            celulas_grade, pontos_esforco
        )
        progresso(55.0)
        checar_cancelamento()
        n_geradores = max(parametros.multiplicador_n, 1) * parametros.k
        geradores = voronoi_partition.gerar_geradores(
            celulas_grade,
            pesos,
            n_geradores,
            moldura,
            fator_delta=parametros.fator_delta,
            seed=parametros.seed,
        )
        qgis_utils.log(
            "Grade auxiliar: %d células; geradores: %d (N alvo %d)."
            % (len(celulas_grade), len(geradores), n_geradores)
        )
        particao = voronoi_partition.diagrama_voronoi(
            geradores, moldura, crs_trabalho.authid()
        )
    else:
        m = parametros.fator_subdivisao_m or parametros.k
        particao = grid_partition.gerar_grade_regular(
            moldura, parametros.k, m
        )
        qgis_utils.log(
            "Grade regular: %d quadrados (m=%d, k=%d)."
            % (len(particao), m, parametros.k)
        )
    resultado.n_celulas = len(particao)
    if resultado.n_celulas < parametros.k:
        resultado.avisos.append(
            "A partição gerou %d células para k=%d áreas; alguns lotes "
            "podem sair vazios. Aumente o multiplicador/subdivisão."
            % (resultado.n_celulas, parametros.k)
        )
    progresso(70.0)
    checar_cancelamento()

    # ------------------------------------ Etapa 5: carga ponderada ci
    cargas_celulas = load_calculation.calcular_cargas(
        particao,
        pontos_esforco,
        parametros.alfa,
        parametros.beta,
        parametros.gama,
        callback_progresso=lambda i, n: progresso(
            70.0 + 10.0 * i / max(n, 1)
        ),
    )
    progresso(80.0)
    checar_cancelamento()

    # ------------------------- Etapa 6: agrupamento contíguo e delegação
    fatores = [e for _, e in parametros.operadores]
    carga_total = sum(c.carga for c in cargas_celulas.values())
    alvos = algorithms.cargas_alvo(carga_total, fatores)
    adjacencia = clustering.grafo_adjacencia(particao)
    atribuicao = algorithms.agrupamento_guloso(
        adjacencia,
        {i: c.carga for i, c in cargas_celulas.items()},
        alvos,
    )
    geometrias_lotes = clustering.dissolver_lotes(
        particao, atribuicao, parametros.k
    )
    progresso(90.0)
    checar_cancelamento()

    # ------------------------------------------------- Etapa 7: saída
    for j, (nome, ej) in enumerate(parametros.operadores):
        lote = LoteResultado(nome, ej, alvos[j] if j < len(alvos) else 0.0)
        lote.geometria = geometrias_lotes[j]
        resultado.lotes.append(lote)
    for id_celula, j in atribuicao.items():
        carga = cargas_celulas[id_celula]
        lote = resultado.lotes[j]
        lote.carga_total += carga.carga
        lote.n_pontos += carga.n_ponto
        lote.n_linhas += carga.n_linha
        lote.n_poligonos += carga.n_poligono
    for lote in resultado.lotes:
        if lote.carga_alvo > 0.0:
            lote.desvio_percentual = (
                100.0
                * (lote.carga_total - lote.carga_alvo)
                / lote.carga_alvo
            )
    resultado.cv = algorithms.coeficiente_variacao(
        [l.carga_total for l in resultado.lotes if not l.geometria.isEmpty()]
    )
    resultado.caminho_gpkg = _gravar_gpkg(
        resultado, crs_trabalho, parametros.pasta_trabalho
    )
    progresso(100.0)
    qgis_utils.log(
        "Pipeline concluído: CV = %.4f; saída em %s."
        % (resultado.cv, resultado.caminho_gpkg)
    )
    return resultado


def _gravar_gpkg(
    resultado: ResultadoPipeline,
    crs: QgsCoordinateReferenceSystem,
    pasta: str,
) -> str:
    """Grava a camada de lotes (Etapa 7) em GeoPackage."""
    campos = QgsFields()
    campos.append(QgsField("operador", QVariant.String))
    campos.append(QgsField("fator_experiencia", QVariant.Double))
    campos.append(QgsField("carga_alvo", QVariant.Double))
    campos.append(QgsField("carga_total", QVariant.Double))
    campos.append(QgsField("n_pontos", QVariant.Int))
    campos.append(QgsField("n_linhas", QVariant.Int))
    campos.append(QgsField("n_poligonos", QVariant.Int))
    campos.append(QgsField("desvio_percentual", QVariant.Double))

    camada = QgsVectorLayer(
        "MultiPolygon?crs=%s" % crs.authid(), "lotes_trabalho", "memory"
    )
    provedor = camada.dataProvider()
    provedor.addAttributes(campos.toList())
    camada.updateFields()
    feicoes = []
    for lote in resultado.lotes:
        if lote.geometria.isEmpty():
            continue
        feicao = QgsFeature(camada.fields())
        geometria = QgsGeometry(lote.geometria)
        geometria.convertToMultiType()
        feicao.setGeometry(geometria)
        feicao.setAttributes(
            [
                lote.operador,
                float(lote.fator_experiencia),
                float(lote.carga_alvo),
                float(lote.carga_total),
                int(lote.n_pontos),
                int(lote.n_linhas),
                int(lote.n_poligonos),
                float(lote.desvio_percentual),
            ]
        )
        feicoes.append(feicao)
    provedor.addFeatures(feicoes)
    camada.updateExtents()

    os.makedirs(pasta, exist_ok=True)
    marca_tempo = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(pasta, "lotes_trabalho_%s.gpkg" % marca_tempo)
    opcoes = QgsVectorFileWriter.SaveVectorOptions()
    opcoes.driverName = "GPKG"
    opcoes.layerName = "lotes_trabalho"
    gravacao = QgsVectorFileWriter.writeAsVectorFormatV3(
        camada, caminho, camada.transformContext(), opcoes
    )
    if gravacao[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(
            "Falha ao gravar o GeoPackage de saída: %s" % gravacao[1]
        )
    return caminho


class PipelineTask(QgsTask):
    """Tarefa em segundo plano que executa o pipeline completo.

    O resultado fica em ``self.resultado`` (ou ``self.erro``); o sinal
    ``concluido`` é emitido no thread principal por ``finished``.
    """

    concluido = pyqtSignal(bool)

    def __init__(self, parametros: ParametrosPipeline):
        super().__init__(
            "Divisão balanceada de áreas de trabalho (SAP)",
            QgsTask.CanCancel,
        )
        self.parametros = parametros
        self.resultado: Optional[ResultadoPipeline] = None
        self.erro: Optional[str] = None

    def run(self):  # noqa: D102 - contrato QgsTask
        try:
            self.resultado = executar_pipeline(
                self.parametros,
                progresso=self.setProgress,
                cancelado=self.isCanceled,
            )
            return True
        except InterruptedError:
            self.erro = "Execução cancelada pelo usuário."
            return False
        except Exception as exc:  # noqa: BLE001 - reportado ao usuário
            self.erro = "%s" % exc
            qgis_utils.log(traceback.format_exc())
            return False

    def finished(self, ok):  # noqa: D102 - contrato QgsTask
        self.concluido.emit(bool(ok and self.resultado is not None))
