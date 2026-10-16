"""Greenhouse zone model (docs/06 §5): first order thermal model and simplified HR, CO₂,
light, soil moisture, pH, EC, water temperature and tank level dynamics.

`ZoneModel.step(t, dt, weather, actuators)` takes the actuator levels in 0..1 (on = 1,
pwm = valeur / 100) and returns nothing; `readings()` gives the true values (the nodes add
the sensor noise). The same API serves as the environment of level 3 (MPC / RL) later.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from common.mqtt import Actuator, SensorType

from .weather import WeatherState

LUX_PER_WM2 = 120.0  # daylight: ~120 lx per W/m² of global radiation
LUX_TO_PPFD = 0.0185


@dataclass
class ZoneParams:
    emplacements: list[str] = field(default_factory=list)  # soil probes (terre / substrat)
    hydro: bool = False
    tau_s: float = 1800.0  # thermal time constant, closed greenhouse
    transmission: float = 0.7  # cover
    hausse_soleil: float = 15.0  # °C of steady excess at 800 W/m²
    hausse_chauffage: float = 10.0  # °C of steady excess, heater at 100 %
    tau_ventilation_s: float = 300.0  # air renewal, fan at 100 %
    tau_hr_s: float = 1200.0
    transpiration: float = 15.0  # % HR added by the plants at equilibrium
    brumisation_pct_s: float = 0.05  # % HR per second of misting
    ppfd_led: float = 450.0  # LED at 100 %
    arrosage_pct_s: float = 0.25  # soil moisture % per second of watering
    sechage_pct_jour: float = 8.0
    ph_derive_jour: float = 0.15
    ph_down_par_s: float = 0.02
    ec_conso_jour: float = 0.12
    ec_par_s: float = 0.004  # per second of A (and of B)
    niveau_conso_jour: float = 3.0  # % of the tank per day (uptake + evaporation)
    fuseau: str = "Europe/Paris"
    visites_par_jour: float = 3.0
    intrusions_par_jour: float = 0.1  # animals at night…


class ZoneModel:
    def __init__(
        self, zone: str, params: ZoneParams | None = None, seed: int = 0, t0: float = 18.0
    ):
        self.zone, self.p = zone, params or ZoneParams()
        self.rng = np.random.default_rng(seed)
        self.t, self.hr, self.co2 = t0, 70.0, 420.0
        self.lux = 0.0
        self.soil = {e: 55.0 + 10 * self.rng.random() for e in self.p.emplacements}
        self._soil_rate = {e: 0.8 + 0.4 * self.rng.random() for e in self.p.emplacements}
        self.ph, self.ec, self.t_eau, self.niveau = 6.0, 1.3, t0, 80.0
        self.presence, self._presence_until = 0, None
        self.pression = 1013.0
        self.t_ext = t0

    def step(self, t: datetime, dt: float, w: WeatherState, act: dict[str, float]) -> None:
        p, rng = self.p, self.rng
        vent = act.get(Actuator.VENTILO, 0.0)
        heat = act.get(Actuator.CHAUFFAGE, 0.0)
        mist = act.get(Actuator.BRUMISATEUR, 0.0)
        led = act.get(Actuator.LED, 0.0)
        pump = act.get(Actuator.POMPE_NUTRI, 0.0)
        self.t_ext, self.pression = w.t_ext, w.pression

        rad = w.rayonnement * p.transmission
        k_sun = p.hausse_soleil / (800 * p.transmission)
        dT = (
            (w.t_ext - self.t) / p.tau_s
            + k_sun * rad / p.tau_s
            + heat * p.hausse_chauffage / p.tau_s
            - vent * (self.t - w.t_ext) / p.tau_ventilation_s
        )
        self.t += dT * dt + 0.02 * math.sqrt(dt / 10) * rng.standard_normal()

        hr_eq = min(99.0, max(20.0, w.hr_ext + p.transpiration - 2.5 * (self.t - w.t_ext)))
        dhr = (
            (hr_eq - self.hr) / p.tau_hr_s
            + mist * p.brumisation_pct_s
            - vent * (self.hr - w.hr_ext) / p.tau_ventilation_s
        )
        self.hr = min(100.0, max(5.0, self.hr + dhr * dt + 0.05 * rng.standard_normal()))

        photo = 0.03 * min(1.0, rad / 400)
        dco2 = (
            (420 - self.co2) / 7200
            - photo
            + 0.004
            + 0.02 * self.presence
            - vent * (self.co2 - 420) / p.tau_ventilation_s
        )
        self.co2 = max(300.0, self.co2 + dco2 * dt)

        self.lux = rad * LUX_PER_WM2 + led * p.ppfd_led / LUX_TO_PPFD

        dry = p.sechage_pct_jour / 86400 * (0.5 + min(1.5, w.rayonnement / 600)) * dt
        for e in self.soil:
            wet = pump * p.arrosage_pct_s * self._soil_rate[e] * dt
            self.soil[e] = min(100.0, max(0.0, self.soil[e] - dry * self._soil_rate[e] + wet))

        if p.hydro:
            day = dt / 86400
            self.ph += (
                p.ph_derive_jour * day - act.get(Actuator.POMPE_PH_DOWN, 0.0) * p.ph_down_par_s * dt
            )
            self.ec += (
                -p.ec_conso_jour * day
                + (act.get(Actuator.POMPE_NUTRI_A, 0.0) + act.get(Actuator.POMPE_NUTRI_B, 0.0))
                * p.ec_par_s
                * dt
            )
            self.ec = max(0.0, self.ec)
            self.niveau = max(0.0, self.niveau - p.niveau_conso_jour * day * (0.5 + pump))
            self.t_eau += (self.t - self.t_eau) / (3 * 3600) * dt

        self._step_presence(t, dt)

    def _step_presence(self, t: datetime, dt: float) -> None:
        if self._presence_until is not None:
            if t >= self._presence_until:
                self.presence, self._presence_until = 0, None
            return
        local_h = t.astimezone(ZoneInfo(self.p.fuseau)).hour
        day = 8 <= local_h < 19
        rate = (self.p.visites_par_jour / 11 if day else self.p.intrusions_par_jour / 13) / 3600
        if self.rng.random() < rate * dt:
            self.presence = int(self.rng.integers(1, 3)) if day else 1
            minutes = self.rng.uniform(5, 20) if day else self.rng.uniform(1, 5)
            self._presence_until = t + timedelta(minutes=minutes)

    def readings(self) -> dict[tuple[SensorType, str | None], float]:
        """True values per (sensor type, emplacement)."""
        out = {
            (SensorType.TEMPERATURE, None): self.t,
            (SensorType.HUMIDITE, None): self.hr,
            (SensorType.CO2, None): self.co2,
            (SensorType.LUX, None): self.lux,
            (SensorType.PRESSION, None): self.pression,
            (SensorType.PRESENCE, None): float(self.presence),
        }
        for e, v in self.soil.items():
            out[(SensorType.HUMIDITE_SOL, e)] = v
        if self.p.hydro:
            out |= {
                (SensorType.PH, None): self.ph,
                (SensorType.EC, None): self.ec,
                (SensorType.TEMP_EAU, None): self.t_eau,
                (SensorType.NIVEAU_CUVE, None): self.niveau,
            }
        return out
