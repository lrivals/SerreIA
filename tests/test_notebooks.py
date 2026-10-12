"""Phase 1 notebooks: in sync with their generator, valid code, papermill parameters."""

import ast
import json

import pytest

from tools.notebooks.build import NB_DIR, NOTEBOOKS, dumps


@pytest.mark.parametrize("nb", NOTEBOOKS, ids=lambda nb: nb.name)
def test_notebook_up_to_date(nb):
    path = NB_DIR / nb.name
    assert path.exists(), f"{nb.name} absent : python -m tools.notebooks.build"
    assert path.read_text(encoding="utf-8") == dumps(nb.build()), (
        f"{nb.name} diffère du générateur : python -m tools.notebooks.build"
    )


@pytest.mark.parametrize("nb", NOTEBOOKS, ids=lambda nb: nb.name)
def test_notebook_cells(nb):
    data = json.loads((NB_DIR / nb.name).read_text(encoding="utf-8"))
    cells = [c for c in data["cells"] if c["cell_type"] == "code"]
    assert "parameters" in cells[0]["metadata"].get("tags", [])
    params = ast.parse("".join(cells[0]["source"]))
    names = {t.id for n in params.body if isinstance(n, ast.Assign) for t in n.targets}
    assert "DATASETS" in names  # read by the setup cell
    for c in cells:
        assert c["outputs"] == [] and c["execution_count"] is None
        ast.parse("".join(c["source"]))
