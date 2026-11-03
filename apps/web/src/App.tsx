import { NavLink, Route, Routes } from "react-router-dom";
import AskPage from "./pages/AskPage";
import ComparePage from "./pages/ComparePage";
import EvaluationPage from "./pages/EvaluationPage";
import ExplorerPage from "./pages/ExplorerPage";
import ModelsPage from "./pages/ModelsPage";
import OverviewPage from "./pages/OverviewPage";

const nav = [
  { to: "/", label: "Overview" },
  { to: "/explorer", label: "Explorer" },
  { to: "/ask", label: "Ask" },
  { to: "/compare", label: "Compare" },
  { to: "/evaluation", label: "Evaluation" },
  { to: "/models", label: "Registry" },
];

export default function App() {
  return (
    <div className="ll-shell">
      <div className="ll-orb -left-24 -top-16 h-64 w-64 bg-aqua-300/50" />
      <div
        className="ll-orb right-[-4rem] top-24 h-72 w-72 bg-coral-500/25"
        style={{ animationDelay: "1.2s" }}
      />
      <div
        className="ll-orb bottom-10 left-1/3 h-56 w-56 bg-gold-500/20"
        style={{ animationDelay: "2.4s" }}
      />

      <header className="relative z-10 border-b border-white/50 bg-white/45 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl flex-col gap-5 px-6 py-6 md:flex-row md:items-end md:justify-between">
          <div className="ll-fade">
            <p className="ll-kicker">Pharmaceutical document intelligence</p>
            <p className="mt-2 font-display text-4xl font-bold tracking-tight text-ink-950 md:text-5xl">
              Label
              <span className="bg-gradient-to-r from-aqua-600 via-coral-500 to-gold-500 bg-clip-text text-transparent">
                Lens
              </span>{" "}
              AI
            </p>
            <p className="mt-2 max-w-xl text-sm leading-6 text-ink-700">
              Colorful research workspace for DailyMed provenance, hybrid retrieval, and
              evidence-backed label comparison.
            </p>
          </div>
          <div className="ll-fade rounded-xl border border-coral-500/20 bg-coral-100/70 px-4 py-2 text-xs font-medium text-coral-700">
            Research use only · not clinical advice
          </div>
        </div>

        <nav className="mx-auto flex max-w-6xl gap-2 overflow-x-auto px-4 pb-4">
          {nav.map((item, idx) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              style={{ animationDelay: `${idx * 40}ms` }}
              className={({ isActive }) =>
                `ll-fade whitespace-nowrap rounded-xl px-3.5 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-ink-900 text-white shadow-soft"
                    : "bg-white/60 text-ink-700 hover:bg-aqua-100 hover:text-aqua-700"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="relative z-10 mx-auto max-w-6xl px-6 py-8">
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/explorer" element={<ExplorerPage />} />
          <Route path="/ask" element={<AskPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
          <Route path="/models" element={<ModelsPage />} />
        </Routes>
      </main>
    </div>
  );
}
