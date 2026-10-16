"""The firmware (C++, not compiled here) speaks the MQTT contract of common/mqtt: same
sensor types, physical ranges and units, actuator names, topic shapes (docs/06 §3)."""

import re
from pathlib import Path

from common.mqtt import PHYSICAL_RANGE, Actuator, SensorType, parse_topic
from sim.nodes import PUMP_MAX_S

FW = Path(__file__).resolve().parents[1] / "firmware"


def sources() -> str:
    return "\n".join(p.read_text() for p in FW.rglob("*") if p.suffix in (".h", ".cpp"))


def test_ranges_table_matches_contract():
    text = (FW / "lib/serre_logic/src/ranges.h").read_text()
    rows = re.findall(r'\{"(\w+)",\s*(-?[\d.]+)f,\s*(-?[\d.]+)f,\s*"([^"]+)"\}', text)
    table = {t: (float(lo), float(hi), u) for t, lo, hi, u in rows}
    expected = {s.value: (r.min, r.max, r.unite) for s, r in PHYSICAL_RANGE.items()}
    assert table == expected


def test_published_sensor_types_exist():
    used = set(re.findall(r'publishReading\("(\w+)"', sources()))
    assert used >= {
        "temperature",
        "humidite",
        "pression",
        "lux",
        "co2",
        "presence",
        "humidite_sol",
        "ph",
        "ec",
        "temp_eau",
        "niveau_cuve",
    }
    assert used <= {s.value for s in SensorType}


def test_actuators_match_contract():
    text = (FW / "lib/serre_logic/src/command.h").read_text()
    block = text[text.index("kActuators[]") :]
    names = re.findall(r'"(\w+)"', block[: block.index("};")])
    assert set(names) == {a.value for a in Actuator}
    pins = (FW / "include/node_config.h").read_text()
    wired = re.findall(r'\{"(z\d+)", "(\w+)", D\d+, (?:true|false)\}', pins)
    assert wired
    for zone, kind in wired:
        parse_topic(f"serre/{zone}/cmd/{kind}")


SAMPLES = {"capteur": "temperature", "etat": "ventilo", "cmd": "ventilo"}


def test_topic_formats_and_limits():
    src = sources()
    formats = set(re.findall(r'"(serre/%s/[^"]+)"', src))
    assert formats == {
        "serre/%s/status",
        "serre/%s/capteur/%s",
        "serre/%s/etat/%s",
        "serre/%s/cmd/#",
        "serre/%s/capteur/niveau_cuve",
    }
    for f in formats:
        kind = f.split("/")[2]
        node_or_zone = "esp32-01" if kind == "status" else "z1"
        topic = f.replace("%s", node_or_zone, 1).replace("%s", SAMPLES.get(kind, ""))
        parse_topic(topic.replace("#", "ventilo"))
    assert '"offline"' in src and '"online"' in src  # LWT and connection status
    limit = re.search(r"#define MAX_PUMP_S ([\d.]+)f", src)
    assert float(limit.group(1)) == PUMP_MAX_S  # the simulator emulates the same limit
