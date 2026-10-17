import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Loading } from "./components/common";
import { Layout } from "./components/Layout";
import { LiveProvider } from "./live/LiveProvider";
import { Agent } from "./pages/Agent";
import { Constructeur } from "./pages/Constructeur";
import { Consommation } from "./pages/Consommation";
import { Dashboard } from "./pages/Dashboard";
import { Decisions } from "./pages/Decisions";
import { Equipements } from "./pages/Equipements";
import { FicheDecisionPage } from "./pages/FicheDecisionPage";

const Arbre = lazy(() => import("./pages/Arbre")); // React Flow: loaded on demand
const SerreJeu = lazy(() => import("./game/SerreJeu")); // Phaser and the sprites: loaded on demand

export function App() {
  return (
    <LiveProvider>
      <Layout>
        <Suspense fallback={<Loading />}>
          <Routes>
            <Route path="/" element={<Navigate to="/tableau" replace />} />
            <Route path="/tableau" element={<Dashboard />} />
            <Route path="/constructeur" element={<Constructeur />} />
            <Route path="/equipements" element={<Equipements />} />
            <Route path="/consommation" element={<Consommation />} />
            <Route path="/decisions" element={<Decisions />} />
            <Route path="/decisions/:id" element={<FicheDecisionPage />} />
            <Route path="/arbre" element={<Arbre />} />
            <Route path="/agent" element={<Agent />} />
            <Route path="/jeu" element={<SerreJeu />} />
            <Route path="*" element={<Navigate to="/tableau" replace />} />
          </Routes>
        </Suspense>
      </Layout>
    </LiveProvider>
  );
}
