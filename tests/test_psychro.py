"""Psychrometry (docs/22 L4) against the reference table of Shamshiri 2018 (Table 5)."""

import pytest

from edge.controller.psychro import humidite_absolue, p_sat, point_de_rosee, vpd


def test_vpd_reference_point():
    assert vpd(25, 90) == pytest.approx(0.317, abs=0.005)  # `2018-shamshiri#016`


@pytest.mark.parametrize(
    ("t", "hr", "expected"),
    [(25, 50, 1.584), (20, 70, 0.701), (30, 80, 0.849), (15, 60, 0.682)],
)
def test_vpd_other_points(t, hr, expected):
    assert vpd(t, hr) == pytest.approx(expected, abs=0.01)


def test_vpd_bounds():
    assert vpd(20, 100) == 0
    assert vpd(20, 120) == 0  # sensor overshoot: clipped
    assert vpd(20, 0) == pytest.approx(p_sat(20))


def test_dew_point():
    assert point_de_rosee(20, 100) == pytest.approx(20, abs=1e-6)
    assert point_de_rosee(25, 50) == pytest.approx(13.9, abs=0.2)
    assert point_de_rosee(18, 93) == pytest.approx(16.9, abs=0.2)


def test_absolute_humidity():
    assert humidite_absolue(20, 100) == pytest.approx(17.3, abs=0.2)
    assert humidite_absolue(25, 50) == pytest.approx(11.5, abs=0.2)
