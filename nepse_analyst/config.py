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
EVAL_DIR = os.path.join(BASE_DIR, "evaluation")

# Retrieval Settings
TOP_K_RAG = _env_int("TOP_K_RAG", 5)
NEWS_STALE_DAYS = _env_int("NEWS_STALE_DAYS", 30)
MAX_SQL_RETRIES = _env_int("MAX_SQL_RETRIES", 3)
NEWS_COLLECTION = os.getenv("NEWS_COLLECTION", "nepse_news")
CORPUS_STATS_TTL_SEC = _env_int("CORPUS_STATS_TTL_SEC", 60)

# Scraping Settings
SCRAPE_DELAY_SEC = _env_int("SCRAPE_DELAY_SEC", 3)  # minimum seconds between requests
MAX_ARTICLES = _env_int("MAX_ARTICLES", 5000)  # cap on total news corpus size
