"""Follow-up routes (docs/12 §2.2–2.4): equipment, measurements, dashboard, vision and
images, consumption, alerts."""

import base64
from datetime import timedelta

import pytest

from common.mqtt import (
    ActuatorState,
    Alert,
    Detection,
    SensorReading,
    VisionResult,
    alert_topic,
    sensor_topic,
    state_topic,
    status_topic,
    vision_topic,
)

from .api_utils import make_api
from .backend_utils import T0


@pytest.fixture
def api(tmp_path):
    return make_api(tmp_path, now=T0 + timedelta(hours=1))


def reading(api, minutes, typ, valeur, unite, noeud="esp32-01", zone="z1", emplacement=None):
    r = SensorReading(
        ts=T0 + timedelta(minutes=minutes),
        noeud=noeud,
        valeur=valeur,
        unite=unite,
        qualite="ok",
        emplacement=emplacement,
    )
    api.send(sensor_topic(zone, typ), r)


def vision(api, image_id="img-1", classe="tomate/mildiou"):
    det = Detection(
        bbox=(0.05, 0.05, 0.4, 0.8),
        espece="tomate",
        espece_conf=0.97,
        sante="anormal",
        sante_conf=0.88,
        classe=classe,
        classe_conf=0.81,
    )
    v = VisionResult(
        ts=T0,
        camera="cam-z1-a",
        image_id=image_id,
        modele="clf",
        detections=[det],
        score_anomalie=0.3,
        surface_verte_px=1000,
    )
    api.send(vision_topic("z1", "cam-z1-a"), v)
    return v


def test_equipment(api):
    c = api.client
    reading(api, 10, "temperature", 22.0, "°C")
    api.send(status_topic("esp32-01"), "online")
    api.send(state_topic("z1", "ventilo"), ActuatorState(ts=T0, action="pwm", valeur=60))
    caps = {x["id"]: x for x in c.get("/api/capteurs", params={"zone": "z1"}).json()}
    t = caps["esp32-01-temperature"]
    assert t["materiel"] == "sht41-z1" and t["derniere_mesure"]["valeur"] == 22.0
    assert set(t["emplacements_couverts"]) == {"z1-A1", "z1-A2"}
    assert caps["esp32-02-humidite_sol-z1-A1"]["emplacements_couverts"] == ["z1-A1"]
    # Calibration reminder: pH every 30 days, last on 2026-10-01 in serre.yaml.
    (ph,) = [x for x in c.get("/api/capteurs", params={"zone": "z2"}).json() if x["type"] == "ph"]
    assert ph["etalonnage_echeance"] == "2026-10-31" and not ph["etalonnage_en_retard"]
    r = c.patch(f"/api/capteurs/{ph['id']}", json={"etalonnage": {"date": "2026-05-01"}}).json()
    assert r["etalonnage_en_retard"]  # 2026-05-31 < 2026-07-15

    new = c.post(
        "/api/capteurs", json={"noeud": "esp32-09", "zone": "z1", "type": "co2", "modele": "SCD41"}
    )
    assert new.status_code == 201 and new.json()["id"] == "esp32-09-co2"

    acts = {a["id"]: a for a in c.get("/api/actionneurs", params={"zone": "z1"}).json()}
    assert acts["ventilo-z1"]["etat"]["valeur"] == 60 and acts["led-z1"]["etat"] is None
    dup = {"id": "ventilo-bis", "zone_id": "z1", "type": "ventilo", "noeud": "esp32-04"}
    assert c.post("/api/actionneurs", json=dup).status_code == 409
    assert c.post("/api/actionneurs", json=dict(dup, type="fusee")).status_code == 422
    assert (
        c.patch("/api/actionneurs/led-z1", json={"puissance_w": 200}).json()["puissance_w"] == 200
    )

    noeuds = {n["id"]: n for n in c.get("/api/noeuds").json()}
    assert noeuds["esp32-01"]["status"] == "online" and noeuds["esp32-01"]["derniere_mesure"]
    assert noeuds["esp32-03"]["status"] is None and noeuds["esp32-03"]["zones"] == ["z2"]


def test_camera_regions(api):
    c = api.client
    r = c.put(
        "/api/cameras/cam-z1-a/regions",
        json={
            "regions": [
                {"emplacement_id": "z1-A1", "bbox": [0, 0, 0.5, 1]},
                {"emplacement_id": "z1-A2", "bbox": [0.5, 0, 0.5, 1]},
            ]
        },
    )
    assert [x["bbox"] for x in r.json()["regions"]] == [[0, 0, 0.5, 1], [0.5, 0, 0.5, 1]]
    out = {"regions": [{"emplacement_id": "z1-A1", "bbox": [0.8, 0, 0.5, 1]}]}
    assert c.put("/api/cameras/cam-z1-a/regions", json=out).status_code == 422
    other = {"regions": [{"emplacement_id": "z2-A1", "bbox": None}]}
    assert c.put("/api/cameras/cam-z1-a/regions", json=other).status_code == 422
    assert c.get("/api/cameras/cam-z1-a/derniere-image").status_code == 404
    vision(api)
    assert c.get("/api/cameras/cam-z1-a/derniere-image").json()["image_id"] == "img-1"


