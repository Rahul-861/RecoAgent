import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getExceptions, getForecast, runForecast } from "../api/client";
import type { CashForecastResponse, ForecastCurvePoint, MatchOut } from "../types";
import { ErrorBlock, LoadingBlock } from "../components/StateBlocks";
import { exceptionLabel, impactAmount } from "../utils/evidenceFormatter";
import { formatDate, formatMoney } from "../utils/format";

function ChartBar({ cls, value, maxAbs }: { cls: string; value: number; maxAbs: number }) {
  const width = maxAbs > 0 ? (Math.abs(value) / maxAbs) * 100 : 0;
  return (
    <div className="chart-bar-line">
      <span className={`chart-bar-fill ${cls}`} style={{ width: `${width}%` }} />
      <span className="chart-bar-value mono">{formatMoney(value)}</span>
    </div>
  );
}

/**
 * Time-series built ONLY from the API's own curve points (README §11) —
 * no future points are invented. Each date shows its confirmed /
 * expected / at-risk movement; the exact table stays below the chart.
 */
function ForecastChart({ curve, horizonDays }: { curve: ForecastCurvePoint[]; horizonDays: number }) {
  const withMovement = curve.filter((p) => p.confirmed !== 0 || p.expected !== 0 || p.at_risk !== 0);
  const shown = withMovement.slice(0, 31);
  const hidden = withMovement.length - shown.length;
  const maxAbs = Math.max(
    1,
    ...withMovement.flatMap((p) => [Math.abs(p.confirmed), Math.abs(p.expected), Math.abs(p.at_risk)])
  );

  if (withMovement.length === 0) return null;

  return (
    <div className="forecast-chart">
      <div className="forecast-chart-legend">
        <span>
          <i className="legend-dot dot-confirmed" /> Confirmed
        </span>
        <span>
          <i className="legend-dot dot-expected" /> Expected
        </span>
        <span>
          <i className="legend-dot dot-atrisk" /> At risk
        </span>
      </div>
      {shown.map((p) => (
        <div className="forecast-chart-row" key={p.date}>
          <span className="forecast-chart-date mono">{formatDate(p.date)}</span>
          <div className="forecast-chart-bars">
            {p.confirmed !== 0 && <ChartBar cls="bar-confirmed" value={p.confirmed} maxAbs={maxAbs} />}
            {p.expected !== 0 && <ChartBar cls="bar-expected" value={p.expected} maxAbs={maxAbs} />}
            {p.at_risk !== 0 && <ChartBar cls="bar-atrisk" value={p.at_risk} maxAbs={maxAbs} />}
          </div>
        </div>
      ))}
      {hidden > 0 && (
        <div className="metric-sub">
          Showing the next {shown.length} days with movement — all {horizonDays} days are in the table below.
        </div>
      )}
    </div>
  );
}

