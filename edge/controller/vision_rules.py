"""Level 1, "classification → action" rules (docs/10 §5), with stable and versioned ids.

A classification triggers something only once **confirmed**: same class on the last N
captures of the emplacement (`regles.yaml`: `confirmations`), each with
`classe_conf >= classe_conf_min`, and the predicted species equal to the declared species
of the plant (otherwise: an "incohérence espèce" alert only). Cameras that only see
species outside the taxonomy (`Greenhouse.vision_auto`) never trigger these rules.

Rules (class of the taxonomy, sensor condition → decision):
- `maladie.mildiou.plante`: `*/maladie/mildiou`, HR > 85 % (`risque.hr_vision`) or wet
  > 10 h, 10–25 °C → plant `malade`, HR max −10 pts for 72 h (never below
  `hr_min_abaissement`), warning; `maladie.mildiou.isolement`: plant `isolee` (proposed);
- `maladie.oidium.surveillance`: `*/maladie/oidium`, HR 60–80 %, 20–28 °C, no free water
  (`2026-fanourakis#027.0`) → warning, capture every hour, plant `a_surveiller`;
- `maladie.taches.arrosage`: septoriose, alternariose, tache_bacterienne with misting used →
  misting off, watering at the foot, manual inspection (proposed);
- `nuisible.brumisation`: `*/nuisible/*` → inspection, capture, scouting advice; light
  misting **only** for a spider mite (`tetranyque`, `acarien*`), by day, with HR < 50 % or
  VPD > 1.2 kPa, up to the HR target 60–70 % (docs/22 L8: misting is useless against
  thrips, whiteflies and aphids, and night wetness favours Botrytis) (proposed);
- `virus.isolement`: `*/virus/*` → critical alert, plant `isolee` (proposed);
- `vision.anomalie.recapture`: `sain` but `score_anomalie` > threshold → info + capture;
- `vision.anormal.surveillance`: any other abnormal class, or its condition not met → plant
  `a_surveiller`, info;
- `vision.espece.incoherence`: predicted species ≠ declared species → warning only;
- `croissance.surface.arrosage`: `surface_verte_px` −15 % over 48 h → watering (soil) or EC
  check (hydro), proposed.

The ventilation against mildew stays in `risk.py` (`maladie.mildiou.ventilation`, auto).
Whether a rule waits for the user is set per rule id in `regles.yaml` (`validation`).
"""

from dataclasses import dataclass
from datetime import timedelta

from common.mqtt import (
    Actuator,
    Detection,
    PreuveCapteur,
    Preuves,
    PreuveVision,
    SensorType,
    VisionResult,
    vision_topic,
)

from .context import Ctx
from .decisions import AlertSpec, Consigne, Order, Proposal, evidence, fmt, rule
from .psychro import vpd
from .risk import mildew_risk

TACHES = ("septoriose", "alternariose", "tache_bacterienne")
ACARIEN_HR_MAX, ACARIEN_VPD_MIN = 50.0, 1.2  # spider mite favoured (`2026-fanourakis#032.0`)
ACARIEN_HR_CIBLE = 65.0  # misting stops at the moderate HR target 60–70 %
DEPISTAGE = (
    "dépistage : cartes jaunes (aleurodes) ou bleues (thrips), une carte par 3 à 5 m² ; "
    "lutte biologique à 0,25–0,5 adulte/cm² (`2019-santiago#008.0`)"
)


def is_mite(classe: str) -> bool:
    nom = classe.split("/")[-1]
    return nom == "tetranyque" or nom.startswith("acarien")


@dataclass(frozen=True)
class Observation:
    """The detection of one capture that stands for one emplacement."""

    result: VisionResult
    det: Detection
    emplacement: str


def observations(ctx: Ctx) -> dict[tuple[str, str], list[Observation]]:
    """(camera, emplacement) -> observations in time order. Per capture and emplacement,
    the most confident abnormal detection, otherwise the most confident one."""
    out: dict[tuple[str, str], list[Observation]] = {}
    for r in sorted(ctx.zs.vision, key=lambda r: r.ts):
        if not ctx.gh.vision_auto(r.camera):
            continue
        per_emp: dict[str, Detection] = {}
        for d in r.detections:
            emp = ctx.gh.cfg.emplacement_of(r.camera, d.bbox)
            if emp is None:
                continue
            cur = per_emp.get(emp)
            if cur is None or _rank(d) > _rank(cur):
                per_emp[emp] = d
        for emp, d in per_emp.items():
            out.setdefault((r.camera, emp), []).append(Observation(r, d, emp))
    return out


