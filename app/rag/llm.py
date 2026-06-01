import asyncio
import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "transformers").lower()
if LLM_PROVIDER == "transformer":
    LLM_PROVIDER = "transformers"
LLM_MODEL = os.getenv("VLLM_MODEL", "sh2orc/Llama-3.1-Korean-8B-Instruct")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from transformers import pipeline

        print(f"[LLM] Loading {LLM_MODEL} on CPU. This can take time once.")
        _pipeline = pipeline("text-generation", model=LLM_MODEL, device="cpu", torch_dtype="auto")
        print("[LLM] loaded.")
    return _pipeline


async def generate(system_prompt: str, user_prompt: str, max_tokens: int = 500) -> str:
    if LLM_PROVIDER == "openai":
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is empty")

        payload = {
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
            "frequency_penalty": 0.25,
        }

        def _request_openai() -> str:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions",
                data=body,
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
                    data = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"OpenAI HTTP {exc.code}: {error_body}") from exc

            return (data["choices"][0]["message"]["content"] or "").strip()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _request_openai)

    pipe = _get_pipeline()
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: pipe(
            messages,
            max_new_tokens=max_tokens,
            do_sample=False,
            temperature=None,
            top_p=None,
        ),
    )
    return (result[0]["generated_text"][-1]["content"] or "").strip()
