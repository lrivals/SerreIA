"""Authentication of the writes, `WS /ws/live` and the built front (docs/12 §1, §3)."""

from fastapi.testclient import TestClient

from backend.api.app import Settings, create_app
from backend.api.sim import QueuedPublisher
from backend.live.bridge import event
from common.mqtt import SensorReading, decode, encode, sensor_topic

from .api_utils import make_api
from .backend_utils import T0, seeded_db


def test_writes_need_a_token(tmp_path):
    api = make_api(tmp_path, password="tomate")
    c = api.client
    assert c.get("/api/auth").json() == {"requise": True, "utilisateur": None}
    assert c.get("/api/zones").status_code == 200  # reads stay open
    assert c.post("/api/zones", json={"nom": "x"}).status_code == 401
    assert c.post("/api/auth/login", json={"mot_de_passe": "patate"}).status_code == 401
    login = c.post("/api/auth/login", json={"mot_de_passe": "tomate", "utilisateur": "lea"})
    h = {"Authorization": f"Bearer {login.json()['jeton']}"}
    assert c.get("/api/auth", headers=h).json()["utilisateur"] == "lea"
    assert c.post("/api/zones", json={"nom": "x"}, headers=h).status_code == 201
    # The user of the session signs the manual orders.
    r = c.post(
        "/api/actions/manuelle",
        headers=h,
        json=dict(
            zone="z1",
            actionneur="ventilo",
            action="on",
            duree_s=60,
            justification="test",
            utilisateur="quelquun",
        ),
    )
    assert r.json()["origine"] == "ui:lea"
    assert c.post("/api/auth/logout", headers=h).status_code == 200
    assert c.post("/api/zones", json={"nom": "y"}, headers=h).status_code == 401
    # Without a password, everything is open.
    open_api = make_api(tmp_path / "b")
    assert open_api.client.post("/api/zones", json={"nom": "x"}).status_code == 201


def test_live_relays_the_bus(tmp_path):
    api = make_api(tmp_path)
    r = SensorReading(ts=T0, noeud="esp32-01", valeur=21.5, unite="°C", qualite="ok")
    with api.client.websocket_connect("/ws/live") as ws:
        api.bus.publish(sensor_topic("z1", "temperature"), encode(r))
        api.bus.publish(sensor_topic("z1", "temperature"), b"{not json")  # dropped
        api.bus.publish("serre/esp32-01/status", b"offline")
        e = ws.receive_json()
        assert (e["kind"], e["zone"], e["subject"]) == ("capteur", "z1", "temperature")
        assert decode(
            sensor_topic("z1", "temperature"), SensorReading(**e["payload"]).model_dump_json()
        )
        assert ws.receive_json() == dict(
            kind="status", zone=None, subject="esp32-01", payload="offline"
        )


def test_live_without_bus():
    _, sessions = seeded_db()
    c = TestClient(create_app(sessions, None, settings=Settings(frontend=None)))
    with c.websocket_connect("/ws/live") as ws:
        assert ws.receive_json()["kind"] == "info"
    assert event("serre/z1/capteur/temperature", b"{}") is None


def test_front_is_served(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    _, sessions = seeded_db()
    c = TestClient(create_app(sessions, None, settings=Settings(frontend=dist)))
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/decisions/dec-1").text == "<div id=root></div>"  # client-side route
    assert c.get("/api/inconnue").status_code == 404
    assert c.get("/../../etc/passwd").text == "<div id=root></div>"
    assert c.get("/api/zones").status_code == 200


def test_sim_publisher_queues_the_api_messages():
    class Runner:
        def __init__(self):
            import queue

            self.inbox = queue.Queue()

    runner = Runner()
    QueuedPublisher(runner).publish("serre/z1/decision", {"x": 1})
    assert runner.inbox.get_nowait() == ("serre/z1/decision", {"x": 1})
