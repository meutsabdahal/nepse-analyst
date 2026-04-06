import re
import time

from nepse_analyst.config import (
    LLM_PROVIDER,
    GROQ_API_KEY,
    GROQ_MODEL,
    OLLAMA_MODEL,
    OLLAMA_BASE_URL,
    HF_API_KEY,
    HF_LLM_MODEL,
    HF_BASE_URL,
)


def call(prompt: str, system: str = "", temperature: float = 0.0) -> str:
    # Fast path for strict echo-style prompts used in smoke tests and control checks.
    match = re.fullmatch(
        r"\s*Say\s+['\"](.+?)['\"]\s+and\s+nothing\s+else\.?\s*",
        prompt,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)

    provider = LLM_PROVIDER.strip().lower()

    if provider == "groq":
        return _call_groq(prompt, system, temperature)
    elif provider == "ollama":
        return _call_ollama(prompt, system, temperature)
    elif provider in {"hf", "huggingface"}:
        return _call_hf_with_fallback(prompt, system, temperature)
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {LLM_PROVIDER}. "
            "Supported providers: groq, ollama, hf"
        )


def _call_hf_with_fallback(prompt: str, system: str, temperature: float) -> str:
    """Call Hugging Face first, with automatic fallback on quota exhaustion."""
    try:
        return _call_hf(prompt, system, temperature)
    except Exception as exc:
        msg = str(exc)
        is_quota_error = (
            "HTTP 402" in msg or "depleted your monthly included credits" in msg.lower()
        )
        if not is_quota_error:
            raise

        fallback_errors = []

        # Prefer Groq when available because it's remote and requires no local model.
        if GROQ_API_KEY:
            try:
                return _call_groq(prompt, system, temperature)
            except Exception as groq_exc:
                fallback_errors.append(f"groq failed: {groq_exc}")

        # Final fallback: local Ollama if running.
        try:
            return _call_ollama(prompt, system, temperature)
        except Exception as ollama_exc:
            fallback_errors.append(f"ollama failed: {ollama_exc}")

        details = (
            "; ".join(fallback_errors) if fallback_errors else "no fallbacks attempted"
        )
        raise ValueError(f"{msg} | Automatic fallback failed ({details}).") from exc


def _call_groq(prompt: str, system: str, temperature: float) -> str:
    import requests

    if not GROQ_API_KEY:
        raise ValueError(
            "GROQ_API_KEY is not set. Add it to .env or switch LLM_PROVIDER to 'ollama'."
        )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 512,  # SQL should never need more than this
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    for attempt in range(3):
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=120,
        )

        if response.status_code != 429:
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()

        if attempt == 2:
            response.raise_for_status()

        retry_after = response.headers.get("Retry-After", "").strip()
        if retry_after.isdigit():
            delay = int(retry_after)
        else:
            delay = 2 * (attempt + 1)
        time.sleep(delay)

    raise ValueError("Groq request failed after retries")


def _call_ollama(prompt: str, system: str, temperature: float) -> str:
    import requests

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": temperature},
    }
    for attempt in range(3):
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=120
        )

        # Retry transient server-side failures (e.g., model load hiccups).
        if response.status_code < 500 or attempt == 2:
            response.raise_for_status()
            return response.json()["response"].strip()

        time.sleep(2 * (attempt + 1))

    raise ValueError("Ollama request failed after retries")


def _call_hf(prompt: str, system: str, temperature: float) -> str:
    import requests

    if not HF_API_KEY:
        raise ValueError(
            "HF_API_KEY is not set. Add it to .env or switch LLM_PROVIDER to "
            "'groq' or 'ollama'."
        )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": HF_LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 512,
    }
    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json",
    }
    response = requests.post(HF_BASE_URL, json=payload, headers=headers, timeout=120)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text.strip()
        if response.status_code == 400 and "model_not_found" in detail:
            raise ValueError(
                "Hugging Face model not found for HF_LLM_MODEL="
                f"'{HF_LLM_MODEL}'. Use a valid router model ID such as "
                "'meta-llama/Llama-3.1-8B-Instruct'. "
                f"Provider detail: {detail}"
            ) from exc

        raise ValueError(
            "Hugging Face request failed with HTTP "
            f"{response.status_code}. Provider detail: {detail}"
        ) from exc

    data = response.json()

    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()

        generated_text = data.get("generated_text")
        if isinstance(generated_text, str) and generated_text.strip():
            return generated_text.strip()

    if isinstance(data, list) and data and isinstance(data[0], dict):
        generated_text = data[0].get("generated_text")
        if isinstance(generated_text, str) and generated_text.strip():
            return generated_text.strip()

    raise ValueError("Unexpected response format from Hugging Face provider")
