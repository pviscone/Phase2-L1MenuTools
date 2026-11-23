"""Write the Typst version of the menu table next to a rate table CSV.

Two tables are written per CSV: `<name>.typ` with the online-thresholds
columns, and `<name>_no_online.typ` without them.

`rate_table` writes them automatically for every rate CSV; they can also be
(re)generated on their own:

    rate_table_typst configs/V50nano/rate_table/step1p5_cfg.yml --version V50nano

The content is derived from three inputs:

* the menu definition (``*_menu_cfg.yml``): the thresholds and the
  "additional requirements" are read off the seed definitions and the object
  configs, so a retuned threshold needs no change anywhere else;
* the per-menu layout (``*_table_layout.yml``, the same file `rate_table_tex`
  uses): section order, object-level requirements (e.g. an ID score cut) and
  any hand-written `thresholds`/`requirements`/`extra_requirements` overrides;
* the rate CSV written by `rate_table`.

Besides the offline thresholds, two columns give the online (hardware) pT
threshold of each leg, obtained by inverting the online-to-offline scaling
(``offline_pt = slope * pt + offset``) of the leg object in the barrel and the
endcap, shown with one decimal. Objects without a regional scaling (the sums)
fall back to their inclusive one. Legs cutting on the online `pt` directly keep
a $dagger$ in the offline column and are their own online threshold.
"""
import argparse
import math
import os
import re
import warnings
from typing import Optional

import pandas as pd
import yaml

from menu_tools.rate_table.menu_config import MenuConfig

# Marks a threshold that is applied on the online pT, without the
# online-to-offline scaling.
DAGGER = "^dagger"

# Subscripts of mass and deltaR requirements between legs of different objects
OBJECT_SYMBOLS = {
    "L1gmtTkMuon": "mu",
    "L1gmtDispMuon": "mu",
    "L1tkElectron": "e",
    "L1EG": "e",
    "L1tkPhoton": "gamma",
    "L1caloTau": "tau",
    "L1nnPuppiTau": "tau",
    "L1nnCaloTau": "tau",
    "L1puppiJetSC4": "j",
    "L1puppiExtJetSC4": "j",
    "L1puppiJetSC4NG": "j",
    "L1puppiJetSC8": "J",
}

# Objects that only carry event-level information and never form a column entry
NON_PHYSICS_OBJECTS = {"L1PV"}

# Per-object defaults (eta bounds, ID requirements); the layout's `objects`
# block overrides them.
DEFAULT_OBJECTS: dict[str, dict] = {
    "L1gmtTkMuon": {"max_eta": 2.4},
    "L1gmtDispMuon": {"max_eta": 2.4},
    "L1nnPuppiTau": {"requirement": "NN score $> 0.22$"},
}

# Ancillary seeds not in the simplified menu, added to the second total line
ANCILLARY_MARGIN = 0.3

TABLE_LABEL = "tab:l1_menu"

# LaTeX macros of the layout strings that need a Typst rendering
_TEXT_MACROS = {
    "ETmiss": '$E_T^"miss"$',
    "ETm": '$E_T^"miss"$',
    "MET": '$E_T^"miss"$',
    "MHT": '$H_T^"miss"$',
    "HT": "$H_T$",
    "ET": "$E_T$",
    "PT": "$p_T$",
    "pt": "$p_T$",
    "mT": "$m_T$",
    "Lone": "L1",
}


def _typst_text(text: str) -> str:
    """Translate the LaTeX macros used in layout strings (section names, ...)
    to Typst."""
    return re.sub(
        r"\\(" + "|".join(_TEXT_MACROS) + r")\b",
        lambda m: _TEXT_MACROS[m.group(1)],
        str(text),
    )


