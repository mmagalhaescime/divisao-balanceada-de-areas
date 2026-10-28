# -*- coding: utf-8 -*-
"""Fixtures compartilhadas dos testes.

Os testes de lógica pura rodam em qualquer Python; os que dependem do
QGIS usam a fixture ``qgis_app`` (que pula o teste quando o módulo
``qgis`` não está disponível). Para rodar a suíte completa no Windows::

    "C:/Program Files/QGIS 3.34.3/bin/python-qgis.bat" -m pytest
"""

import os
import sys

import pytest


@pytest.fixture(scope="session")
def qgis_app():
    """Inicializa o QGIS (headless) uma única vez por sessão de testes."""
    pytest.importorskip("qgis")
    from qgis.core import QgsApplication

    # GUI habilitada (True) para permitir testes dos diálogos PyQt;
    # nenhuma janela é exibida (os testes não chamam show()/exec_()).
    app = QgsApplication([], True)
    app.initQgis()

    # Em execução standalone (fora do QGIS Desktop) o pacote `processing`
    # não está no sys.path; ele mora em <prefixo>/python/plugins.
    caminho_plugins = os.path.join(
        QgsApplication.prefixPath(), "python", "plugins"
    )
    if caminho_plugins not in sys.path:
        sys.path.insert(0, caminho_plugins)

    # Inicializa o framework Processing (algoritmos native:*).
    import processing  # noqa: F401  (registra o provedor ao importar)
    from processing.core.Processing import Processing

    Processing.initialize()
    yield app
    app.exitQgis()
