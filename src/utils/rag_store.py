# src/utils/rag_store.py
from __future__ import annotations
import os
import json
import numpy as np
from typing import List, Dict, Tuple, Optional
from config.servicenow_settings import settings

# Local TF-IDF
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import joblib
# Azure OpenAI (import lazily and only when needed)
def _try_import_azure():
   try:
       from openai import AzureOpenAI
       return AzureOpenAI
   except Exception as e:
       raise RuntimeError("Azure OpenAI SDK not installed. `pip install openai`") from e

# ---------- Paths & small helpers ----------
def _ensure_dir(path: str) -> None:
   os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
def _load_docs(json_path: str) -> List[Dict]:
   """Load [{id, pattern, resolution}] and produce unified text."""
   with open(json_path, "r", encoding="utf-8") as f:
       raw = json.load(f)
   # Accept either list of dicts or {"items":[...]}
   items = raw["items"] if isinstance(raw, dict) and "items" in raw else raw
   docs = []
   for d in items:
       doc = {
           "id": d.get("id") or d.get("kb_id") or "",
           "pattern": (d.get("pattern") or d.get("text") or "").strip(),
           "resolution": (d.get("resolution") or d.get("answer") or "").strip(),
       }
       # unified “text” used by vectorizers/embedders
       doc["text"] = f"{doc['pattern']}\n{doc['resolution']}".strip()
       docs.append(doc)
   return docs

# ---------- Azure backend (embeddings) ----------
def _embed_azure(texts: List[str]) -> np.ndarray:
   AzureOpenAI = _try_import_azure()
   client = AzureOpenAI(
       api_key=settings.AZURE_OPENAI_API_KEY,
       azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
       api_version=settings.AZURE_OPENAI_API_VERSION,
   )
   # batch in one call (the SDK accepts list)
   resp = client.embeddings.create(
       input=texts,
       model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
   )
   # Return (n_docs, dim)
   arr = np.vstack([np.array(d.embedding, dtype=np.float32) for d in resp.data])
   return arr

# ---------- Public: build + search ----------
def build_store(json_path: str) -> dict:
   """
   Build vector store from KB JSON and persist to /data on first run.
   - local/TF-IDF  -> joblib (vectorizer + matrix) at settings.RAG_TFIDF_PATH
   - azure/embeds  -> npz (X + docs) at settings.RAG_STORE_PATH
   Returns a short dict describing what was written/used.
   """
   docs = _load_docs(json_path)
   texts = [d["text"] for d in docs]
   backend = (settings.RAG_BACKEND or "local").lower()
   if backend == "local":
       # TF-IDF
       tfidf_path = settings.RAG_TFIDF_PATH  # e.g., data/rag_tfidf.joblib
       _ensure_dir(tfidf_path)
       vect = TfidfVectorizer(stop_words="english", max_features=50000)
       X = vect.fit_transform(texts)                         # sparse
       joblib.dump({"vect": vect, "X": X, "docs": docs}, tfidf_path)
       return {
           "ok": True,
           "backend": "local",
           "store_path": tfidf_path,
           "count": len(docs),
       }
   elif backend == "azure":
       # Embeddings
       npz_path = settings.RAG_STORE_PATH  # e.g., data/rag_azure.npz
       _ensure_dir(npz_path)
       X = _embed_azure(texts)                                 # (n, dim)
       # Save both vectors and docs
       np.savez_compressed(npz_path, X=X, docs=np.array(docs, dtype=object))
       return {
           "ok": True,
           "backend": "azure",
           "store_path": npz_path,
           "count": len(docs),
       }
   else:
       raise ValueError(f"Unknown RAG_BACKEND: {backend!r}")

def search(query: str, top_k: int = 3, min_sim: float | None = None) -> List[Dict]:
   """
   Retrieve top_k matches from the persisted store.
   Returns: [{"id": "...", "pattern": "...", "resolution": "...", "score": 0.xx}, ...]
   """
   backend = (settings.RAG_BACKEND or "local").lower()
   min_sim = settings.RAG_MIN_SIM if min_sim is None else float(min_sim)
   if backend == "local":
       # Load TF-IDF
       tfidf_path = settings.RAG_TFIDF_PATH
       if not os.path.exists(tfidf_path):
           # Build on the fly from KB file the first time
           build_store(settings.RAG_KB_PATH)
       blob = joblib.load(tfidf_path)  # {vect, X, docs}
       vect, X, docs = blob["vect"], blob["X"], blob["docs"]
       q = vect.transform([query])
       sims = cosine_similarity(q, X).ravel()                 # (n,)
       order = np.argsort(-sims)[:top_k]
       return [
           {**docs[i], "score": float(sims[i])}
           for i in order
           if float(sims[i]) >= min_sim
       ]
   elif backend == "azure":
       npz_path = settings.RAG_STORE_PATH
       if not os.path.exists(npz_path):
           # Build on the fly from KB file the first time
           build_store(settings.RAG_KB_PATH)
       blob = np.load(npz_path, allow_pickle=True)
       X = blob["X"]                # (n, dim)
       docs = list(blob["docs"])    # object array -> py list
       q = _embed_azure([query])[0]                             # (dim,)
       # cosine similarity with numeric stability
       qn = np.linalg.norm(q) + 1e-8
       Xn = np.linalg.norm(X, axis=1, keepdims=True) + 1e-8
       sims = (X @ q) / (Xn.ravel() * qn)                       # (n,)
       order = np.argsort(-sims)[:top_k]
       return [
           {**docs[i], "score": float(sims[i])}
           for i in order
           if float(sims[i]) >= min_sim
       ]
   else:
       raise ValueError(f"Unknown RAG_BACKEND: {backend!r}")