def _fmt_num(value: float) -> str:
    """12.0 -> '12', 2.172 -> '2.172'."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _fmt_eta(value: float) -> str:
    """Like _fmt_num but keeping one decimal: 2 -> '2.0', 2.4 -> '2.4'."""
    text = _fmt_num(value)
    return text + ".0" if "." not in text else text


def _fmt_rate(rate: Optional[float]) -> str:
    """0.8 -> '0.8', 22.8 -> '23', missing -> '--'."""
    if rate is None or (isinstance(rate, float) and math.isnan(rate)):
        return "--"
    if rate == 0:
        return "0"
    decimals = 0 if rate >= 1 else 1
    while round(rate, decimals) == 0:
        decimals += 1
    return f"{rate:.{decimals}f}"


def _fmt_khz(rate: Optional[float]) -> str:
    """Whole-kHz cell content, e.g. '342 kHz'."""
    if rate is None or (isinstance(rate, float) and math.isnan(rate)):
        return "--"
    return f"{int(rate)} kHz"


###########################################################################
# Deriving thresholds and requirements from the menu definition
###########################################################################

_THRESHOLD_RE = re.compile(r"^\s*(?:leg\d+\.)?(offline_pt|pt)\s*(>=|>)\s*(-?[\d.]+)\s*$")


def parse_threshold(cut: Optional[str]) -> Optional[tuple[float, bool]]:
    """Parse a leg `threshold_cut`.

    Returns:
        (value, is_online) or None if the cut is not a plain pT threshold.
    """
    if cut is None:
        return None
    match = _THRESHOLD_RE.match(str(cut))
    if not match:
        return None
    return float(match.group(3)), match.group(1) == "pt"


def online_threshold(
    obj_key: str,
    value: float,
    version: str,
    region: str,
    scalings_version: Optional[str] = None,
    decimals: Optional[int] = None,
) -> Optional[float]:
    """Online (hardware) pT whose scaled value is `value`, i.e. the inverse of
    `offline_pt = slope * pt + offset` for the leg object in `region`
    ("barrel"/"endcap").

    The scaling of `region` is used, falling back to the inclusive one for
    objects without a scaling for `region` (e.g. the sums).
    """
    try:
        # Imported lazily: pulls in awkward, which the tests do not need.
        from menu_tools.utils.objects import Object
        from menu_tools.utils.scalings import load_scaling_params

        obj = Object(obj_key, version)
        # The scaling file is keyed by region: load it for `region` even when
        # the leg's own key names a different eta range.
        base = ":".join(obj_key.split(":")[:2])
        for eta_range in dict.fromkeys([region, "inclusive"]):
            if eta_range not in obj.eta_ranges:
                continue
            slope, offset = load_scaling_params(
                Object(f"{base}:{eta_range}", version),
                eta_range,
                scalings_version,
                decimals,
            )
            break
        else:
            raise UserWarning(f"no `{region}` scaling")
    except Exception as exc:  # scaling file missing, object config missing, ...
        warnings.warn(f"No scalings for `{obj_key}` ({exc}), no online threshold")
        return None
    # A threshold below the scaling offset maps to a negative pT, i.e. no cut
    return max(0.0, (value - offset) / slope)


def _fmt_online(value: Optional[float]) -> str:
    """Online threshold with one decimal: 18.53 -> '18.5', missing -> '--'."""
    return "--" if value is None else f"{value:.1f}"


def _object_max_eta(obj_key: str, version: str, objects_cfg: dict) -> Optional[float]:
    """Tightest |eta| bound implied by the object definition itself (ID cuts
    and eta-region suffix), or by `max_eta` in the layout's `objects` block."""
    bounds = []
    nano_name = obj_key.split(":")[0]
    if objects_cfg.get(nano_name, {}).get("max_eta") is not None:
        bounds.append(float(objects_cfg[nano_name]["max_eta"]))
    try:
        # Imported lazily: pulls in awkward, which the tests do not need.
        from menu_tools.utils.objects import Object

        obj = Object(obj_key, version)
        for cut in (obj.cuts or {}).get("inclusive", []):
            for val in re.findall(r"abs\(\{eta\}\)\s*<\s*([\d.]+)", cut):
                bounds.append(float(val))
    except Exception as exc:  # object config missing, awkward missing, ...
        warnings.warn(f"Could not load object `{obj_key}` for eta cuts: {exc}")
    # |eta| < 7 is the framework's "no cut"
    bounds = [b for b in bounds if b < 7]
    return min(bounds) if bounds else None


# Each pattern maps a cross-mask fragment to a (kind, payload) item.
_LEG = r"leg(\d+)"
_NUM = r"(-?[\d.]+)"
_CROSS_PATTERNS = [
    ("eta", re.compile(rf"abs\(\s*{_LEG}\.eta\s*\)\s*<\s*{_NUM}")),
    ("dz", re.compile(rf"abs\(\s*{_LEG}\.z0\s*-\s*{_LEG}\.z0\s*\)\s*<\s*{_NUM}")),
    ("deta", re.compile(rf"abs\(\s*{_LEG}\.eta\s*-\s*{_LEG}\.eta\s*\)\s*<\s*{_NUM}")),
    ("dr_max", re.compile(rf"{_LEG}\.deltaR\(\s*{_LEG}\s*\)\s*<\s*{_NUM}")),
    ("dr_min", re.compile(rf"{_LEG}\.deltaR\(\s*{_LEG}\s*\)\s*>\s*{_NUM}")),
    ("mass_min", re.compile(rf"\(\s*((?:{_LEG}\s*\+\s*)+{_LEG})\s*\)\.mass\s*>\s*{_NUM}")),
    ("mass_max", re.compile(rf"\(\s*((?:{_LEG}\s*\+\s*)+{_LEG})\s*\)\.mass\s*<\s*{_NUM}")),
    ("os", re.compile(rf"{_LEG}\.charge\s*\*\s*{_LEG}\.charge\s*<\s*0(?:\.0*)?")),
    ("os3", re.compile(r"abs\(\s*leg\d+\.charge\s*\+\s*leg\d+\.charge\s*\+\s*leg\d+\.charge\s*\)\s*==\s*1(?:\.0*)?")),
    ("btag", re.compile(rf"\(\s*(?:{_LEG}\.btagscore\s*\+?\s*)+\)\s*>\s*{_NUM}", re.IGNORECASE)),
]


