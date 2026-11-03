"""Psychrometry of the greenhouse air (docs/22 L4): VPD, dew point, absolute humidity.

Air temperature is used for want of a leaf temperature. Saturation vapour pressure:
Tetens formula over water, 0.6108 exp(17.27 T / (T + 237.3)) kPa, the one of the table used
as reference (90 % at 25 °C → 0.317 kPa, Shamshiri 2018 Table 5, `2018-shamshiri#016`).

The VPD **constrains** the actuators but never drives them alone: the same 0.85 kPa is
15 °C at 50 % or 34 °C at 84 % (`2018-shamshiri#008.0`).
"""

import math

_A, _B = 17.27, 237.3
_M_W, _R = 18.015, 8.314  # g/mol, J/(mol K)


def p_sat(t: float) -> float:
    """Saturation vapour pressure (kPa) at t °C."""
    return 0.6108 * math.exp(_A * t / (t + _B))


def vpd(t: float, hr: float) -> float:
    """Vapour pressure deficit (kPa) of air at t °C and hr % relative humidity."""
    hr = min(100.0, max(0.0, hr))
    return p_sat(t) * (1 - hr / 100)


def point_de_rosee(t: float, hr: float) -> float:
    """Dew point (°C), inverse of the same Tetens formula."""
    hr = min(100.0, max(0.1, hr))
    g = math.log(hr / 100) + _A * t / (t + _B)
    return _B * g / (_A - g)


def humidite_absolue(t: float, hr: float) -> float:
    """Absolute humidity (g of water per m³ of air)."""
    e = p_sat(t) * min(100.0, max(0.0, hr)) / 100 * 1000  # Pa
    return e * _M_W / (_R * (t + 273.15))
