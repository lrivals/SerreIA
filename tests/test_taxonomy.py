"""Unified taxonomy (docs/02-donnees.md §2)."""

import pytest

from vision.datasets.build_index import DATA_DIR, iter_source_dirs
from vision.datasets.taxonomy import ETATS, TaxonomyError, load_taxonomy


@pytest.fixture(scope="module")
def taxo():
    return load_taxonomy()


def test_taxonomy_shape(taxo):
    assert taxo.version >= 1
    assert len(taxo.especes) == 16
    assert 50 <= len(taxo.classes) <= 60
    assert {c.etat for c in taxo.classes.values()} <= set(ETATS)


def test_sante(taxo):
    assert taxo.lookup("ccmt", "Tomato/healthy").sante == "sain"
    assert taxo.lookup("plantvillage", "Tomato___Late_blight").sante == "anormal"


def test_ambigu_kept_separate(taxo):
    info = taxo.lookup("ccmt", "Tomato/leaf blight")
    assert info.ambigu and info.classe == "tomate/maladie/brulure_ccmt"


def test_duplicate_key_rejected(tmp_path):
    bad = tmp_path / "t.yaml"
    bad.write_text(
        "version: 1\nclasses:\n"
        "  a/sain/sain: {sources: {ccmt: [X/y]}}\n"
        "  b/sain/sain: {sources: {ccmt: [X/y]}}\n"
    )
    with pytest.raises(TaxonomyError):
        load_taxonomy(bad)


@pytest.mark.parametrize("classe", ["Tomate/sain/sain", "tomate/malade/x", "tomate/sain"])
def test_bad_class_rejected(tmp_path, classe):
    bad = tmp_path / "t.yaml"
    bad.write_text(f"version: 1\nclasses:\n  {classe}: {{sources: {{}}}}\n")
    with pytest.raises(TaxonomyError):
        load_taxonomy(bad)


def test_all_folders_on_disk_mapped(taxo):
    dirs = list(iter_source_dirs(DATA_DIR))
    if not dirs:
        pytest.skip("data/ absent")
    unmapped = [f"{d.source}: {d.key}" for d in dirs if not taxo.has(d.source, d.key)]
    assert not unmapped