def _mask_items(mask: str) -> tuple[list[tuple], bool]:
    """Find all recognised conditions in one cross-mask string.

    Returns:
        items: list of (kind, value, legs) tuples
        fully_parsed: False if the mask contains something not understood
    """
    items = []
    leftover = mask
    for kind, pattern in _CROSS_PATTERNS:
        for match in pattern.finditer(mask):
            groups = match.groups()
            value = None
            legs: tuple = ()
            if kind == "eta":
                legs, value = (groups[0],), float(groups[1])
            elif kind in ("dz", "deta", "dr_max", "dr_min"):
                legs, value = (groups[0], groups[1]), float(groups[2])
            elif kind in ("mass_min", "mass_max"):
                legs, value = tuple(re.findall(r"leg(\d+)", groups[0])), float(groups[-1])
            elif kind == "btag":
                value = float(groups[-1])
            elif kind == "os":
                legs = (groups[0], groups[1])
            items.append((kind, value, legs))
            leftover = leftover.replace(match.group(0), "")
    # Anything but brackets, boolean operators and whitespace left -> not understood
    fully_parsed = re.sub(r"[()&|\s]", "", leftover) == ""
    return items, fully_parsed


def _mass_sub(legs: tuple, leg_symbols: dict[str, str]) -> str:
    """'_(mu mu mu)' for legs of the same object, conventional '_"jj"' for
    dijets, '' if a symbol is unknown."""
    symbols = [leg_symbols.get(leg, "") for leg in legs]
    if not all(symbols):
        return ""
    if set(symbols) == {"j"}:
        return '_"jj"'
    return "_(" + " ".join(symbols) + ")"


def _dr_sub(legs: tuple, leg_symbols: dict[str, str], symbol_counts: dict[str, int]) -> str:
    """'(j, mu)' when the pairing of the legs is ambiguous (some object appears
    on more than one leg), '' otherwise."""
    symbols = [leg_symbols.get(leg, "") for leg in legs]
    if len(set(symbols)) < 2 or not all(symbols):
        return ""
    if all(symbol_counts[symbol] == 1 for symbol in symbols):
        return ""
    return "(" + ", ".join(symbols) + ")"


def _render_items(
    items: list[tuple],
    leg_symbols: dict[str, str],
    symbol_counts: dict[str, int],
) -> list[str]:
    """Render parsed cross-mask items to Typst, merging duplicates."""
    out: list[str] = []

    def add(text: str) -> None:
        if text not in out:
            out.append(text)

    # Mass windows: pair min and max on the same set of legs
    mass: dict[tuple, dict[str, float]] = {}
    for kind, value, legs in items:
        if kind in ("mass_min", "mass_max"):
            mass.setdefault(tuple(legs), {})[kind] = value

    for kind, value, legs in items:
        if kind == "dz":
            add(f'$|Delta z_0| < {_fmt_num(value)} "cm"$')
        elif kind == "deta":
            add(f"$|Delta eta| < {_fmt_num(value)}$")
        elif kind in ("dr_max", "dr_min"):
            if kind == "dr_min" and value <= 0:  # dR > 0 is only duplicate removal
                continue
            sub = _dr_sub(legs, leg_symbols, symbol_counts)
            op = "<" if kind == "dr_max" else ">"
            add(f"$Delta R{sub} {op} {_fmt_num(value)}$")
        elif kind in ("mass_min", "mass_max"):
            window = mass[tuple(legs)]
            lo, hi = window.get("mass_min"), window.get("mass_max")
            m = "m" + _mass_sub(legs, leg_symbols)
            if lo is not None and hi is not None:
                add(f'${_fmt_num(lo)} < {m} < {_fmt_num(hi)} "GeV"$')
            elif lo is not None:
                add(f'${m} > {_fmt_num(lo)} "GeV"$')
            else:
                add(f'${m} < {_fmt_num(hi)} "GeV"$')
        elif kind == "os":
            add("opposite charge")
        elif kind == "os3":
            add("$|q_1 + q_2 + q_3| = 1$")
        elif kind == "btag":
            add(f"Total b-tag score $> {_fmt_num(value)}$")
        elif kind == "or":
            rendered = _render_items(value, leg_symbols, symbol_counts)
            add(" or ".join(dict.fromkeys(rendered)))
    return out


