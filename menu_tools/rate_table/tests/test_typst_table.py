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
    # one number for legs of differing thresholds: cannot be matched, keep
    assert tt._fix_name_thresholds("DoubleTkMu4er2p0_SQ", [6, 7], "x") == "DoubleTkMu4er2p0_SQ"
    # name numbers that cannot be matched to the legs one to one, keep
    assert tt._fix_name_thresholds("TkMu7_TkEle20", [9, 24, 5], "x") == "TkMu7_TkEle20"
    # an unknown threshold keeps the name untouched
    assert tt._fix_name_thresholds("DoubleTkMu_HTSum", [5, None, 305], "x") == "DoubleTkMu_HTSum"
    # legs that cannot be matched to the object parts, keep
    assert tt._fix_name_thresholds("DoubleTkMu_HTSum", [5, 305], "x") == "DoubleTkMu_HTSum"


def test_fix_name_thresholds_adds_missing():
    # thresholds attached to their object segment, like `TkMu6_HTSum240`
    assert tt._fix_name_thresholds("DoubleTkMu_HTSum", [5, 5, 305], "x") == "DoubleTkMu5_HTSum305"
    assert tt._fix_name_thresholds("HTSum", [378], "x") == "HTSum378"
    # one number for legs of equal threshold, like `DoubleTkMu4er2p0`
    assert tt._fix_name_thresholds("TripleTkMu", [5, 5, 5], "x") == "TripleTkMu5"
    # legs of differing thresholds keep one number each
    assert tt._fix_name_thresholds("DoubleIsoTau_Jet", [58, 56, 103], "x") == "DoubleIsoTau58_56_Jet103"
    # suffix segments name no leg
    assert tt._fix_name_thresholds("SingleTkMu_Barrel", [13], "x") == "SingleTkMu13_Barrel"
    assert (
        tt._fix_name_thresholds("DoubleJet_Mass_Min1000", [145, 70], "x")
        == "DoubleJet145_70_Mass_Min1000"
    )
    # thresholds keep their "p" form
    assert tt._fix_name_thresholds("DoubleTkMu", [2.5, 2.5], "x") == "DoubleTkMu2p5"


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


def test_online_cells_one_decimal():
    # (offline, is_online, barrel, endcap)
    thresholds = [("23", False, "18.5", "16.4"), ("30", False, "24.7", "21.9")]
    assert tt._online_cells(thresholds) == ("[18.5, 24.7]", "[16.4, 21.9]")
    # missing scaling and unparsed legs
    thresholds = [("--", False, "--", "--"), ("12", False, "8.8", "--")]
    assert tt._online_cells(thresholds) == ("[--, 8.8]", "[--, --]")


def test_online_cut_legs_own_threshold():
    # a leg cutting on the online pT is its own threshold in both columns
    thresholds = [("5", True, "5.0", "5.0")]
    assert tt._online_cells(thresholds) == ("[5.0]", "[5.0]")
    assert tt._thresholds_cell(thresholds) == "[$5^dagger$]"
