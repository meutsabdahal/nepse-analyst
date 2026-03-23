import os
from dotenv import load_dotenv

load_dotenv()

# LLM Settings
LLM_PROVIDER    = os.getenv("LLM_PROVIDER", "groq")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL      = "llama-3.1-8b-instant"
OLLAMA_MODEL    = "llama3.2:3b"
OLLAMA_BASE_URL = "http://localhost:11434"

# Embedding Settings
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# Paths 
BASE_DIR         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH          = os.path.join(BASE_DIR, "data", "processed", "nepse.db")
VECTOR_STORE_DIR = os.path.join(BASE_DIR, "data", "vector_store")
NEWS_CACHE_DIR   = os.path.join(BASE_DIR, "data", "raw", "news_cache")
EVAL_DIR         = os.path.join(BASE_DIR, "evaluation")

# Retrieval Settings
TOP_K_RAG       = 5
MAX_SQL_RETRIES = 3
NEWS_COLLECTION = "nepse_news"

# Scraping Settings
SCRAPE_DELAY_SEC = 3      # minimum seconds between requests
MAX_ARTICLES     = 5000   # cap on total news corpus size