def derive_seed(
    seed_def: dict,
    version: str,
    objects_cfg: dict,
    scalings_version: Optional[str] = None,
    decimals: Optional[int] = None,
) -> dict:
    """Derive the table ingredients for one seed from its menu definition."""
    legs = {k: v for k, v in seed_def.items() if re.match(r"leg\d+$", k)}
    physics_legs = [
        name
        for name, leg in legs.items()
        if leg["obj"].split(":")[0] not in NON_PHYSICS_OBJECTS
    ]
    cross_masks = seed_def.get("cross_masks") or []

    # --- thresholds, in leg order, skipping PV-like legs
    # (offline, is_online, online barrel, online endcap)
    thresholds: list[tuple[str, bool, str, str]] = []
    unparsed: list[str] = []
    has_online = False
    for leg_name in physics_legs:
        parsed = parse_threshold(legs[leg_name].get("threshold_cut"))
        if parsed is None:
            if legs[leg_name].get("threshold_cut") is not None:
                unparsed.append(f"{leg_name}: {legs[leg_name]['threshold_cut']}")
            thresholds.append(("--", False, "--", "--"))
            continue
        value, is_online = parsed
        has_online |= is_online
        if is_online:
            # the cut is already the online threshold, region-independent
            text = _fmt_online(value)
            thresholds.append((_fmt_num(value), True, text, text))
            continue
        online = [
            _fmt_online(
                online_threshold(
                    legs[leg_name]["obj"], value, version, region, scalings_version, decimals
                )
            )
            for region in ("barrel", "endcap")
        ]
        thresholds.append((_fmt_num(value), False, *online))

    # --- requirements from the cross masks
    per_leg_eta: dict[str, float] = {}
    items: list[tuple] = []
    for mask in cross_masks:
        mask_items, ok = _mask_items(str(mask))
        if not ok:
            unparsed.append(str(mask))
        if "|" in str(mask) and len(mask_items) > 1:
            # OR of conditions: keep them together
            items.append(("or", mask_items, ()))
            continue
        for item in mask_items:
            if item[0] == "eta":
                leg = f"leg{item[2][0]}"
                per_leg_eta[leg] = min(item[1], per_leg_eta.get(leg, math.inf))
            else:
                items.append(item)

    # Combine explicit eta cuts with those implied by the object definition
    for leg_name in physics_legs:
        obj_eta = _object_max_eta(legs[leg_name]["obj"], version, objects_cfg)
        if obj_eta is not None:
            per_leg_eta[leg_name] = min(obj_eta, per_leg_eta.get(leg_name, math.inf))

    leg_symbols = {
        leg_name[3:]: OBJECT_SYMBOLS.get(legs[leg_name]["obj"].split(":")[0], "")
        for leg_name in physics_legs
    }
    symbol_counts: dict[str, int] = {}
    for symbol in leg_symbols.values():
        if symbol:
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

    requirements: list[str] = []
    # Eta bounds first: one entry if all legs share the bound, else one per
    # bound, subscripted with the objects it applies to.
    eta_legs: dict[float, list[str]] = {}
    for leg_name in physics_legs:
        if leg_name in per_leg_eta:
            eta_legs.setdefault(per_leg_eta[leg_name], []).append(leg_name[3:])
    if len(eta_legs) == 1:
        requirements.append(f"$|eta| < {_fmt_eta(next(iter(eta_legs)))}$")
    else:
        for value, leg_ids in eta_legs.items():
            symbols = list(dict.fromkeys(leg_symbols[leg] for leg in leg_ids))
            sub = ""
            if all(symbols):
                sub = f"_{symbols[0]}" if len(symbols) == 1 else "_(" + " ".join(symbols) + ")"
            requirements.append(f"$|eta{sub}| < {_fmt_eta(value)}$")
    requirements += _render_items(items, leg_symbols, symbol_counts)
    # Object-level requirements from the layout, e.g. an ID score cut
    for leg_name in physics_legs:
        extra = objects_cfg.get(legs[leg_name]["obj"].split(":")[0], {}).get("requirement")
        if extra and _typst_text(extra) not in requirements:
            requirements.append(_typst_text(extra))

    return {
        "thresholds": thresholds,
        "requirements": requirements,
        "has_online": has_online,
        "unparsed": unparsed,
    }


