"""Physical ranges and units of the sensor types (docs/06 §3: local validation).

A value outside its range is published with `qualite: erreur`. The firmware has the same
table (`firmware/lib/serre_core/src/ranges.h`, checked by tests/test_firmware_contract.py),
the simulator applies it too.
"""

from dataclasses import dataclass

from .topics import SensorType


@dataclass(frozen=True)
class PhysicalRange:
    min: float
    max: float
    unite: str


PHYSICAL_RANGE: dict[SensorType, PhysicalRange] = {
    SensorType.TEMPERATURE: PhysicalRange(-40, 85, "°C"),  # SHT41: -40..125, XIAO: 85
    SensorType.HUMIDITE: PhysicalRange(0, 100, "%"),
    SensorType.CO2: PhysicalRange(400, 5000, "ppm"),  # SCD41 specified range
    SensorType.LUX: PhysicalRange(0, 65535, "lx"),  # BH1750
    SensorType.PH: PhysicalRange(0, 14, "pH"),
    SensorType.EC: PhysicalRange(0, 20, "mS/cm"),
    SensorType.TEMP_EAU: PhysicalRange(-10, 85, "°C"),  # DS18B20 (waterproof probe)
    SensorType.NIVEAU_CUVE: PhysicalRange(0, 100, "%"),
    SensorType.PRESSION: PhysicalRange(300, 1100, "hPa"),  # BMP280
    SensorType.PRESENCE: PhysicalRange(0, 3, "cibles"),  # HLK-LD2450
    SensorType.HUMIDITE_SOL: PhysicalRange(0, 100, "%"),
}


def quality(sensor: SensorType | str, valeur: float) -> str:
    """`ok` inside the physical range, `erreur` outside (or NaN)."""
    r = PHYSICAL_RANGE[SensorType(sensor)]
    return "ok" if r.min <= valeur <= r.max else "erreur"
