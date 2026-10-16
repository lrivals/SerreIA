"""Synthetic outside weather: temperature (season + day), sun, clouds, pressure fronts.

Ornstein-Uhlenbeck processes for the pressure and the temperature noise; a low pressure
brings clouds and humidity (what the BMP280 trend is meant to anticipate).
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class WeatherState:
    t_ext: float  # °C
    rayonnement: float  # W/m², global horizontal
    hr_ext: float  # %
    pression: float  # hPa
    nuages: float  # 0 clear .. 1 overcast


@dataclass
class Weather:
    seed: int = 0
    lat: float = 45.0
    lon: float = 2.0
    t_annuelle: float = 12.0
    amp_saison: float = 8.0
    amp_jour: float = 5.0
    rng: np.random.Generator = field(init=False)

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)
        self.p_dev = 0.0  # pressure deviation from 1013 hPa
        self.t_noise = 0.0
        self.cloud_noise = 0.0

    @staticmethod
    def _ou(x: float, dt: float, tau: float, sigma: float, rng) -> float:
        a = math.exp(-dt / tau)
        return a * x + sigma * math.sqrt(1 - a * a) * rng.standard_normal()

    def sun_elevation(self, t: datetime) -> float:
        """sin of the solar elevation (simple declination / hour angle model)."""
        doy = t.timetuple().tm_yday
        dec = math.radians(23.44) * math.sin(2 * math.pi * (284 + doy) / 365)
        solar_h = t.hour + t.minute / 60 + t.second / 3600 + self.lon / 15  # t is UTC
        ha = math.radians(15 * (solar_h - 12))
        lat = math.radians(self.lat)
        return math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(ha)

    def step(self, t: datetime, dt: float) -> WeatherState:
        rng = self.rng
        self.p_dev = self._ou(self.p_dev, dt, 2 * 86400, 8.0, rng)
        self.t_noise = self._ou(self.t_noise, dt, 6 * 3600, 1.5, rng)
        self.cloud_noise = self._ou(self.cloud_noise, dt, 3 * 3600, 0.2, rng)
        pression = 1013 + self.p_dev
        nuages = min(1.0, max(0.0, 0.45 - self.p_dev / 25 + self.cloud_noise))
        doy = t.timetuple().tm_yday
        season = self.t_annuelle - self.amp_saison * math.cos(2 * math.pi * (doy - 15) / 365)
        local_h = t.hour + t.minute / 60 + self.lon / 15
        day = -self.amp_jour * math.cos(2 * math.pi * (local_h - 3) / 24)  # min ~3 h, max ~15 h
        t_ext = season + day * (1 - 0.5 * nuages) + self.t_noise
        elev = self.sun_elevation(t)
        rayonnement = max(0.0, 1000 * elev) * (1 - 0.75 * nuages)
        hr_ext = min(100.0, max(25.0, 72 + 20 * nuages - 2.5 * (t_ext - season)))
        return WeatherState(t_ext, rayonnement, hr_ext, pression, nuages)