###########################################################################
# Inputs
###########################################################################


def load_layout(path: str) -> dict:
    with open(path) as f:
        layout = yaml.safe_load(f) or {}
    layout.setdefault("sections", [])
    return layout


def default_layout_path(menu_config_path: str) -> str:
    """configs/V50nano/rate_table/step1p5_menu_cfg.yml
    -> configs/V50nano/rate_table/step1p5_table_layout.yml"""
    base = os.path.basename(menu_config_path)
    stem = re.sub(r"(_menu)?_cfg\.ya?ml$", "", base)
    return os.path.join(os.path.dirname(menu_config_path), f"{stem}_table_layout.yml")


def read_section_hints(menu_config_path: str) -> dict[str, str]:
    """Map each active seed to the column-0 comment directly above it.

    Fallback grouping when a menu has no layout file; YAML loses the comments,
    so the raw text is read. Commented-out YAML is ignored.
    """
    hints: dict[str, str] = {}
    current: Optional[str] = None
    with open(menu_config_path) as f:
        for line in f:
            if not line.strip():
                continue
            if line.startswith("#"):
                text = re.sub(r"^[#\s]+", "", line).strip()
                looks_like_yaml = re.match(r"^[\w\-]+\s*:", text) or text.startswith("-")
                if text and not looks_like_yaml and not re.fullmatch(r"[#=\-*\s]*", text):
                    current = text
                continue
            key = re.match(r"^([A-Za-z0-9_]+)\s*:", line)
            if key:
                hints[key.group(1)] = current or "Unsorted seeds"
    return hints


def pu_for_version(version: str, layout: dict) -> int:
    """Pile-up the main CSV was produced at: the `_NNNPU` version suffix, else
    the layout's `pu_columns` entry without a suffix, else 200."""
    match = re.search(r"_(\d+)PU$", version)
    if match:
        return int(match.group(1))
    for entry in layout.get("pu_columns") or []:
        if not entry.get("version_suffix"):
            return int(entry["pu"])
    return 200


def _thresholds_cell(thresholds: list[tuple[str, bool, str, str]]) -> str:
    """Offline-threshold cell: '[1, 1]' or '[6^dagger, 6^dagger]' in math when
    any threshold is applied online."""
    if any(is_online for _, is_online, _, _ in thresholds):
        values = ", ".join(
            text + (DAGGER if is_online else "") for text, is_online, _, _ in thresholds
        )
        return f"[${values}$]"
    return "[" + ", ".join(text for text, _, _, _ in thresholds) + "]"


def _online_cells(thresholds: list[tuple[str, bool, str, str]]) -> tuple[str, str]:
    """Barrel and endcap online-threshold cells, one value per leg."""
    barrel = ", ".join(text for _, _, text, _ in thresholds)
    endcap = ", ".join(text for _, _, _, text in thresholds)
    return f"[{barrel}]", f"[{endcap}]"


def _requirements_cell(requirements: list[str]) -> str:
    if not requirements:
        return "[]"
    return "[" + "\\ ".join(requirements) + "]"


###########################################################################
# Thresholds embedded in the seed names
###########################################################################

# Numbers in a name that are not thresholds ("DoubleTkMu4er2p0": 4 is the
# threshold, the 2p0 after "er" is an eta bound; "Mass_Max12": 12 is a mass)
_NAME_NUMBER_RE = re.compile(r"([A-Za-z]+)(\d+(?:p\d+)?)")
_NAME_NOT_THRESHOLD = {"max", "min", "mass", "er", "to", "dr", "deta", "mt"}
# Bare threshold segments, optionally with a quality suffix ("TripleTkMu_4_2p5_0",
# "TripleTkMu_5SQ_3SQ_0OQ")
_NAME_BARE_NUMBER_RE = re.compile(r"(\d+(?:p\d+)?)(?:SQ|OQ|DQ)?")


def _fmt_name_num(value: float) -> str:
    """219 -> '219', 2.5 -> '2p5', as thresholds are written in seed names."""
    return _fmt_num(value).replace(".", "p")