export default function CashForecast() {
  const { batchId } = useParams<{ batchId: string }>();
  const [data, setData] = useState<CashForecastResponse | null>(null);
  const [exceptions, setExceptions] = useState<MatchOut[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [horizonDays, setHorizonDays] = useState(30);
  const [openingBalance, setOpeningBalance] = useState<string>("");
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(() => {
    if (!batchId) return;
    setLoading(true);
    setError(null);
    getForecast(batchId)
      .then((res) => setData(res))
      .catch((e) => {
        // No run yet is expected the first time this page is opened.
        if (!(e as Error).message?.toLowerCase().includes("no forecast run")) {
          setError((e as Error).message);
        }
        setData(null);
      })
      .finally(() => setLoading(false));
  }, [batchId]);

  useEffect(() => {
    load();
  }, [load, reloadKey]);

  // Real exception data for the "Why is cash at risk?" breakdown. The
  // forecast API does not expose a per-category at-risk split, so this
  // section is built from the reconciliation output itself — never
  // fabricated. If it can't be loaded the section is simply omitted.
  useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    getExceptions(batchId)
      .then((res) => {
        if (!cancelled) setExceptions(res.matches);
      })
      .catch(() => {
        if (!cancelled) setExceptions(null);
      });
    return () => {
      cancelled = true;
    };
  }, [batchId]);

  const handleRun = (force: boolean) => {
    if (!batchId) return;
    setRunning(true);
    setError(null);
    const opening = openingBalance.trim() === "" ? undefined : Number(openingBalance);
    runForecast(batchId, { horizonDays, openingBalance: opening, force })
      .then((res) => setData(res))
      .catch((e) => setError((e as Error).message))
      .finally(() => setRunning(false));
  };

  if (!batchId) {
    return (
      <div className="page">
        <div className="error-banner">No batch selected.</div>
      </div>
    );
  }

  const openByType = exceptions
    ? (() => {
        const map = new Map<string, { count: number; value: number }>();
        for (const m of exceptions) {
          if (m.status !== "exception") continue;
          if ((m.exception_lifecycle || "OPEN").toUpperCase() !== "OPEN") continue;
          const key = m.exception_type || "other";
          const cur = map.get(key) || { count: 0, value: 0 };
          cur.count += 1;
          cur.value += impactAmount(m) || 0;
          map.set(key, cur);
        }
        return Array.from(map.entries()).sort((a, b) => b[1].value - a[1].value);
      })()
    : [];

  return (
    <div className="page">
      <div className="page-header">
        <h1>Cash Outlook</h1>
        <p>
          Projects expected future cash movements from this batch's own reconciliation
          output — matched-but-unsettled amounts, open exceptions with a directional cash
          implication, and settlement lag learned from this batch's own confirmed matches.
          Anything the forecaster can't confidently place is reported separately, never
          silently folded into the curve.
        </p>
      </div>

      <div className="panel panel-pad" style={{ marginBottom: 18 }}>
        <div className="panel-title">Run settings</div>
        <div style={{ display: "flex", gap: 16, alignItems: "flex-end", flexWrap: "wrap" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span className="metric-sub">Horizon (days)</span>
            <input
              type="number"
              min={1}
              max={365}
              value={horizonDays}
              onChange={(e) => setHorizonDays(Number(e.target.value) || 30)}
              style={{ width: 90 }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span className="metric-sub">Opening balance (optional)</span>
            <input
              type="number"
              placeholder="0"
              value={openingBalance}
              onChange={(e) => setOpeningBalance(e.target.value)}
              style={{ width: 140 }}
            />
          </label>
          <button className="btn btn-primary btn-sm" disabled={running} onClick={() => handleRun(false)}>
            {running ? "Building cash forecast…" : data ? "Refresh forecast" : "Run forecast"}
          </button>
          {data && (
            <button className="btn btn-ghost btn-sm" disabled={running} onClick={() => handleRun(true)}>
              Force new run
            </button>
          )}
        </div>
      </div>

      {error && (
        <ErrorBlock
          context="Unable to build the cash forecast."
          message={error}
          onRetry={() => setReloadKey((k) => k + 1)}
        />
      )}

      {loading && !data && <LoadingBlock message="Building cash forecast…" />}

      {!loading && !data && !error && (
        <div className="panel panel-pad">
          <div className="empty-state">
            <h3>No forecast yet</h3>
            <p>
              Run the forecast above. The batch must already be reconciled — if it isn't,
              reconcile it first from the overview page.
            </p>
          </div>
        </div>
      )}

      {data && (
        <>
          <div className="panel panel-pad" style={{ marginBottom: 18 }}>
            <div className="panel-title">{data.horizon_days}-Day Cash Outlook</div>
            <div className="metrics-grid outlook-grid">
              <div className="panel metric-card" style={{ boxShadow: "none" }}>
                <div className="metric-value success">{formatMoney(data.totals.confirmed)}</div>
                <div className="metric-label">Confirmed cash</div>
                <div className="metric-sub">Already reconciled — context only, not projected forward.</div>
              </div>
              <div className="panel metric-card" style={{ boxShadow: "none" }}>
                <div className="metric-value accent">{formatMoney(data.totals.expected)}</div>
                <div className="metric-label">Expected cash</div>
                <div className="metric-sub">Matched but not yet settled; date from settlement lag.</div>
              </div>
              <div className="panel metric-card" style={{ boxShadow: "none" }}>
                <div className="metric-value warning">{formatMoney(data.totals.at_risk)}</div>
                <div className="metric-label">At-risk cash</div>
                <div className="metric-sub">Open exceptions with a reliable cash direction.</div>
              </div>
              <div className="panel metric-card" style={{ boxShadow: "none" }}>
                <div className="metric-value">{formatMoney(data.totals.unclassifiable)}</div>
                <div className="metric-label">Unclassifiable cash</div>
                <div className="metric-sub">
                  Excluded from the forecast curve because the reconciliation engine could not
                  confidently classify its future cash movement.
                </div>
              </div>
            </div>
            {data.opening_balance != null && (
              <div className="kv">
                <span>Opening balance</span>
                <span className="mono">{formatMoney(data.opening_balance)}</span>
              </div>
            )}
          </div>

          <div className="panel panel-pad" style={{ marginBottom: 18 }}>
            <div className="panel-title">Forecast curve</div>
            {data.curve.length === 0 ? (
              <div className="empty-state">
                <h3>Nothing projected in this horizon</h3>
                <p>
                  No EXPECTED or AT_RISK cash movements land within the next {data.horizon_days}{" "}
                  days for this batch. Check the totals above — amounts may be sitting in the
                  Unclassifiable bucket instead.
                </p>
              </div>
            ) : (
              <>
                <ForecastChart curve={data.curve} horizonDays={data.horizon_days} />
                <table className="data-table forecast-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Confirmed</th>
                      <th>Expected</th>
                      <th>At risk</th>
                      {data.opening_balance != null && <th>Running balance</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {data.curve.map((row) => (
                      <tr key={row.date}>
                        <td className="mono">{row.date}</td>
                        <td className="mono">{formatMoney(row.confirmed)}</td>
                        <td className="mono">{formatMoney(row.expected)}</td>
                        <td className="mono">{formatMoney(row.at_risk)}</td>
                        {data.opening_balance != null && (
                          <td className="mono">{formatMoney(row.running_balance)}</td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="panel panel-pad" style={{ marginBottom: 18 }}>
            <div className="panel-title">Why is cash at risk?</div>
            {data.totals.at_risk === 0 ? (
              <p className="risk-note">
                No cash is projected as at-risk for this horizon. Open exceptions that do carry a
                cash direction would appear here.
              </p>
            ) : openByType.length === 0 ? (
              <p className="risk-note">
                The at-risk amount is projected from this batch's open exceptions, but the
                per-category detail could not be loaded. Open the Exceptions page for the full
                list.
              </p>
            ) : (
              <>
                <div className="risk-breakdown">
                  {openByType.map(([type, v]) => (
                    <div className="fin-row" key={type}>
                      <span>
                        {exceptionLabel(type)} <span className="risk-count">· {v.count} open</span>
                      </span>
                      <span className="mono">{formatMoney(v.value)}</span>
                    </div>
                  ))}
                </div>
                <p className="risk-note">
                  At-risk cash is projected from open exceptions whose type has a reliable cash
                  direction (for example, refunds awaiting a bank debit). Exceptions without a
                  reliable direction stay in Unclassifiable cash until a human reviews them.
                </p>
              </>
            )}
          </div>

          <div className="panel panel-pad">
            <div className="panel-title">Run metadata</div>
            <div className="kv">
              <span>Run ID</span>
              <span className="mono">{data.run_id}</span>
            </div>
            <div className="kv">
              <span>Forecast version</span>
              <span className="mono">{data.forecast_version || "—"}</span>
            </div>
            <div className="kv">
              <span>Lag model version</span>
              <span className="mono">{data.lag_model_version || "—"}</span>
            </div>
            <div className="kv">
              <span>AI calls / failovers</span>
              <span className="mono">
                {data.forecast_llm_call_count} / {data.forecast_failover_count}
              </span>
            </div>
            <div className="kv">
              <span>Total lines classified</span>
              <span className="mono">{data.line_count}</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
