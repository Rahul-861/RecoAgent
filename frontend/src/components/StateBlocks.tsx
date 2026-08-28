interface LoadingProps {
  message: string;
}

/** Consistent loading state (README §19). */
export function LoadingBlock({ message }: LoadingProps) {
  return <div className="loading-block">{message}</div>;
}

interface ErrorProps {
  /** What failed, e.g. "Unable to load reconciliation evidence." */
  context: string;
  /** Technical detail from the API — secondary, muted. */
  message?: string | null;
  onRetry?: () => void;
}

/** Consistent error state with optional Retry (README §19). */
export function ErrorBlock({ context, message, onRetry }: ErrorProps) {
  return (
    <div className="error-banner error-banner-row" role="alert">
      <div className="error-banner-text">
        <strong>{context}</strong>
        {message && <div className="error-detail">{message}</div>}
      </div>
      {onRetry && (
        <button type="button" className="btn btn-sm error-retry" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}