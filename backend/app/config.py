"""
Central configuration for ReconAgent backend.
All tunables come from environment variables so the pipeline can be
re-tuned without touching code (see .env.example).
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # --- LLM providers ---
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    # --- Database ---
    # Defaults to a local SQLite file so the MVP runs with zero setup.
    # Point DATABASE_URL at a Supabase/Postgres connection string in prod.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./reconagent.db")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

    # --- Matching thresholds ---
    LLM_CONFIDENCE_THRESHOLD: float = float(os.getenv("LLM_CONFIDENCE_THRESHOLD", 0.75))
    FUZZY_MATCH_THRESHOLD: float = float(os.getenv("FUZZY_MATCH_THRESHOLD", 80))
    SEMANTIC_MATCH_THRESHOLD: float = float(os.getenv("SEMANTIC_MATCH_THRESHOLD", 0.72))
    TIMING_TOLERANCE_DAYS: int = int(os.getenv("TIMING_TOLERANCE_DAYS", 5))
    LLM_BATCH_SIZE: int = int(os.getenv("LLM_BATCH_SIZE", 8))
    AMOUNT_TOLERANCE: float = float(os.getenv("AMOUNT_TOLERANCE", 0.01))

    # --- Multi-source / fee-aware / settlement matching (new) ---
    # Tolerance used when checking gross - fee - refund == net, and when
    # summing a group of processor payments against one settlement/bank
    # deposit (many-to-one / one-to-many, README §14-16).
    SETTLEMENT_SUM_TOLERANCE: float = float(os.getenv("SETTLEMENT_SUM_TOLERANCE", 0.5))
    # Max number of rows considered when searching for a many-to-one /
    # one-to-many subset-sum grouping. Kept small -- this is a combinatorial
    # search over each settlement/invoice's own candidate rows only.
    MAX_GROUP_SIZE: int = int(os.getenv("MAX_GROUP_SIZE", 6))

    # --- Process versions (reproducibility / audit) ---
    PIPELINE_VERSION: str = os.getenv("PIPELINE_VERSION", "2.2.0")
    RECONCILIATION_VERSION: str = os.getenv("RECONCILIATION_VERSION", "1.0")
    NORMALIZATION_VERSION: str = os.getenv("NORMALIZATION_VERSION", "1.0")
    RULE_SET_VERSION: str = os.getenv("RULE_SET_VERSION", "1.0")
    CANDIDATE_GENERATION_VERSION: str = os.getenv("CANDIDATE_GENERATION_VERSION", "1.0")
    CONFIGURATION_VERSION: str = os.getenv("CONFIGURATION_VERSION", "1.0")

    # Auto-match only when the top candidate beats the runner-up by this margin.
    MIN_CANDIDATE_MARGIN: float = float(os.getenv("MIN_CANDIDATE_MARGIN", 0.10))
    MAX_CANDIDATES: int = int(os.getenv("MAX_CANDIDATES", 10))

    # CORS - the Vite dev server origin by default
    CORS_ORIGINS: list = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

    # --- Forward Cash Forecaster (README §41) ---
    # Additive feature: reads TransactionRow/MatchResult, never writes to
    # reconciliation tables. Same os.getenv/versioned-config pattern as
    # the reconciliation settings above -- nothing here is hard-coded
    # elsewhere in the forecaster.
    FORECAST_HORIZON_DAYS: int = int(os.getenv("FORECAST_HORIZON_DAYS", 30))
    FORECAST_VERSION: str = os.getenv("FORECAST_VERSION", "1.0")
    LAG_MODEL_VERSION: str = os.getenv("LAG_MODEL_VERSION", "1.0")
    MIN_LAG_SAMPLES_FOR_STATS: int = int(os.getenv("MIN_LAG_SAMPLES_FOR_STATS", 5))
    DEFAULT_LAG_DAYS: int = int(os.getenv("DEFAULT_LAG_DAYS", 2))
    FORECAST_AI_ENABLED: bool = os.getenv("FORECAST_AI_ENABLED", "true").lower() == "true"


settings = Settings()