def _rank(d: Detection) -> tuple[bool, float]:
    return (d.sante == "anormal", d.sante_conf if d.sante == "anormal" else d.classe_conf)


def confirmed(obs: list[Observation], n: int, seuil: float) -> list[Observation]:
    """Last n observations with the same class, all confident enough (latest first)."""
    last = obs[-n:]
    if len(last) < n or len({o.det.classe for o in last}) != 1:
        return []
    if any(o.det.classe_conf < seuil for o in last):
        return []
    return last[::-1]


def vision_evidence(c: list[Observation]) -> list[PreuveVision]:
    o = c[0]
    d = o.det
    return [
        PreuveVision(
            camera=o.result.camera,
            image_id=o.result.image_id,
            modele=o.result.modele,
            classe=d.classe,
            classe_conf=d.classe_conf,
            sante=d.sante,
            sante_conf=d.sante_conf,
            espece=d.espece,
            espece_conf=d.espece_conf,
            bbox=d.bbox,
            score_anomalie=o.result.score_anomalie,
            emplacement=o.emplacement,
            confirmations=len(c),
        )
    ]


class VisionRules:
    """All the rules of the table above for one zone, evaluated at every tick."""

    def evaluate(self, ctx: Ctx) -> list[Proposal]:
        cfg = ctx.gh.regles
        out: list[Proposal] = []
        for (_, emp), obs in observations(ctx).items():
            c = confirmed(obs, cfg.confirmations, cfg.classe_conf_min)
            if c:
                out += self._classification(ctx, emp, c)
        out += self._surface(ctx)
        return out

    # --- helpers ------------------------------------------------------------------------

    def _p(
        self,
        ctx: Ctx,
        rule_id: str,
        emp: str,
        explication: str,
        c: list[Observation] | None,
        *,
        default_validation: bool = False,
        alerte: tuple[str, str] | None = None,
        orders=(),
        captures=(),
        plantes=(),
        consigne: Consigne | None = None,
        capteurs=(),
        emplacements=None,
        version: int = 1,
    ) -> Proposal:
        key = f"{ctx.zone}/{rule_id}/{emp}"
        return Proposal(
            zone=ctx.zone,
            regle=rule(rule_id, version),
            niveau=1,
            type="exceptionnelle",
            explication=explication,
            orders=list(orders),
            alerte=AlertSpec(alerte[0], alerte[1], key) if alerte else None,
            preuves=Preuves(
                vision=vision_evidence(c) if c else [],
                capteurs=list(capteurs),
                consignes=ctx.sp.as_evidence() if ctx.sp else {},
            ),
            emplacements=list(emplacements or [emp]),
            captures=list(captures),
            plantes=list(plantes),
            consigne=consigne,
            validation=ctx.gh.regles.needs_validation(rule_id, default_validation),
            key=key,
        )

    def _recapture(self, ctx: Ctx, rule_id: str, camera: str) -> list[str]:
        """The camera again, at most every `recapture_s`."""
        last = ctx.zs.rule_fired.get(rule_id)
        period = timedelta(seconds=ctx.gh.regles.recapture_s)
        return [camera] if last is None or ctx.now - last >= period else []

    @staticmethod
    def _what(c: list[Observation]) -> str:
        d = c[0].det
        return f"{d.classe} sur {c[0].emplacement} (conf. {fmt(d.classe_conf, 2)}, {len(c)} images)"

    # --- classification -----------------------------------------------------------------

    def _classification(self, ctx: Ctx, emp: str, c: list[Observation]) -> list[Proposal]:
        d, cam = c[0].det, c[0].result.camera
        plant = ctx.gh.cfg.plant_at(emp)
        if plant is not None and d.espece != plant.espece:
            msg = (
                f"espèce prédite {d.espece} (conf. {fmt(d.espece_conf, 2)}) ≠ espèce déclarée "
                f"{plant.espece} sur {emp} : aucune action"
            )
            return [
                self._p(ctx, "vision.espece.incoherence", emp, msg, c,
                        alerte=("warning", f"{ctx.zone} : incohérence espèce, {msg}"))
            ]  # fmt: skip
        if d.sante == "sain":
            return self._anomaly(ctx, emp, c, cam)
        _, groupe, nom = (d.classe.split("/") + ["", ""])[:3]
        if groupe == "maladie" and nom == "mildiou":
            out = self._mildew(ctx, emp, c)
        elif groupe == "maladie" and nom == "oidium":
            out = self._powdery(ctx, emp, c, cam)
        elif groupe == "maladie" and nom in TACHES:
            out = self._spots(ctx, emp, c)
        elif groupe == "nuisible":
            out = self._pest(ctx, emp, c, cam)
        elif groupe == "virus":
            out = self._virus(ctx, emp, c)
        else:
            out = []
        return out or self._watch(ctx, emp, c)

    def _anomaly(self, ctx: Ctx, emp: str, c: list[Observation], cam: str) -> list[Proposal]:
        score, seuil = c[0].result.score_anomalie, ctx.gh.regles.anomalie_seuil
        if score <= seuil:
            return []
        rid = "vision.anomalie.recapture"
        msg = (
            f"{emp} classée saine mais score d'anomalie {fmt(score, 2)} > {fmt(seuil, 2)} "
            "→ recapture"
        )
        return [
            self._p(ctx, rid, emp, msg, c, alerte=("info", f"{ctx.zone} : {msg}"),
                    captures=self._recapture(ctx, rid, cam))
        ]  # fmt: skip

    def _watch(self, ctx: Ctx, emp: str, c: list[Observation]) -> list[Proposal]:
        msg = f"{self._what(c)} → plante à surveiller"
        return [
            self._p(ctx, "vision.anormal.surveillance", emp, msg, c,
                    alerte=("info", f"{ctx.zone} : {msg}"), plantes=[(emp, "a_surveiller")])
        ]  # fmt: skip

    def _mildew(self, ctx: Ctx, emp: str, c: list[Observation]) -> list[Proposal]:
        risque, regles = ctx.gh.cfg.risque, ctx.gh.regles
        hr = ctx.value(SensorType.HUMIDITE)
        t = ctx.zs.mean(SensorType.TEMPERATURE, ctx.now, timedelta(hours=12))
        wet = ctx.zs.spell(risque.hr_humectation).hours(ctx.now)
        humid = (hr is not None and hr > risque.hr_vision) or wet >= risque.humectation_h
        if not humid or t is None or not risque.t_min <= t <= risque.t_max:
            return []
        capteurs = [
            evidence(ctx.zone, SensorType.HUMIDITE, ctx.reading(SensorType.HUMIDITE),
                     seuil=risque.hr_vision),
            evidence(ctx.zone, SensorType.HUMIDITE, valeur=wet, unite="h",
                     agregat="duree_au_dessus", seuil=risque.hr_humectation),
            evidence(ctx.zone, SensorType.TEMPERATURE, valeur=t, unite="°C",
                     agregat="moyenne_12h"),
        ]  # fmt: skip
        why = f"{self._what(c)}, HR {fmt(hr or 0)} % (humectation {fmt(wet)} h) à {fmt(t)} °C"
        consigne = Consigne("humidite_max", -regles.hr_abaissement, regles.hr_abaissement_h * 3600)
        return [
            self._p(
                ctx,
                "maladie.mildiou.plante",
                emp,
                f"{why} → plante malade, consigne HR max −{regles.hr_abaissement:g} pts "
                f"pendant {regles.hr_abaissement_h:g} h",
                c,
                alerte=("warning", f"{ctx.zone} : mildiou probable sur {emp} ({why})"),
                plantes=[(emp, "malade")],
                consigne=consigne,
                capteurs=capteurs,
            ),
            self._p(
                ctx,
                "maladie.mildiou.isolement",
                emp,
                f"{why} → isoler la plante",
                c,
                default_validation=True,
                plantes=[(emp, "isolee")],
                capteurs=capteurs,
            ),
        ]

    def _powdery(self, ctx: Ctx, emp: str, c: list[Observation], cam: str) -> list[Proposal]:
        hr, t = ctx.value(SensorType.HUMIDITE), ctx.value(SensorType.TEMPERATURE)
        if hr is None or t is None:
            return []
        oid = ctx.gh.pathogenes.oidium  # pathogenes.yaml (docs/22 L7)
        if not (oid.hr[0] <= hr <= oid.hr[1] and oid.t[0] <= t <= oid.t[1]):
            return []
        rid = "maladie.oidium.surveillance"
        why = f"{self._what(c)}, HR {fmt(hr)} % et {fmt(t)} °C favorables"
        day = ctx.zs.recent(SensorType.HUMIDITE, ctx.now, timedelta(hours=24))
        amplitude = max(day) - min(day) if day else None
        if amplitude is not None and amplitude >= oid.amplitude_hr_24h:
            why += f", HR très variable ({fmt(amplitude, 0)} points en 24 h)"
        return [
            self._p(
                ctx,
                rid,
                emp,
                f"{why} → plante à surveiller, recapture toutes les "
                f"{ctx.gh.regles.recapture_s / 60:g} min",
                c,
                alerte=("warning", f"{ctx.zone} : oïdium probable sur {emp} ({why})"),
                captures=self._recapture(ctx, rid, cam),
                plantes=[(emp, "a_surveiller")],
                capteurs=[
                    evidence(ctx.zone, SensorType.HUMIDITE, ctx.reading(SensorType.HUMIDITE)),
                    evidence(ctx.zone, SensorType.TEMPERATURE, ctx.reading(SensorType.TEMPERATURE)),
                    *(
                        [
                            evidence(
                                ctx.zone,
                                SensorType.HUMIDITE,
                                valeur=amplitude,
                                unite="%",
                                agregat="amplitude_24h",
                                seuil=oid.amplitude_hr_24h,
                            )
                        ]
                        if amplitude is not None
                        else []
                    ),
                ],
                version=2,
            )
        ]

    def _spots(self, ctx: Ctx, emp: str, c: list[Observation]) -> list[Proposal]:
        """Leaf spots spread with splashing water: stop the misting (the only overhead
        watering of the greenhouse), water at the foot, inspect."""
        cfg = ctx.act(Actuator.BRUMISATEUR)
        if cfg is None:
            return []
        on = ctx.zs.actuator_on(Actuator.BRUMISATEUR)
        recent = ctx.since_on(Actuator.BRUMISATEUR) < 24 * 3600
        if not (on or recent):
            return []
        why = f"{self._what(c)}, brumisation utilisée"
        orders = [Order(Actuator.BRUMISATEUR, "off", texte="taches foliaires")] if on else []
        msg = f"{why} → arrêter l'aspersion, arrosage au pied, inspection manuelle"
        return [
            self._p(ctx, "maladie.taches.arrosage", emp, msg, c, default_validation=True,
                    alerte=("warning", f"{ctx.zone} : {msg}"), orders=orders)
        ]  # fmt: skip

    def _pest(self, ctx: Ctx, emp: str, c: list[Observation], cam: str) -> list[Proposal]:
        rid = "nuisible.brumisation"
        orders, capteurs = [], []
        msg = f"{self._what(c)} → inspection, recapture ; {DEPISTAGE}"
        if is_mite(c[0].det.classe):
            orders, capteurs, why = self._mite_misting(ctx)
            if orders:
                msg = f"{self._what(c)}, {why} → brumisation {orders[0].duree_s:g} s, " + (
                    "inspection, recapture"
                )
            elif why:
                msg = f"{self._what(c)} → inspection, recapture (pas de brumisation : {why})"
        return [
            self._p(ctx, rid, emp, msg, c, default_validation=True,
                    alerte=("warning", f"{ctx.zone} : {msg}"), orders=orders,
                    captures=[cam], capteurs=capteurs, version=2)
        ]  # fmt: skip

    def _mite_misting(self, ctx: Ctx) -> tuple[list[Order], list, str]:
        """Light misting against a spider mite: by day, dry air (HR < 50 % or VPD > 1.2 kPa),
        below the moderate HR target, never when a wet-disease index is active."""
        cfg = ctx.act(Actuator.BRUMISATEUR)
        hr, t = ctx.value(SensorType.HUMIDITE), ctx.value(SensorType.TEMPERATURE)
        if cfg is None or hr is None:
            return [], [], ""
        if not ctx.jour:
            return [], [], "nuit"
        if mildew_risk(ctx).conditions:
            return [], [], "risque mildiou actif"
        v = vpd(t, hr) if t is not None else None
        hr_max = min(ACARIEN_HR_CIBLE, ctx.sp.humidite[1] if ctx.sp else ACARIEN_HR_CIBLE)
        dry = hr < ACARIEN_HR_MAX or (v is not None and v > ACARIEN_VPD_MIN)
        if not dry or hr >= hr_max:
            return [], [], ""
        duree = ctx.gh.regles.brumisation_s
        capteurs = [
            evidence(ctx.zone, SensorType.HUMIDITE, ctx.reading(SensorType.HUMIDITE),
                     seuil=ACARIEN_HR_MAX)
        ]  # fmt: skip
        why = f"HR {fmt(hr)} %"
        if v is not None:
            capteurs.append(
                evidence(ctx.zone, SensorType.HUMIDITE, valeur=v, unite="kPa", agregat="vpd",
                         seuil=ACARIEN_VPD_MIN)
            )  # fmt: skip
            why += f", VPD {fmt(v, 2)} kPa"
        orders = [Order(Actuator.BRUMISATEUR, "on", None, duree, "acarien : air sec")]
        return orders, capteurs, why + " (acarien favorisé par l'air sec)"

    def _virus(self, ctx: Ctx, emp: str, c: list[Observation]) -> list[Proposal]:
        msg = f"{self._what(c)} → isoler la plante (pas de remède, risque de propagation)"
        return [
            self._p(ctx, "virus.isolement", emp, msg, c, default_validation=True,
                    alerte=("critique", f"{ctx.zone} : {msg}"), plantes=[(emp, "isolee")])
        ]  # fmt: skip

    # --- green surface ------------------------------------------------------------------

    def _surface(self, ctx: Ctx) -> list[Proposal]:
        regles = ctx.gh.regles
        window = timedelta(hours=regles.surface_fenetre_h)
        by_cam: dict[str, list[VisionResult]] = {}
        for r in sorted(ctx.zs.vision, key=lambda r: r.ts):
            by_cam.setdefault(r.camera, []).append(r)
        out = []
        for cam, results in by_cam.items():
            old = [r for r in results if ctx.now - r.ts >= window / 2]
            if not old:
                continue  # less than half the window of history
            ref = _mean_px(old[:3])
            now_px = _mean_px(results[-3:])
            if ref <= 0 or 1 - now_px / ref <= regles.surface_baisse:
                continue
            camcfg = ctx.gh.cfg.camera(cam)
            emps = list(camcfg.emplacements_visibles) if camcfg else []
            drop = 1 - now_px / ref
            hours = (ctx.now - old[0].ts).total_seconds() / 3600
            why = f"surface verte de {cam} en baisse de {fmt(drop * 100, 0)} % en {fmt(hours, 0)} h"
            pump = ctx.act(Actuator.POMPE_NUTRI)
            if not ctx.zcfg.hydro and pump is not None:
                duree = pump.duree_s or 30.0
                orders = [Order(Actuator.POMPE_NUTRI, "on", None, duree, "stress hydrique")]
                msg = f"{why} : stress hydrique possible → arrosage ponctuel {duree:g} s"
            else:
                orders = []
                msg = f"{why} : stress hydrique possible → vérifier l'EC et la circulation"
            capteurs = [  # the vision series itself is the measurement here
                PreuveCapteur(topic=vision_topic(ctx.zone, cam), agregat="surface_verte_moy3",
                              valeur=round(now_px, 1), unite="px",
                              seuil=round(ref * (1 - regles.surface_baisse), 1))
            ]  # fmt: skip
            out.append(
                self._p(ctx, "croissance.surface.arrosage", cam, msg, None,
                        default_validation=True, alerte=("warning", f"{ctx.zone} : {msg}"),
                        orders=orders, capteurs=capteurs, emplacements=emps)
            )  # fmt: skip
        return out


def _mean_px(results: list[VisionResult]) -> float:
    return sum(r.surface_verte_px for r in results) / len(results)