def test_measurements_and_dashboard(api):
    c = api.client
    for i in range(6):  # 12:00 local, day: tomato flowering 21–27 °C, HR 55–70 %
        reading(api, i * 10, "temperature", 24.0 + i, "°C")
        reading(api, i * 10, "humidite", 90.0, "%")
    reading(api, 30, "humidite_sol", 50.0, "%", noeud="esp32-02", emplacement="z1-A1")
    s = c.get(
        "/api/mesures",
        params={"zone": "z1", "type": ["temperature"], "debut": T0.isoformat(), "agregat": "brut"},
    ).json()
    (t,) = s["series"]
    assert t["n_mesures"] == 6 and t["max"] == 29.0 and len(t["points"]) == 6
    agg = c.get(
        "/api/mesures", params={"zone": "z1", "debut": T0.isoformat(), "agregat": "moy_1h"}
    ).json()
    assert {x["type"] for x in agg["series"]} == {"temperature", "humidite", "humidite_sol"}
    assert c.get("/api/mesures", params={"zone": "z9"}).status_code == 404

    vision(api)
    api.send(alert_topic("z1"), Alert(ts=T0, niveau="warning", message="HR haute", source="ctl"))
    d = c.get("/api/zones/z1/tableau").json()
    assert d["jour"] and d["consignes"]["humidite"] == [55, 70]
    tiles = {(x["type"], x["emplacement"]): x for x in d["mesures"]}
    temp = tiles[("temperature", None)]
    assert temp["valeur"] == 29.0 and temp["plage"] == [21, 27] and temp["statut"] == "alerte"
    assert tiles[("humidite", None)]["statut"] == "alerte"
    assert tiles[("humidite_sol", "z1-A1")]["statut"] == "ok"
    assert d["image"]["detections"][0]["emplacement"] == "z1-A1"
    assert d["alertes"][0]["message"] == "HR haute"
    assert {a["id"] for a in d["actionneurs"]} >= {"ventilo-z1", "led-z1"}


def test_vision_and_images(api, tmp_path):
    c = api.client
    v = vision(api)
    rows = c.get("/api/vision", params={"emplacement": "z1-A1"}).json()
    assert rows[0]["classe"] == "tomate/mildiou" and rows[0]["image_id"] == "img-1"
    assert c.get("/api/images/img-1").status_code == 404
    jpeg = b"\xff\xd8\xff\xe0fake-jpeg"
    up = {
        "resultat": v.model_dump(mode="json"),
        "extras": {"probs": [0.1]},
        "jpeg_b64": base64.b64encode(jpeg).decode(),
    }
    assert c.post("/api/images", json=up).status_code == 201
    assert (tmp_path / "images" / "2026-07-15" / "img-1.json").is_file()
    r = c.get("/api/images/img-1")
    assert r.status_code == 200 and r.content == jpeg
    assert c.get("/api/images/img-1", params={"gradcam": 1}).status_code == 404
    assert c.get("/api/images/..%2Fsecret").status_code in (404, 422)
    assert c.get("/api/images/.hidden").status_code == 422
    bad = dict(up, jpeg_b64=base64.b64encode(b"GIF89a").decode())
    assert c.post("/api/images", json=bad).status_code == 422


def test_consumption(api):
    c = api.client
    api.send(state_topic("z1", "chauffage"), ActuatorState(ts=T0 - timedelta(hours=2), action="on"))
    api.send(
        state_topic("z1", "chauffage"), ActuatorState(ts=T0 - timedelta(hours=1), action="off")
    )
    r = c.get("/api/consommation", params={"periode": "semaine", "zone": "z1"}).json()
    assert r["estime"] and len(r["par_jour"]) == 7 and r["jour_en_cours"]
    assert r["totaux"]["kwh"] == pytest.approx(1.5)
    assert r["par_jour"][-1]["actionneurs"]["chauffage-z1"]["kwh"] == pytest.approx(1.5)
    assert r["dli_cible"] == {"z1": 25}


def test_alerts(api):
    c = api.client
    for msg in ("HR haute", "T° basse"):
        api.send(alert_topic("z1"), Alert(ts=T0, niveau="warning", message=msg, source="ctl"))
    alerts = c.get("/api/alertes", params={"actives": 1}).json()
    assert len(alerts) == 2
    assert c.post(f"/api/alertes/{alerts[0]['id']}/acquitter").json()["acquittee"]
    assert len(c.get("/api/alertes", params={"actives": 1}).json()) == 1
    assert len(c.get("/api/alertes").json()) == 2
    assert c.post("/api/alertes/inconnue/acquitter").status_code == 404