def _name_threshold_tokens(name: str) -> list[tuple[int, int, float]]:
    """(start, end, value) of the numbers of `name` that encode thresholds."""
    tokens = []
    offset = 0
    for segment in name.split("_"):
        start = offset
        offset += len(segment) + 1
        bare = _NAME_BARE_NUMBER_RE.fullmatch(segment)
        if bare:
            tokens.append(
                (start, start + len(bare.group(1)), float(bare.group(1).replace("p", ".")))
            )
            continue
        for match in _NAME_NUMBER_RE.finditer(segment):
            if match.group(1).lower() in _NAME_NOT_THRESHOLD:
                continue
            number = match.group(2)
            num_start = start + match.start(2)
            tokens.append((num_start, num_start + len(number), float(number.replace("p", "."))))
    return tokens


def _fix_name_thresholds(name: str, values: list[Optional[float]], seed: str) -> str:
    """Rewrite the thresholds embedded in `name` when they differ from the
    thresholds `values` of the menu definition, e.g. `TkMu12_HTSum150` with
    thresholds 15 and 219 shows as `TkMu15_HTSum219`. Only the Typst table
    changes; the YAML keeps the historical name.

    The name is left alone when it embeds no thresholds, when they agree, or
    when they cannot be matched to the legs one to one.
    """
    tokens = _name_threshold_tokens(name)
    if not tokens or any(value is None for value in values):
        return name
    if len(tokens) == len(values):
        expected = values
    elif len(tokens) == 1 and len(values) > 1 and len(set(values)) == 1:
        # one number covers legs of equal threshold ("DoubleTkMu4er2p0")
        expected = values[:1]
    else:
        print(
            f"WARNING: {seed}: {len(tokens)} thresholds in the name for "
            f"{len(values)} legs, leaving the name unchanged"
        )
        return name

    renamed = name
    for (start, end, found), want in reversed(list(zip(tokens, expected))):
        if abs(found - want) > 1e-9:
            renamed = renamed[:start] + _fmt_name_num(want) + renamed[end:]
    if renamed != name:
        print(f"INFO: {seed}: name thresholds differ from the menu, shown as `{renamed}`")
    return renamed


###########################################################################
# Row colors
###########################################################################

# "blue" or "#123456"; the row fill is the color with a low alpha
_ROW_FILL_ALPHA = "transparentize(85%)"


def _fill_expr(color, seed: str) -> Optional[str]:
    """Typst fill expression for the `color` field of a seed, or None."""
    if color is None:
        return None
    text = str(color).strip()
    if re.fullmatch(r"[a-zA-Z]+", text):
        base = text
    elif re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        base = f'rgb("{text}")'
    else:
        print(
            f"WARNING: {seed}: unusable color `{color}`, "
            "expected a Typst color name (e.g. `blue`) or #rrggbb"
        )
        return None
    return f"{base}.{_ROW_FILL_ALPHA}"


def _cell(content: str, fill: Optional[str]) -> str:
    """Wrap one cell in `table.cell(fill: ...)` when the row is colored."""
    if not fill:
        return content
    body = content[1:-1] if content.startswith("[") and content.endswith("]") else content
    return f"table.cell(fill: {fill})[{body}]"


###########################################################################
# Rendering
###########################################################################


def build_rows(
    menu: dict,
    layout: dict,
    rates: dict[str, float],
    version: str,
    scalings_version: Optional[str] = None,
    decimals: Optional[int] = None,
) -> tuple[list[tuple[str, list[dict]]], bool, int]:
    """Resolve the layout against the menu and the CSV into render-ready rows.

    Returns the sections, whether any threshold is applied online, and the
    number of seed rows (the caption quotes it).
    """
    objects_cfg = DEFAULT_OBJECTS | (layout.get("objects") or {})
    sections = []
    placed = set()
    any_online = False
    n_seeds = 0

    def make_row(seed: str, entry: dict) -> dict:
        nonlocal any_online, n_seeds
        derived = derive_seed(
            menu[seed], version, objects_cfg, scalings_version, decimals
        )
        for problem in derived["unparsed"]:
            # threshold problems are reported as "legN: <cut>"
            key = "thresholds" if re.match(r"leg\d+: ", problem) else "requirements"
            if key not in entry:
                print(f"WARNING: {seed}: could not translate `{problem}`, set `{key}` by hand")
        any_online |= derived["has_online"]
        n_seeds += 1
        requirements = list(derived["requirements"])
        if entry.get("requirements"):
            requirements = [_typst_text(entry["requirements"])]
        if entry.get("extra_requirements"):
            requirements.append(_typst_text(entry["extra_requirements"]))
        thresholds = derived["thresholds"]
        if seed not in rates:
            print(f"WARNING: `{seed}` not found in the CSV")
        display = seed.removeprefix("L1_")
        display = _fix_name_thresholds(
            display,
            [float(text) if text != "--" else None for text, *_ in thresholds],
            seed,
        )
        online_barrel, online_endcap = _online_cells(thresholds)
        return {
            "seed": display,
            "offline": _thresholds_cell(thresholds),
            "online_barrel": online_barrel,
            "online_endcap": online_endcap,
            "rate": rates.get(seed),
            "requirements": _requirements_cell(requirements),
            "fill": _fill_expr(entry.get("color") or menu[seed].get("color"), seed),
        }

    for section in layout["sections"]:
        rows = []
        for seed, entry in (section.get("seeds") or {}).items():
            entry = entry or {}
            if seed not in menu:
                print(f"WARNING: `{seed}` is in the layout but not in the menu, skipping")
                continue
            placed.add(seed)
            rows.append(make_row(seed, entry))
        if rows:
            sections.append((section["name"], rows))

    missing = [s for s in menu if s not in placed]
    if missing:
        print(f"WARNING: {len(missing)} seed(s) not in the layout, appended at the end: {missing}")
        sections.append(
            ("Seeds missing from the table layout", [make_row(seed, {}) for seed in missing])
        )

    return sections, any_online, n_seeds


