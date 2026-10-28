# -*- coding: utf-8 -*-
"""Utilitários QGIS compartilhados (log, CRS, geometria, camadas)."""

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsMessageLog,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from .algorithms import detectar_fuso_utm

NOME_LOG = "Divisão Balanceada de Áreas"

# CRS geográfico de referência para detecção de fuso (SIRGAS 2000).
EPSG_SIRGAS_GEOGRAFICO = 4674


def log(mensagem: str, nivel=Qgis.Info) -> None:
    """Registra mensagem na aba própria do plugin no log do QGIS."""
    QgsMessageLog.logMessage(str(mensagem), NOME_LOG, nivel)


def crs_utm_automatico(
    geometria_moldura: QgsGeometry,
    crs_moldura: QgsCoordinateReferenceSystem,
) -> QgsCoordinateReferenceSystem:
    """Detecta o CRS SIRGAS 2000 / UTM pelo centroide da moldura.

    :param geometria_moldura: geometria (no CRS original da camada).
    :param crs_moldura: CRS original da camada de moldura.
    :returns: ``QgsCoordinateReferenceSystem`` EPSG:31978..31985.
    """
    centroide = geometria_moldura.centroid()
    sirgas = QgsCoordinateReferenceSystem.fromEpsgId(
        EPSG_SIRGAS_GEOGRAFICO
    )
    transformacao = QgsCoordinateTransform(
        crs_moldura, sirgas, QgsProject.instance()
    )
    ponto = transformacao.transform(centroide.asPoint())
    _, epsg = detectar_fuso_utm(ponto.x(), ponto.y())
    return QgsCoordinateReferenceSystem.fromEpsgId(epsg)


def transformar_geometria(
    geometria: QgsGeometry,
    crs_origem: QgsCoordinateReferenceSystem,
    crs_destino: QgsCoordinateReferenceSystem,
) -> QgsGeometry:
    """Retorna cópia da geometria transformada entre CRSs."""
    copia = QgsGeometry(geometria)
    if crs_origem != crs_destino:
        transformacao = QgsCoordinateTransform(
            crs_origem, crs_destino, QgsProject.instance()
        )
        copia.transform(transformacao)
    return copia


def geometria_valida(geometria: QgsGeometry) -> QgsGeometry:
    """Aplica ``makeValid`` quando necessário (insumos podem ser inválidos)."""
    if geometria.isNull() or geometria.isEmpty():
        return geometria
    if geometria.isGeosValid():
        return geometria
    return geometria.makeValid()


def moldura_unificada(
    camada: QgsVectorLayer, apenas_selecionadas: bool = False
) -> QgsGeometry:
    """União (dissolve) das feições da camada de moldura.

    :param camada: camada de polígonos da moldura.
    :param apenas_selecionadas: usar somente as feições selecionadas.
    :returns: geometria única (possivelmente multipolígono, com buracos
        preservados), já validada com ``makeValid``.
    :raises ValueError: se não houver feições utilizáveis.
    """
    if apenas_selecionadas:
        feicoes = list(camada.selectedFeatures())
    else:
        feicoes = list(camada.getFeatures())
    geometrias = [
        geometria_valida(f.geometry())
        for f in feicoes
        if f.hasGeometry() and not f.geometry().isEmpty()
    ]
    geometrias = [g for g in geometrias if not g.isEmpty()]
    if not geometrias:
        raise ValueError(
            "A camada de moldura não possui feições utilizáveis"
            + (" (nenhuma feição selecionada)." if apenas_selecionadas else ".")
        )
    uniao = QgsGeometry.unaryUnion(geometrias)
    return geometria_valida(uniao)


def criar_camada_pontos_esforco(
    crs: QgsCoordinateReferenceSystem,
) -> QgsVectorLayer:
    """Cria a camada (memória) unificada de pontos de esforço (Etapa 2)."""
    camada = QgsVectorLayer(
        "Point?crs=%s" % crs.authid(), "pontos_esforco", "memory"
    )
    provedor = camada.dataProvider()
    campos = QgsFields()
    campos.append(QgsField("tipo_primitiva", QVariant.String))
    campos.append(QgsField("classe_edgv", QVariant.String))
    campos.append(QgsField("fonte", QVariant.String))
    provedor.addAttributes(campos.toList())
    camada.updateFields()
    return camada


def adicionar_pontos(
    camada: QgsVectorLayer, pontos, tipo: str, classe: str, fonte: str
) -> None:
    """Acrescenta pontos de esforço à camada unificada.

    :param pontos: iterável de ``QgsPointXY``.
    :param tipo: primitiva de origem ('ponto' | 'linha' | 'poligono').
    :param classe: identificador da classe ET-EDGV.
    :param fonte: nome da fonte de dados.
    """
    provedor = camada.dataProvider()
    feicoes = []
    for p in pontos:
        f = QgsFeature(camada.fields())
        f.setGeometry(QgsGeometry.fromPointXY(p))
        f.setAttributes([tipo, classe, fonte])
        feicoes.append(f)
    if feicoes:
        provedor.addFeatures(feicoes)
        camada.updateExtents()
