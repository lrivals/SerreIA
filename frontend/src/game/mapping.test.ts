import { CATALOGUE, type Catalogue } from "./catalogue";
import { animActionneur, animJardinier, coeurs, spriteContenant, spriteCuve, spritePlante, STADES } from "./mapping";

const SANTES = ["sain", "a_surveiller", "malade", "isolee"];
const frames = new Set<string>([
  ...Object.values(CATALOGUE.plantes.sprites).flatMap((s) => Object.values(s.stades).flatMap((x) => Object.values(x))),
  ...(CATALOGUE.plantes.generique ? [CATALOGUE.plantes.generique] : []),
]);

describe("spritePlante", () => {
  it("gives an existing frame for every species × stage × health of the model", () => {
    for (const espece of [...Object.keys(CATALOGUE.plantes.especes), "concombre", "Laitue batavia"])
      for (const stade of STADES)
        for (const sante of SANTES) {
          const s = spritePlante({ espece, stade, etat_sante: sante });
          expect(s.frame, `${espece} ${stade} ${sante}`).not.toBeNull();
          expect(frames.has(s.frame!), `${espece} ${stade} ${sante} → ${s.frame}`).toBe(true);
        }
  });

  it("uses the species sprite, generic otherwise", () => {
    expect(spritePlante({ espece: "Tomate", stade: "floraison", etat_sante: "sain" })).toMatchObject({
      frame: "plants/tomato/flowering/healthy",
      generique: false,
    });
    expect(spritePlante({ espece: "concombre", stade: "floraison", etat_sante: "sain" })).toMatchObject({
      frame: CATALOGUE.plantes.generique,
      generique: true,
    });
  });

  it("maps health and the states without sprites to overlays", () => {
    expect(spritePlante({ espece: "tomate", stade: "semis", etat_sante: "a_surveiller" }).frame).toBe("plants/tomato/seedling/yellowing");
    expect(spritePlante({ espece: "tomate", stade: "semis", etat_sante: "malade" })).toMatchObject({ frame: "plants/tomato/seedling/sick", overlay: "spores" });
    expect(spritePlante({ espece: "tomate", stade: "semis", etat_sante: "isolee" })).toMatchObject({ frame: "plants/tomato/seedling/sick", overlay: "cloche" });
    expect(spritePlante({ espece: "tomate", stade: "semis", etat_sante: "retiree" }).frame).toBeNull();
  });

  it("falls back on the closest stage when a species lacks one", () => {
    const c: Catalogue = structuredClone(CATALOGUE);
    c.plantes.sprites.tomato.stades = { semis: { sain: "a" }, fructification: { sain: "b" } };
    expect(spritePlante({ espece: "tomate", stade: "croissance", etat_sante: "sain" }, c).frame).toBe("a");
    expect(spritePlante({ espece: "tomate", stade: "recolte", etat_sante: "sain" }, c).frame).toBe("b");
  });
});

describe("objects", () => {
  it("containers by type, material, then growing mode", () => {
    expect(spriteContenant({ type: "pot", materiau: "terre cuite" }, "substrat")).toBe("containers/terracotta_pot");
    expect(spriteContenant({ type: "pot", materiau: null }, "substrat")).toBe("containers/plastic_pot");
    expect(spriteContenant({ type: "canal_NFT", materiau: null }, "hydro_nft")).toBe("containers/hydroponic_nft_channel");
    expect(spriteContenant(null, "hydro_dwc")).toBe("containers/dwc_tub");
    expect(spriteContenant({ type: "inconnu", materiau: null }, "substrat")).toBe("containers/plastic_pot");
  });

  it("actuators: off is still, on animates, pwm speed follows the value", () => {
    const off = animActionneur({ type: "ventilo", etat: { action: "off", valeur: null } })!;
    expect(off.actif).toBe(false);
    expect(off.frames).toHaveLength(1);
    const on = animActionneur({ type: "ventilo", etat: { action: "on", valeur: null } })!;
    expect(on.actif && on.frames.length > 1 && on.vitesse === 1).toBe(true);
    expect(animActionneur({ type: "led", etat: { action: "pwm", valeur: 50 } })).toMatchObject({ actif: true, vitesse: 0.5, effet: "pink_purple_glow" });
    expect(animActionneur({ type: "pompe_nutri_a", etat: null })).not.toBeNull(); // closest pump
    expect(animActionneur({ type: "inconnu", etat: null })).toBeNull();
  });

  it("tank level", () => {
    expect(spriteCuve(90)).toBe("sensors/water_tank/full/0");
    expect(spriteCuve(40)).toBe("sensors/water_tank/half/0");
    expect(spriteCuve(10)).toBe("sensors/water_tank/low/0");
  });

  it("gardener actions fall back while the sprite sheet lacks them", () => {
    expect(animJardinier("marcher", "left")?.nom).toBe("walk_left");
    expect(animJardinier("arroser", "right")?.nom).toBe("watering");
    expect(animJardinier("dormir", "down")?.nom).toBe("idle");
  });

  it("hearts are bounded", () => {
    expect(coeurs("sain")).toBe(5);
    expect(coeurs("malade", 0.9, 3)).toBe(0);
    expect(coeurs("a_surveiller", 0.2, 1)).toBe(2);
  });
});
