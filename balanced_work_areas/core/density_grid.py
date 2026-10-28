# -*- coding: utf-8 -*-
"""Etapa 3 — Grade auxiliar de densidade.

Grade regular de resolução ``r`` sobre a moldura; a contagem de pontos de
esforço por célula produz o mapa de pesos W = {wi} usado na alocação de
geradores do Voronoi adaptativo (Etapa 4).
"""

import math
from typing import Dict, List

from qgis.core import (
    QgsFeatureRequest,
    QgsGeometry,
    QgsRectangle,
    QgsSpatialIndex,
    QgsVectorLayer,
)


class CelulaGrade:
    """Célula da grade auxiliar (retângulo alinhado aos eixos)."""

    __slots__ = ("id", "retangulo", "geometria")

    def __init__(self, id_celula: int, retangulo: QgsRectangle):
        self.id = id_celula
        self.retangulo = retangulo
        self.geometria = QgsGeometry.fromRect(retangulo)


def construir_grade(moldura: QgsGeometry, r: float) -> List[CelulaGrade]:
    """Gera as células de resolução ``r`` que intersectam a moldura.

    :param moldura: geometria da moldura no CRS de trabalho (métrico).
    :param r: resolução da grade em metros.
    :returns: lista de células (ids sequenciais a partir de 0).
    :raises ValueError: para parâmetros/geometria degenerados.
    """
    if r <= 0.0:
        raise ValueError("Resolução r deve ser positiva.")
    extensao = moldura.boundingBox()
    if extensao.isEmpty():
        raise ValueError("Moldura com extensão vazia.")
    ncols = max(1, int(math.ceil(extensao.width() / r)))
    nlins = max(1, int(math.ceil(extensao.height() / r)))
    motor = QgsGeometry.createGeometryEngine(moldura.constGet())
    motor.prepareGeometry()
    celulas: List[CelulaGrade] = []
    proximo_id = 0
    for lin in range(nlins):
        for col in range(ncols):
            retangulo = QgsRectangle(
                extensao.xMinimum() + col * r,
                extensao.yMinimum() + lin * r,
                min(extensao.xMinimum() + (col + 1) * r, extensao.xMaximum()),
                min(extensao.yMinimum() + (lin + 1) * r, extensao.yMaximum()),
            )
            geometria = QgsGeometry.fromRect(retangulo)
            if motor.intersects(geometria.constGet()):
                celulas.append(CelulaGrade(proximo_id, retangulo))
                proximo_id += 1
    return celulas


def contar_pontos_por_celula(
    celulas: List[CelulaGrade], camada_pontos: QgsVectorLayer
) -> Dict[int, float]:
    """Conta pontos de esforço por célula → mapa de pesos W = {wi}.

    Como as células são retângulos alinhados aos eixos, o teste de
    bounding box do índice espacial já é exato para pontos.

    :returns: dicionário ``id da célula -> peso`` (contagem, >= 0).
    """
    indice = QgsSpatialIndex(
        camada_pontos.getFeatures(
            QgsFeatureRequest().setNoAttributes()
        )
    )
    pesos: Dict[int, float] = {}
    for celula in celulas:
        pesos[celula.id] = float(len(indice.intersects(celula.retangulo)))
    return pesos
