# -*- coding: utf-8 -*-
"""Método alternativo — divisão por grade regular de quadrados.

Divide a moldura em ~``m x k`` quadrados (m = fator de subdivisão,
padrão m = k), recortados pelo contorno (quadrados de borda podem ser
parciais). A complexidade de cada quadrado usa exatamente a mesma métrica
do método principal (pontos de esforço + pesos alfa/beta/gama) e a
aglutinação em k áreas reutiliza o agrupamento guloso contíguo com
adjacência rook (``core.clustering`` / ``core.algorithms``).
"""

import math
from typing import List

from qgis.core import QgsGeometry, QgsRectangle

from . import qgis_utils


def gerar_grade_regular(
    moldura: QgsGeometry, k: int, m: int
) -> List[QgsGeometry]:
    """Gera os quadrados da grade regular recortados pela moldura.

    O lado do quadrado é escolhido para que a caixa envolvente da moldura
    contenha aproximadamente ``m*k`` quadrados; a grade cobre toda a
    caixa e cada quadrado é recortado pelo contorno da moldura.

    :param moldura: geometria da moldura no CRS de trabalho (métrico).
    :param k: número de áreas de trabalho finais.
    :param m: fator de subdivisão (número de quadrados por área final).
    :returns: lista de geometrias (quadrados, possivelmente parciais).
    :raises ValueError: para parâmetros inválidos.
    """
    if k < 2:
        raise ValueError("k deve ser >= 2.")
    if m < 1:
        raise ValueError("Fator de subdivisão m deve ser >= 1.")
    extensao = moldura.boundingBox()
    if extensao.isEmpty():
        raise ValueError("Moldura com extensão vazia.")
    n_quadrados = m * k
    lado = math.sqrt(
        (extensao.width() * extensao.height()) / float(n_quadrados)
    )
    ncols = max(1, int(math.ceil(extensao.width() / lado)))
    nlins = max(1, int(math.ceil(extensao.height() / lado)))
    motor = QgsGeometry.createGeometryEngine(moldura.constGet())
    motor.prepareGeometry()
    quadrados: List[QgsGeometry] = []
    for lin in range(nlins):
        for col in range(ncols):
            retangulo = QgsRectangle(
                extensao.xMinimum() + col * lado,
                extensao.yMinimum() + lin * lado,
                extensao.xMinimum() + (col + 1) * lado,
                extensao.yMinimum() + (lin + 1) * lado,
            )
            geometria = QgsGeometry.fromRect(retangulo)
            if not motor.intersects(geometria.constGet()):
                continue
            recorte = qgis_utils.geometria_valida(
                geometria.intersection(moldura)
            )
            if not recorte.isEmpty() and recorte.area() > 0.0:
                quadrados.append(recorte)
    return quadrados