def render_table(
    sections: list[tuple[str, list[dict]]],
    total: Optional[float],
    pu: int,
    n_seeds: int,
    any_online: bool,
    with_online: bool = True,
) -> str:
    """Render the Typst table. `with_online` adds the online-thresholds columns
    (and mentions them in the caption)."""
    ncol = 6 if with_online else 4
    online_header = (
        "[#align(center)[Online threshold\\ barrel [GeV]]], "
        "[#align(center)[Online threshold\\ endcap [GeV]]], "
        if with_online
        else ""
    )
    rows = [
        "      [Seed], "
        "[#align(center)[Offline thresholds\\ [GeV]]], "
        + online_header
        + f"[#align(center)[Rate at PU {pu}\\ [kHz]]], "
        "[#align(center)[Additional\\ requirements]],"
    ]
    heavy: list[int] = []  # rows with a 1pt top stroke: section banners, totals
    y = 0  # the header row is y == 0
    for name, seeds in sections:
        y += 1
        heavy.append(y)
        rows.append(
            f"      table.cell(colspan: {ncol}, align: left, "
            "inset: (left: 4pt, right: 4pt, top: 4pt, bottom: 6pt))"
            f"[*{_typst_text(name)}*],"
        )
        for row in seeds:
            y += 1
            cells = [f"`{row['seed']}`", row["offline"]]
            if with_online:
                cells += [row["online_barrel"], row["online_endcap"]]
            cells += [f"[{_fmt_rate(row['rate'])}]", row["requirements"]]
            rows.append(
                "      " + ", ".join(_cell(cell, row["fill"]) for cell in cells) + ","
            )
    if total is not None and not math.isnan(total):
        y += 1
        heavy.append(y)
        rows.append(
            f"      table.cell(colspan: {ncol - 1}, align: right)"
            "[*Total L1 menu rate*], "
            f"[{_fmt_khz(total)}],"
        )
        y += 1
        margin = int(100 * ANCILLARY_MARGIN)
        rows.append(
            f"      table.cell(colspan: {ncol - 1}, align: right)"
            f"[*Total L1 menu rate + {margin}% ancillary seeds*], "
            f"[{_fmt_khz(total * (1 + ANCILLARY_MARGIN))}]"
        )
    last = y

    thresholds_text = (
        "offline thresholds and the online thresholds of the barrel and endcap scalings"
        if with_online
        else "offline thresholds"
    )
    caption = (
        f"Complete list of the {n_seeds} seeds of the Phase-2 simplified L1 menu, "
        f"with the Run-3 {thresholds_text}, the individual rates at "
        f"PU {pu} and the additional requirements of each seed."
    )
    if any_online:
        caption += (
            " The thresholds marked with $dagger$ are applied online, without the "
            "offline-to-online scaling."
        )

    out = [
        "#align(center)[",
        "  #set text(size: 10.34pt)",
        "  #figure(",
        "    table(",
        f"      columns: ({', '.join(['auto'] * ncol)}),",
        "      stroke: (x, y) => (",
        "        left: if x > 0 { 1pt } else { 0pt },",
        "        top: if y == 0 {",
        "          0pt",
        f"        }} else if y in ({', '.join(str(i) for i in heavy)}) {{",
        "          1pt",
        "        } else {",
        "          0.4pt",
        "        },",
        f"        bottom: if y == {last} {{ 1pt }} else {{ 0pt }},",
        "      ),",
        "      inset: 4pt,",
        "      align: left + horizon,",
    ]
    out += rows
    out += [
        "    ),",
        f"    caption: [{caption}],",
        f"  ) <{TABLE_LABEL}>",
        "]",
    ]
    return "\n".join(out) + "\n"


