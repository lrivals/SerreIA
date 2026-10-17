"""Simulated greenhouse on MQTT: weather + zone models + emulated nodes (docs/06 §5).

Default layout, the one of `edge/controller/serre.yaml`:
- z1, soil: air node esp32-01 (SHT41, BMP280, GY-302, SCD41, HLK-LD2450), soil node
  esp32-02 (probes z1-A1, z1-A2);
- z2, hydro NFT: solution node esp32-03 (pH, EC, DS18B20, tank level), air node esp32-05;
- actuator node esp32-04 for both zones;
- cameras cam-z1-a (z1-A1 tomato, z1-A2 basil, one region each) and cam-z2-a (z2-A1).
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np

from common.mqtt import (
    CAPTURE,
    Actuator,
    CaptureRequest,
    SensorType,
    decode,
    parse_topic,
    status_topic,
)

from .faults import Faults
from .model import ZoneModel, ZoneParams
from .nodes import ActuatorNode, SensorNode, SimCamera
from .weather import Weather

log = logging.getLogger(__name__)

AIR = [
    SensorType.TEMPERATURE,
    SensorType.HUMIDITE,
    SensorType.PRESSION,
    SensorType.LUX,
    SensorType.CO2,
    SensorType.PRESENCE,
]
SOLUTION = [SensorType.PH, SensorType.EC, SensorType.TEMP_EAU, SensorType.NIVEAU_CUVE]
CLIMATE = [
    Actuator.VENTILO,
    Actuator.CHAUFFAGE,
    Actuator.BRUMISATEUR,
    Actuator.LED,
    Actuator.POMPE_NUTRI,
]
HYDRO = [
    Actuator.VENTILO,
    Actuator.LED,
    Actuator.POMPE_NUTRI,
    Actuator.POMPE_PH_DOWN,
    Actuator.POMPE_NUTRI_A,
    Actuator.POMPE_NUTRI_B,
]


@dataclass
class Layout:
    zones: dict[str, ZoneParams]
    sensor_nodes: list[SensorNode]
    actuators: dict[str, list[Actuator]]
    cameras: list[SimCamera] = field(default_factory=list)


def default_layout(seed: int = 0) -> Layout:
    rng = np.random.default_rng(seed)
    emps = ["z1-A1", "z1-A2"]
    return Layout(
        zones={"z1": ZoneParams(emplacements=emps), "z2": ZoneParams(hydro=True, transmission=0.6)},
        sensor_nodes=[
            SensorNode("esp32-01", "z1", [(s, None) for s in AIR], rng=rng, radar=True),
            SensorNode("esp32-02", "z1", [(SensorType.HUMIDITE_SOL, e) for e in emps], rng=rng),
            SensorNode("esp32-03", "z2", [(s, None) for s in SOLUTION], rng=rng),
            SensorNode("esp32-05", "z2", [(s, None) for s in AIR[:4]], rng=rng),
        ],
        actuators={"z1": CLIMATE, "z2": HYDRO},
        cameras=[
            SimCamera(
                "cam-z1-a",
                "z1",
                {"z1-A1": (0.0, 0.0, 0.5, 1.0), "z1-A2": (0.5, 0.0, 0.5, 1.0)},
                {"z1-A1": "tomate", "z1-A2": "basilic"},
            ),
            SimCamera("cam-z2-a", "z2", {"z2-A1": None}, {"z2-A1": "laitue"}),
        ],
    )


class Simulation:
    """`step()` advances the simulated time by `dt` seconds. The controller, if attached,
    ticks every `tick_s` of simulated time with the simulated clock."""

    def __init__(
        self,
        publisher,
        start: datetime | None = None,
        seed: int = 0,
        faults: Faults | None = None,
        layout: Layout | None = None,
        controller=None,
        dt: float = 10.0,
        tick_s: float = 10.0,
        scenario=None,
    ):
        self.pub, self.t, self.dt = publisher, start or datetime.now(UTC), dt
        self.t0 = self.t
        self.faults = faults or Faults()
        self.layout = layout or default_layout(seed)
        # sim.scenario.Scenario: forced weather and quantities, fake vision (docs/16)
        self.scenario = scenario.injector(self.layout) if scenario is not None else None
        self.weather = Weather(seed)
        self.models = {
            z: ZoneModel(z, p, seed + i) for i, (z, p) in enumerate(self.layout.zones.items())
        }
        self.act_node = ActuatorNode("esp32-04", self.layout.actuators)
        self.controller, self.tick_s, self._next_tick = controller, tick_s, self.t
        self.lock = threading.Lock()
        self.offline: set[str] = set()
        for n in self._nodes():
            publisher.publish(status_topic(n), "online")
        for pattern in self.act_node.topics():
            publisher.subscribe(pattern, self._on_command)
        self.act_node.start(self.t)
        self._flush_states()
        if controller is not None:
            controller.subscribe()

    def _nodes(self) -> list[str]:
        return [n.id for n in self.layout.sensor_nodes] + [self.act_node.id]

    def _on_command(self, topic: str, payload: bytes) -> None:
        with self.lock:
            parsed = parse_topic(topic)
            if parsed.subject == CAPTURE:
                req: CaptureRequest = decode(topic, payload)
                for cam in self.layout.cameras:
                    if cam.zone == parsed.scope and req.camera in (None, cam.id):
                        cam.requested = True  # captured at the next step
            else:
                self.act_node.on_command(topic, payload, self.t)
        self._flush_states()

    def _flush_states(self) -> None:
        for topic, state in self.act_node.drain():
            self.pub.publish(topic, state)

    def step(self) -> None:
        with self.lock:
            self.t += timedelta(seconds=self.dt)
            t = self.t
            w = self.weather.step(t, self.dt)
            if self.scenario is not None:
                w = self.scenario.weather(t, w)
            for zone, model in self.models.items():
                if self.faults.tank_empty(zone, t):
                    model.niveau = 0.0
                model.step(t, self.dt, w, self.act_node.levels(zone))
                if self.scenario is not None:
                    self.scenario.force(zone, model, t, self.dt)
                self.act_node.tank[zone] = model.niveau if model.p.hydro else 100.0
            self.act_node.step(t)
            out = []
            for node in self.layout.sensor_nodes:
                truth = self.models[node.zone].readings()
                out += node.poll(t, truth, self.faults)
            for cam in self.layout.cameras:
                out += cam.poll(t, self.faults)
            if self.scenario is not None:
                out += self.scenario.vision(t)
            status = []
            for n in self._nodes():
                down = self.faults.disconnected(n, t)
                if down and n not in self.offline:
                    self.offline.add(n)
                    status.append((status_topic(n), "offline"))  # the broker's LWT
                elif not down and n in self.offline:
                    self.offline.discard(n)
                    status.append((status_topic(n), "online"))
        for topic, message in status + out:
            self.pub.publish(topic, message)
        self._flush_states()
        if self.controller is not None and t >= self._next_tick:
            self._next_tick = t + timedelta(seconds=self.tick_s)
            self.controller.tick(t)

    def run(
        self,
        duration_s: float | None = None,
        accel: float | None = None,
        stop: threading.Event | None = None,
    ) -> None:
        """Simulated `duration_s` (None: forever), `accel` x real time (None: at full speed)."""
        end = None if duration_s is None else self.t + timedelta(seconds=duration_s)
        while (end is None or self.t < end) and not (stop and stop.is_set()):
            t_real = time.monotonic()
            self.step()
            if accel:
                time.sleep(max(0.0, self.dt / accel - (time.monotonic() - t_real)))

    def close(self) -> None:
        for n in self._nodes():
            self.pub.publish(status_topic(n), "offline")
