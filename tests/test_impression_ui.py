"""The configurator (docs/21) uses the same dimensions as hardware/params.py (docs/20 §5.2)."""

import re
from dataclasses import fields
from pathlib import Path

from hardware import params as hp

CATALOGUE = Path(__file__).parents[1] / "frontend/src/impression/catalogue.ts"


def _cotes_params() -> dict[str, float]:
    out = {}
    for line in CATALOGUE.read_text().splitlines():
        if line.lstrip().startswith("{ cle:") and "params: true" in line:
            m = re.search(r'cle: "(\w+)".*?nominal: ([\d.]+)', line)
            assert m, line
            out[m[1]] = float(m[2])
    return out


def test_catalogue_dimensions_are_params_fields_with_same_nominal():
    cotes = _cotes_params()
    nominal = {f.name: getattr(hp.Params(), f.name) for f in fields(hp.Params)}
    assert cotes, "no params dimension found in catalogue.ts"
    for cle, v in cotes.items():
        assert cle in nominal, f"{cle} is not a field of hardware.params.Params"
        assert v == nominal[cle], f"{cle}: {v} in catalogue.ts, {nominal[cle]} in params.py"


def test_every_dimension_to_measure_is_in_the_configurator():
    assert set(hp.A_MESURER) <= set(_cotes_params())
