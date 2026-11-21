import pytest

from menu_tools.rate_table import typst_table as tt


@pytest.mark.parametrize(
    "name, expected",
    [
        # thresholds attached to an object name
        ("TkMu12_HTSum150", [(4, 6, 12.0), (12, 15, 150.0)]),
        ("TkMu7_TkEle20", [(4, 5, 7.0), (11, 13, 20.0)]),
        ("HTSum240", [(5, 8, 240.0)]),
        # threshold before "er" is a threshold, the number after it is not
        ("DoubleTkMu0er1p4_SQ_OS_dR_Max1p4", [(10, 11, 0.0)]),
        ("DoubleTkMu4er2p0_SQ_OS_dR_Max1p6", [(10, 11, 4.0)]),
        # bare threshold segments
        ("TripleTkMu_4_2p5_0_OS_Mass_Max12", [(11, 12, 4.0), (13, 16, 2.5), (17, 18, 0.0)]),
        # no thresholds embedded
        ("DoubleJet_Mass_Min250_dEta_Max1p5", []),
        ("DoubleTkEle_er1p2_dR_Max0p6", []),
        ("SingleTkMu_Barrel", []),
        ("DoubleIsoTau_Jet", []),
    ],
)
def test_name_threshold_tokens(name, expected):
    assert tt._name_threshold_tokens(name) == expected


def test_fix_name_thresholds_renames():
    # the user's example: L1_TkMu12_HTSum150 has thresholds 15 and 219
    assert (
        tt._fix_name_thresholds("TkMu12_HTSum150", [15, 219], "L1_TkMu12_HTSum150")
        == "TkMu15_HTSum219"
    )
    # one name number for legs of equal threshold
    assert (
        tt._fix_name_thresholds("DoubleTkMu4er2p0_SQ_OS_dR_Max1p6", [6, 6], "x")
        == "DoubleTkMu6er2p0_SQ_OS_dR_Max1p6"
    )
    # several name numbers, matched leg by leg, 2.5 keeps its "p" form
    assert (
        tt._fix_name_thresholds("TripleTkMu_4_2p5_0_OS_Mass_Max12", [6, 4, 1], "x")
        == "TripleTkMu_6_4_1_OS_Mass_Max12"
    )


def test_fix_name_thresholds_keeps_names():
    # agrees with the menu definition
    assert tt._fix_name_thresholds("TkMu15_HTSum219", [15, 219], "x") == "TkMu15_HTSum219"
    # no thresholds in the name
    assert tt._fix_name_thresholds("DoubleTkMu_HTSum", [5, 5, 305], "x") == "DoubleTkMu_HTSum"
    # one number for legs of differing thresholds: cannot be matched, keep
    assert tt._fix_name_thresholds("DoubleTkMu4er2p0_SQ", [6, 7], "x") == "DoubleTkMu4er2p0_SQ"
    # name numbers that cannot be matched to the legs one to one, keep
    assert tt._fix_name_thresholds("TkMu7_TkEle20", [9, 24, 5], "x") == "TkMu7_TkEle20"


def test_fix_name_thresholds_compressed_legs():
    # one name number covers any set of equal-threshold legs
    assert (
        tt._fix_name_thresholds("DoubleTkMu4er2p0_SQ", [6, 6, 6], "x")
        == "DoubleTkMu6er2p0_SQ"
    )


def test_fill_expr():
    assert tt._fill_expr("blue", "x") == "blue.transparentize(85%)"
    assert tt._fill_expr("#3366cc", "x") == 'rgb("#3366cc").transparentize(85%)'
    assert tt._fill_expr("blue-ish!", "x") is None
    assert tt._fill_expr(None, "x") is None


def test_cell_wrapping():
    assert tt._cell("[1, 1]", None) == "[1, 1]"
    assert tt._cell("[1, 1]", "blue.transparentize(85%)") == (
        "table.cell(fill: blue.transparentize(85%))[1, 1]"
    )
    assert tt._cell("`TkMu9`", "blue.transparentize(85%)") == (
        "table.cell(fill: blue.transparentize(85%))[`TkMu9`]"
    )
