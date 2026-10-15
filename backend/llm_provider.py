"""
LLM Provider abstraction layer.
Supports Ollama (free/local) and OpenAI (paid) with identical interface.
Switch between providers by changing LLM_PROVIDER in .env — no code changes needed.
"""
import json
import re
import httpx
from abc import ABC, abstractmethod
from typing import Optional
from config import settings


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(self, system_prompt: str, user_message: str) -> str:
        """Generate a response given system prompt and user message."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the LLM service is reachable."""
        pass


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider (free, no API key needed)."""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL

    async def generate(self, system_prompt: str, user_message: str) -> str:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0,
                        "num_predict": 2048,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except Exception:
            return False


class OpenAIProvider(LLMProvider):
    """OpenAI API provider (paid, requires API key)."""

    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.model = settings.OPENAI_MODEL
        self.base_url = "https://api.openai.com/v1"

    async def generate(self, system_prompt: str, user_message: str) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0,
                    "max_tokens": 2048,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def health_check(self) -> bool:
        if not self.api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return response.status_code == 200
        except Exception:
            return False


def get_llm_provider() -> LLMProvider:
    """Factory function that returns the configured LLM provider."""
    provider = settings.LLM_PROVIDER.lower()
    if provider == "openai":
        return OpenAIProvider()
    else:
        return OllamaProvider()


def extract_sql_from_response(response: str) -> Optional[str]:
    """
    Extract SQL query from LLM response.
    Handles various formats: raw SQL, code blocks, JSON with 'sql' key.
    """
    # Try extracting from JSON format first
    try:
        # Look for JSON in the response
        json_match = re.search(r'\{[^{}]*"sql"\s*:\s*"[^"]*"[^{}]*\}', response, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            if "sql" in parsed:
                return parsed["sql"]
    except (json.JSONDecodeError, KeyError):
        pass

    # Try extracting from ```sql code block
    sql_block = re.search(r'```sql\s*\n(.*?)\n\s*```', response, re.DOTALL | re.IGNORECASE)
    if sql_block:
        return sql_block.group(1).strip()

    # Try extracting from ``` code block
    code_block = re.search(r'```\s*\n(.*?)\n\s*```', response, re.DOTALL)
    if code_block:
        candidate = code_block.group(1).strip()
        if candidate.upper().startswith("SELECT"):
            return candidate

    # Try to find a SELECT statement directly
    select_match = re.search(r'(SELECT\s+.*?;)', response, re.DOTALL | re.IGNORECASE)
    if select_match:
        return select_match.group(1).strip()

    # Last resort: if the whole response looks like SQL
    stripped = response.strip().rstrip(";") + ";"
    if stripped.upper().startswith("SELECT"):
        return stripped

    return None


def extract_explanation_from_response(response: str) -> Optional[str]:
    """Extract the explanation/analysis text from LLM response."""
    # Try JSON format
    try:
        json_match = re.search(r'\{.*?"explanation"\s*:\s*"([^"]*)".*?\}', response, re.DOTALL)
        if json_match:
            return json_match.group(1)
    except Exception:
        pass

    # Remove SQL blocks and return remaining text
    cleaned = re.sub(r'```sql\s*\n.*?\n\s*```', '', response, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'```\s*\n.*?\n\s*```', '', cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()
    if cleaned:
        return cleaned

    return None