###########################################################################
# Entry points
###########################################################################


def write_typst_table(
    config_dict: dict,
    config: MenuConfig,
    csv_path: str,
    layout_path: Optional[str] = None,
    output: Optional[str] = None,
) -> list[str]:
    """Write the Typst menu tables for `csv_path`: with the online-thresholds
    columns (`<base>.typ`) and without them (`<base>_no_online.typ`), where
    `output` or the CSV stem gives `<base>`. Returns the paths written."""
    with open(config.menu_config) as f:
        menu = yaml.safe_load(f)
    layout_path = (
        layout_path
        or config_dict.get("table_layout")
        or default_layout_path(config.menu_config)
    )
    if os.path.exists(layout_path):
        layout = load_layout(layout_path)
    else:
        print(f"WARNING: no layout at {layout_path}, grouping seeds by menu config comments")
        order: dict[str, list[str]] = {}
        hints = read_section_hints(config.menu_config)
        for seed in menu:
            order.setdefault(hints.get(seed, "Unsorted seeds"), []).append(seed)
        layout = {
            "sections": [{"name": name, "seeds": {s: {} for s in seeds}} for name, seeds in order.items()]
        }

    df = pd.read_csv(csv_path)
    if "rate" not in df.columns:
        raise SystemExit(f"{csv_path} has no rate column (signal run?), cannot write a rate table")
    rates = dict(zip(df["seed"], df["rate"]))
    total = rates.pop("Total", None)
    rates.pop("Total Event Number", None)
    if total is not None and math.isnan(total):
        total = None

    sections, any_online, n_seeds = build_rows(
        menu,
        layout,
        rates,
        config.config_version_for_objects,
        config.scalings_version,
        config.scalings_decimals,
    )
    pu = pu_for_version(config.version, layout)

    out_base = output or os.path.splitext(csv_path)[0]
    if out_base.endswith(".typ"):
        out_base = out_base[: -len(".typ")]
    written = []
    for with_online in (True, False):
        out_path = out_base + (".typ" if with_online else "_no_online.typ")
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w") as f:
            f.write(render_table(sections, total, pu, n_seeds, any_online, with_online))
        print(f"Wrote {out_path}")
        written.append(out_path)
    return written


def _extract_version(path: str) -> Optional[str]:
    """configs/V50nano/rate_table/x.yml -> V50nano (same logic as rate_table)."""
    parts = os.path.normpath(path).split(os.sep)
    if "configs" in parts and parts.index("configs") + 1 < len(parts):
        return parts[parts.index("configs") + 1]
    return None


EXAMPLES = """examples (from the repository root):
  rate_table_typst configs/V50nano/rate_table/step1p5_cfg.yml --version V50nano
  rate_table_typst configs/V50nano/rate_table/step1p5_cfg.yml --csv outputs/V50nano/rate_tables/x.csv
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="rate_table_typst",
        description=__doc__.split("\n\n")[0],
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("config_file", help="rate_table config, e.g. configs/V50nano/rate_table/step1p5_cfg.yml")
    parser.add_argument("--version", help="outputs/<version>/rate_tables to read the CSV from "
                        "(same as for rate_table)", default=None)
    parser.add_argument("--scalings", help="same as for rate_table, to pick up the matching CSV", default=None)
    parser.add_argument("--truncated", action="store_true",
                        help="same as for rate_table, to pick up the matching CSV")
    parser.add_argument("--layout", help="table layout (default: `table_layout` in the config, "
                        "else <menu>_table_layout.yml next to the menu config)")
    parser.add_argument("--csv", help="rate CSV, instead of the one derived from the config and --version")
    parser.add_argument("-o", "--output", help="base path for the two .typ files "
                        "(default: the CSV stem); writes <base>.typ and <base>_no_online.typ")
    args = parser.parse_args()

    with open(args.config_file) as f:
        config_dict = yaml.safe_load(f)
    config = MenuConfig(
        config_dict,
        config_version=_extract_version(args.config_file),
        override_version=args.version,
        override_scalings_version=args.scalings,
        override_sample=None,
        truncated=args.truncated,
    )
    write_typst_table(
        config_dict,
        config,
        args.csv or config.csv_path,
        layout_path=args.layout,
        output=args.output,
    )


if __name__ == "__main__":
    main()
