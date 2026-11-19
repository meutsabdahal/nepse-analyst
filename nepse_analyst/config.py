import os
from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# LLM Settings
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
HF_API_KEY = os.getenv("HF_API_KEY", "")
HF_LLM_MODEL = os.getenv("HF_LLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
HF_BASE_URL = os.getenv(
    "HF_BASE_URL", "https://router.huggingface.co/v1/chat/completions"
)

# Embedding Settings
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "processed", "nepse.db")
VECTOR_STORE_DIR = os.path.join(BASE_DIR, "data", "vector_store")
NEWS_CACHE_DIR = os.path.join(BASE_DIR, "data", "raw", "news_cache")

# Retrieval Settings
TOP_K_RAG = _env_int("TOP_K_RAG", 5)
RAG_CANDIDATE_MULTIPLIER = _env_int("RAG_CANDIDATE_MULTIPLIER", 4)  # candidates fetched per result
# Added to cosine similarity (0..1) when an article is tagged with the
# company / sector the query is about. Ranks tagged articles higher without
# excluding untagged ones.
RAG_SYMBOL_BOOST = float(os.getenv("RAG_SYMBOL_BOOST", "0.1"))
RAG_SECTOR_BOOST = float(os.getenv("RAG_SECTOR_BOOST", "0.05"))
NEWS_STALE_DAYS = _env_int("NEWS_STALE_DAYS", 30)
MAX_SQL_RETRIES = _env_int("MAX_SQL_RETRIES", 3)
NEWS_COLLECTION = os.getenv("NEWS_COLLECTION", "nepse_news")
CORPUS_STATS_TTL_SEC = _env_int("CORPUS_STATS_TTL_SEC", 60)
DB_BUSY_TIMEOUT_MS = _env_int("DB_BUSY_TIMEOUT_MS", 5000)
# Limits on each query run by execute_query (model-written SQL). The timeout
# covers running the query and fetching its rows; 0 disables either limit.
SQL_TIMEOUT_MS = _env_int("SQL_TIMEOUT_MS", 5000)
SQL_MAX_ROWS = _env_int("SQL_MAX_ROWS", 500)

# Scraping Settings
SCRAPE_DELAY_SEC = _env_int("SCRAPE_DELAY_SEC", 3)  # minimum seconds between requests
MAX_ARTICLES = _env_int("MAX_ARTICLES", 5000)  # cap on total news corpus size

# News corpus health: the news step refuses to replace the vector store when the
# scrape is too small, too old, or mostly undated. Set NEWS_ALLOW_THIN_CORPUS=1
# to index anyway (a loud warning is still printed).
NEWS_MIN_ARTICLES = _env_int("NEWS_MIN_ARTICLES", 50)
NEWS_MAX_NEWEST_AGE_DAYS = _env_int("NEWS_MAX_NEWEST_AGE_DAYS", 14)  # newest article must be this recent
NEWS_ALLOW_THIN_CORPUS = os.getenv("NEWS_ALLOW_THIN_CORPUS", "").strip().lower() in ("1", "true", "yes")
