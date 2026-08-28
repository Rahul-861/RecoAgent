import { Routes, Route, Link, useLocation } from "react-router-dom";
import UploadPage from "./pages/UploadPage";
import ResultsDashboard from "./pages/ResultsDashboard";
import ExceptionQueue from "./pages/ExceptionQueue";
import GraphExplorer from "./pages/GraphExplorer";
import AuditExplorer from "./pages/AuditExplorer";
import CashForecast from "./pages/CashForecast";
import MemoryPage from "./pages/MemoryPage";

function LedgerMark() {
  return (
    <svg className="wordmark-mark" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="2" y="2" width="20" height="20" rx="4" fill="#2554C7" />
      <path
        d="M6.5 12.5L10 16L17.5 8"
        stroke="white"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function extractBatchId(pathname: string): string | null {
  const match = pathname.match(/\/(dashboard|exceptions|graph|audit|forecast|memory)\/([^/]+)/);
  return match ? match[2] : null;
}

function NavBar() {
  const location = useLocation();
  const batchId = extractBatchId(location.pathname);
  const isActive = (base: string) => location.pathname.startsWith(base);

  return (
    <div className="topbar">
      <Link to="/" className="wordmark">
        <LedgerMark />
        ReconAgent
      </Link>
      <div className="nav-tabs">
        <Link to="/" className={`nav-tab ${location.pathname === "/" ? "active" : ""}`}>
          Upload
        </Link>
        {batchId && (
          <>
            <Link
              to={`/dashboard/${batchId}`}
              className={`nav-tab ${isActive("/dashboard") ? "active" : ""}`}
            >
              Overview
            </Link>
            <Link
              to={`/graph/${batchId}`}
              className={`nav-tab ${isActive("/graph") ? "active" : ""}`}
            >
              Money Flow
            </Link>
            <Link
              to={`/exceptions/${batchId}`}
              className={`nav-tab ${isActive("/exceptions") ? "active" : ""}`}
            >
              Exceptions
            </Link>
            <Link
              to={`/audit/${batchId}`}
              className={`nav-tab ${isActive("/audit") ? "active" : ""}`}
            >
              Audit Trail
            </Link>
            <Link
              to={`/memory/${batchId}`}
              className={`nav-tab ${isActive("/memory") ? "active" : ""}`}
            >
              Memory
            </Link>
            <Link
              to={`/forecast/${batchId}`}
              className={`nav-tab ${isActive("/forecast") ? "active" : ""}`}
            >
              Cash Outlook
            </Link>
          </>
        )}
      </div>
      {batchId && <span className="batch-pill">{batchId}</span>}
    </div>
  );
}

export default function App() {
  return (
    <div className="app-shell">
      <NavBar />
      <Routes>
        <Route path="/" element={<UploadPage />} />
        <Route path="/dashboard/:batchId" element={<ResultsDashboard />} />
        <Route path="/graph/:batchId" element={<GraphExplorer />} />
        <Route path="/exceptions/:batchId" element={<ExceptionQueue />} />
        <Route path="/audit/:batchId" element={<AuditExplorer />} />
        <Route path="/forecast/:batchId" element={<CashForecast />} />
        <Route path="/memory/:batchId" element={<MemoryPage />} />
      </Routes>
    </div>
  );
}
