# -*- coding: utf-8 -*-
"""Testes da interface gráfica (widgets reais, sem exibir janelas)."""

import pytest

pytest.importorskip("qgis")

from qgis.PyQt.QtCore import Qt  # noqa: E402


@pytest.fixture
def dialogo(qgis_app):
    from balanced_work_areas.gui.main_dialog import DialogoPrincipal

    janela = DialogoPrincipal()
    yield janela
    janela.close()
    janela.deleteLater()


def test_dialogo_tem_tres_abas(dialogo):
    assert dialogo.abas.count() == 3
    assert dialogo.abas.tabText(0) == "Área e divisão"
    assert dialogo.abas.tabText(1) == "Dados de entrada"
    assert dialogo.abas.tabText(2) == "Parâmetros"


def test_k_sincroniza_tabela_operadores(dialogo):
    assert dialogo.tabela_operadores.rowCount() == dialogo.spin_k.value()
    dialogo.spin_k.setValue(6)
    assert dialogo.tabela_operadores.rowCount() == 6
    assert dialogo.tabela_operadores.item(5, 0).text() == "Operador 6"


def test_m_acompanha_k_ate_edicao_manual(dialogo):
    dialogo.spin_k.setValue(5)
    assert dialogo.spin_m.value() == 5
    dialogo.spin_m.setValue(9)  # edição manual
    dialogo.spin_k.setValue(7)
    assert dialogo.spin_m.value() == 9  # não volta a acompanhar


def test_metodo_alterna_pagina_de_parametros(dialogo):
    dialogo.combo_metodo.setCurrentIndex(0)
    assert dialogo.pilha_metodo.currentIndex() == 0
    dialogo.combo_metodo.setCurrentIndex(1)
    assert dialogo.pilha_metodo.currentIndex() == 1


def test_escala_preenche_defaults_d_r(dialogo):
    indice_100k = 2  # 1:100.000
    dialogo.combo_escala.setCurrentIndex(indice_100k)
    assert dialogo.spin_d.value() == pytest.approx(200.0)
    assert dialogo.spin_r.value() == pytest.approx(1000.0)


def test_arvore_classes_padrao_marcadas(dialogo):
    ids = dialogo.ids_classes_marcadas()
    assert "edificacoes" in ids
    assert "vias_rodoviarias" in ids
    assert "economia_ponto" not in ids  # não é padrão


def test_arvore_classes_desmarcar(dialogo):
    raiz = dialogo.arvore_classes.topLevelItem(0)
    for i in range(raiz.childCount()):
        raiz.child(i).setCheckState(0, Qt.Unchecked)
    ids = dialogo.ids_classes_marcadas()
    assert all(
        classe not in ids
        for classe in ("localidades_ponto", "relevo_pontos_cotados")
    )


def test_zerar_ponderacao(dialogo):
    dialogo.spin_k.setValue(3)
    dialogo.tabela_operadores.cellWidget(1, 1).setValue(3.5)
    dialogo._zerar_ponderacao()
    assert dialogo.tabela_operadores.cellWidget(1, 1).value() == 1.0


def test_montar_parametros_sem_moldura_erro(dialogo):
    # Projeto vazio → combo de moldura sem camada selecionada.
    with pytest.raises(ValueError):
        dialogo.montar_parametros()


def test_definir_execucao_alterna_controles(dialogo):
    dialogo.definir_execucao(True)
    assert not dialogo.botao_executar.isEnabled()
    assert dialogo.botao_cancelar.isEnabled()
    assert not dialogo.abas.isEnabled()
    dialogo.definir_execucao(False)
    assert dialogo.botao_executar.isEnabled()
    assert not dialogo.botao_cancelar.isEnabled()


def test_dialogo_resultados_tabela_e_cv(qgis_app):
    from balanced_work_areas.core.pipeline import (
        LoteResultado,
        ResultadoPipeline,
    )
    from balanced_work_areas.gui.results_dialog import DialogoResultados

    resultado = ResultadoPipeline()
    resultado.metodo = "grade"
    resultado.n_celulas = 16
    resultado.n_pontos_esforco = 100
    resultado.cv = 0.1234
    for nome, alvo, total in (("A", 50.0, 52.0), ("B", 50.0, 48.0)):
        lote = LoteResultado(nome, 1.0, alvo)
        lote.carga_total = total
        lote.desvio_percentual = 100.0 * (total - alvo) / alvo
        resultado.lotes.append(lote)

    janela = DialogoResultados(resultado)
    assert janela.tabela.rowCount() == 2
    assert janela.tabela.item(0, 0).text() == "A"
    assert janela.tabela.item(1, 3).text() == "48.0"
    janela.close()
    janela.deleteLater()


def test_class_factory_instancia_plugin(qgis_app):
    """O ponto de entrada do plugin funciona com uma iface mínima."""
    import balanced_work_areas as pacote

    class IfaceFalsa:
        def mainWindow(self):
            return None

    plugin = pacote.classFactory(IfaceFalsa())
    assert plugin is not None
    assert hasattr(plugin, "initGui")
    assert hasattr(plugin, "unload")
