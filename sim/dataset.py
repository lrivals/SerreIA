"""Simulated history for the level 2 forecast (`edge.controller.forecast train --sim-jours`).

Runs the zone models directly (no MQTT, 60 s step) with a simple thermostat policy plus
random excitation of the actuators, so that the model sees their effect, and returns a
wide table at a 10 min step: `ts`, `zone`, the sensor columns, `etat_<actuator>` (0..1)
and the outside temperature `t_ext`.
"""

from datetime import UTC, datetime, timedelta

import numpy as np

from common.mqtt import Actuator, SensorType

from .model import ZoneModel
from .simulation import default_layout
from .weather import Weather


def _policy(m: ZoneModel, t: datetime, rng, state: dict) -> dict[str, float]:
    local_h = (t.hour + 2) % 24
    a = {}
    a[Actuator.VENTILO] = 1.0 if m.t > 26 + state["dt"] or m.hr > 85 else 0.0
    a[Actuator.CHAUFFAGE] = 1.0 if m.t < 15 + state["dt"] else 0.0
    a[Actuator.LED] = 1.0 if 6 <= local_h < 20 and m.lux < 15000 else 0.0
    a[Actuator.BRUMISATEUR] = 1.0 if m.hr < 50 and rng.random() < 0.3 else 0.0
    dry = any(v < 45 for v in m.soil.values())
    a[Actuator.POMPE_NUTRI] = (
        1.0 if (dry and rng.random() < 0.1) or (m.p.hydro and t.minute < 15) else 0.0
    )
    if m.p.hydro:
        a[Actuator.POMPE_PH_DOWN] = 1.0 if m.ph > 6.3 and rng.random() < 0.05 else 0.0
        nutri = 1.0 if m.ec < 1.1 and rng.random() < 0.05 else 0.0
        a[Actuator.POMPE_NUTRI_A] = a[Actuator.POMPE_NUTRI_B] = nutri
        if m.niveau < 15:
            m.niveau = 90.0  # refill
    if rng.random() < 0.002:  # excitation: random manual actions
        k = rng.choice([Actuator.VENTILO, Actuator.CHAUFFAGE, Actuator.BRUMISATEUR])
        state["force"] = (k, t + timedelta(minutes=float(rng.uniform(5, 60))))
    if state.get("force") and t < state["force"][1]:
        a[state["force"][0]] = 1.0
    if rng.random() < 0.001:
        state["dt"] = float(rng.uniform(-3, 3))  # setpoint changes
    return a


def generate(days: int = 30, seed: int = 0, start: datetime | None = None, dt: float = 60.0):
    import pandas as pd

    rng = np.random.default_rng(seed)
    layout = default_layout(seed)
    weather = Weather(seed)
    models = {z: ZoneModel(z, p, seed + i) for i, (z, p) in enumerate(layout.zones.items())}
    states = {z: {"dt": 0.0} for z in models}
    t = start or datetime(2026, 3, 1, tzinfo=UTC)
    rows = []
    for i in range(int(days * 86400 / dt)):
        t += timedelta(seconds=dt)
        w = weather.step(t, dt)
        for z, m in models.items():
            act = _policy(m, t, rng, states[z])
            m.step(t, dt, w, act)
            if i % int(600 / dt) == 0:
                r = m.readings()
                row = {"ts": t, "zone": z, "t_ext": w.t_ext}
                for (s, _), v in r.items():
                    if s == SensorType.HUMIDITE_SOL:
                        continue
                    row[s.value] = v
                soil = [v for (s, _), v in r.items() if s == SensorType.HUMIDITE_SOL]
                if soil:
                    row["humidite_sol"] = float(np.mean(soil))
                for a in Actuator:
                    row[f"etat_{a.value}"] = act.get(a, 0.0)
                rows.append(row)
    return pd.DataFrame(rows)
