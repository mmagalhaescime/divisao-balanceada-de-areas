# -*- coding: utf-8 -*-
"""Divisão Balanceada de Áreas — plugin QGIS de apoio ao SAP/DSG (pacote balanced_work_areas).

Pacote do plugin QGIS. Este módulo expõe apenas o ponto de entrada
``classFactory`` exigido pela infraestrutura de plugins do QGIS.

Autores: Matheus Magalhães Cardoso, Bruno Lixandrão Silvestre,
Giovana Baroni Cadorin.
Licença: GPL-2.0-or-later (ver arquivo LICENSE na raiz do repositório).
"""


def classFactory(iface):  # pylint: disable=invalid-name
    """Ponto de entrada padrão de plugins QGIS.

    Chamado pelo QGIS ao carregar o plugin. A importação da classe
    principal é feita aqui dentro (e não no topo do módulo) para que o
    custo de import só ocorra quando o plugin é de fato ativado.

    :param iface: interface do QGIS (``qgis.gui.QgisInterface``).
    :returns: instância da classe principal do plugin.
    """
    from .balanced_work_areas import BalancedWorkAreas

    return BalancedWorkAreas(iface)
