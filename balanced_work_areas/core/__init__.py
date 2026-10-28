# -*- coding: utf-8 -*-
"""Módulos de núcleo (core) do plugin Divisão Balanceada de Áreas.

Organização por etapa metodológica:

- ``algorithms``        — algoritmos puros (sem dependência de QGIS);
- ``edgv_classes``      — catálogo de classes ET-EDGV e mapeamento para fontes;
- ``data_acquisition``  — download e pré-processamento de dados abertos;
- ``normalization``     — conversão de geometrias para pontos de esforço;
- ``density_grid``      — grade auxiliar e estimativa de densidade;
- ``voronoi_partition`` — geração adaptativa do Voronoi ponderado;
- ``grid_partition``    — divisão alternativa por grade regular;
- ``load_calculation``  — cálculo de carga ponderada por célula;
- ``clustering``        — agrupamento contíguo e delegação de lotes;
- ``pipeline``          — orquestração das etapas em ``QgsTask``.

Os módulos que dependem do QGIS importam ``qgis.*`` no topo; ``algorithms``
e ``edgv_classes`` são Python puro para permitir testes fora do QGIS.
"""
