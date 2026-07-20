from __future__ import annotations
import os
from pathlib import Path
from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

# Figure out repo root: <repo>/src/config/... -> repo root = parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
class Settings(BaseSettings):
   """All configuration comes from .env with sensible defaults.
   You can override any of these with real environment variables too.
   """
   # ---------------- ServiceNow ----------------
   SN_BASE_URL: str
   SN_USERNAME: str
   SN_PASSWORD: str
   SN_POLLER_FILTER: str
   SN_POLLER_MODE: str
   # ---------------- Azure Service Bus ----------------
   SB_CONNECTION_STR: str
   SB_QUEUE_NAME: str
   # ---------------- Defaults / App behavior ----------------
   ACK_TEMPLATE: str = "Hi team – incident {number} is acknowledged by the AI agent. Details: {short_description}"
   VERIFY_TLS: bool = False
   POLL_INTERVAL_SEC: int = 5
   POLL_LOOKBACK_SEC: int = 60
   # ---------------- RAG (auto-reply) ----------------
   RAG_AUTOREPLY: bool = True
   RAG_TOP_K: int = 3
   RAG_MIN_SIM: float = 0.30
   
   # auto-close toggles
   RAG_AUTOCLOSE: bool = False          # turn ON to let AI resolve incidents
   RAG_CLOSE_MIN_SCORE: float = 0.50    # only close if score >= this
   RAG_CLOSE_STATE: str = "6"           # "6"=Resolved, "7"=Closed
   RAG_CLOSE_CODE: str = "Solved (Permanently)"

   # choose backend and mode
   RAG_BACKEND: Literal["local", "azure"] = "local"   # "local" -> TF-IDF; "azure" -> embeddings
   RAG_MODE: Literal["local", "azure"] = "local"      # which retriever to actually use

   # --------- Paths (all under <repo>/data by default) ----------
   DATA_DIR: Path = Path(os.getenv("RAG_DATA_DIR", str(_REPO_ROOT / "data")))

   RAG_STORE_PATH: Path = (DATA_DIR / "rag_store.npz")       # for embeddings (azure path)
   RAG_TFIDF_PATH: Path = (DATA_DIR / "rag_tfidf.joblib")    # for TF-IDF
   RAG_KB_PATH: Path = (DATA_DIR / "rag_kb.json")            # knowledge base JSON

   # ------------- Azure OpenAI (only used if RAG_BACKEND == "azure") -------------
   AZURE_OPENAI_ENDPOINT: Optional[str] = None
   AZURE_OPENAI_API_KEY: Optional[str] = None
   AZURE_OPENAI_API_VERSION: str = "2024-02-01"
   AZURE_OPENAI_EMBEDDING_DEPLOYMENT: Optional[str] = None

   # Pydantic settings
   model_config = SettingsConfigDict(
       env_file=str(Path(__file__).with_name(".env")),  # <repo>/src/config/.env
       env_file_encoding="utf-8",
       extra="ignore",
       case_sensitive=True,
   )
# Build the singleton settings object once
settings = Settings()
# Ensure data dir exists so first-run can persist artifacts
try:
   settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
   # never crash if folder creation races; runtime will still work
   pass