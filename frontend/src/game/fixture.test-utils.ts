// The offline demonstration greenhouse (public/demo/serre-demo.json) as a test fixture: the
// tests also check that the demo stays valid.
import demo from "../../public/demo/serre-demo.json";
import type { Demo } from "./donnees";
import type { Donnees } from "./monde";

export const DEMO = demo as unknown as Demo;
export const donneesDemo = (): Donnees => structuredClone(DEMO.donnees);
