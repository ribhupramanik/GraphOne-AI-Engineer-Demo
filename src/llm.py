import json
import logging
import re

from .net import FetchError

LOG = logging.getLogger(__name__)


class NoProviderAvailable(RuntimeError):
    pass


def dense_chunk(text, *, max_chars=20000):
    if max_chars < 512:
        raise ValueError("Character budget too small")
    if len(text) <= max_chars:
        return text
    chunks = [s.strip() for s in re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z])", text) if s.strip()]
    priority = re.compile(r"\b(?:founded|employees|pricing|publication|published|github|"
                          r"arxiv|research|company|product|launch|announced|created|date|\d{4})\b", re.I)
    ranked = sorted(enumerate(chunks), key=lambda p: (-len(priority.findall(p[1])), p[0]))
    picked = []
    used = 0
    for index, segment in ranked:
        if used + len(segment) + 2 > max_chars:
            continue
        picked.append((index, segment))
        used += len(segment) + 2
    if not picked:
        return text[:max_chars]
    return "\n\n".join(segment for _, segment in sorted(picked))[:max_chars]


def parse_evidence_json(model_response, source_text):
    if isinstance(model_response, dict):
        obj = model_response
    else:
        clean = model_response.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean)
        obj = json.loads(clean)
    fields = obj.get("fields")
    if not isinstance(fields, dict):
        raise ValueError("Missing fields object")
    result = {}
    for name, record in fields.items():
        if not isinstance(record, dict):
            continue
        evidence = record.get("evidence")
        value = record.get("value")
        if not isinstance(evidence, str) or not evidence.strip() or value in (None, ""):
            continue
        evidence_compact = " ".join(evidence.split()).casefold()
        source_compact = " ".join(source_text.split()).casefold()
        if evidence_compact not in source_compact:
            LOG.warning("dropping ungrounded LLM field %s", name)
            continue
        if isinstance(value, str) and " ".join(value.split()).casefold() not in evidence_compact:
            LOG.warning("dropping LLM field not directly supported by quoted evidence %s", name)
            continue
        if isinstance(value, (int, float)) and str(value) not in evidence_compact:
            LOG.warning("dropping numerical LLM field not directly supported by quoted evidence %s", name)
            continue
        result[name] = value
    return result


class MultiTierExtractor:
    def __init__(self, fetcher, settings):
        self.fetcher = fetcher
        self.gemini_model = getattr(settings, "gemini_model", "gemini-3.5-flash-lite")
        self.providers = []
        if settings.gemini_key:
            self.providers.append(("Gemini Flash", "gemini", settings.gemini_key))
        if settings.groq_key:
            self.providers.append(("Groq GPT-OSS", "groq", settings.groq_key))
        if settings.deepseek_key:
            self.providers.append(("DeepSeek", "deepseek", settings.deepseek_key))

    async def _complete(self, kind, key, payload):
        sys_prompt = (
            "Extract only facts explicitly evidenced by the supplied source. "
            'Return JSON {"fields": {"field_name": {"value": value, "evidence": "exact source quote"}}}. '
            "Never guess missing details. Quotes must be contiguous text from the source."
        )
        if kind == "gemini":
            response = await self.fetcher.request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent",
                method="POST", headers={"x-goog-api-key": key},
                json_body={"systemInstruction": {"parts": [{"text": sys_prompt}]},
                           "contents": [{"parts": [{"text": payload}]}],
                           "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 1800}})
            return response["candidates"][0]["content"]["parts"][0]["text"]
        url, model = (
            ("https://api.groq.com/openai/v1/chat/completions", "openai/gpt-oss-20b") if kind == "groq"
            else ("https://api.deepseek.com/chat/completions", "deepseek-chat")
        )
        response = await self.fetcher.request(
            url, method="POST", headers={"Authorization": "Bearer " + key},
            json_body={"model": model, "temperature": 0,
                       "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": sys_prompt},
                                    {"role": "user", "content": payload}],
                       "max_tokens": 1800})
        return response["choices"][0]["message"]["content"]

    async def extract(self, source_text, wanted_fields):
        if not self.providers:
            raise NoProviderAvailable("Set GEMINI_API_KEY, GROQ_API_KEY or DEEPSEEK_API_KEY")
        last_error = None
        for name, kind, key in self.providers:
            budget = 20000
            for _ in range(4):
                chunk = dense_chunk(source_text, max_chars=budget)
                payload = "Wanted fields: " + ", ".join(wanted_fields) + "\n\nSOURCE:\n" + chunk
                try:
                    raw = await self._complete(kind, key, payload)
                    grounded = parse_evidence_json(raw, chunk)
                    LOG.info("LLM provider=%s grounded_fields=%s", name, len(grounded))
                    return {k: v for k, v in grounded.items() if k in wanted_fields}
                except FetchError as exc:
                    last_error = exc
                    if exc.status == 413:
                        budget = max(512, budget // 2)
                        continue
                    LOG.warning("provider=%s rejected request status=%s detail=%s; moving to fallback", name, exc.status, getattr(exc, "detail", None) or "unavailable")
                    break
                except (KeyError, ValueError, IndexError, TypeError) as exc:
                    last_error = exc
                    LOG.warning("provider=%s returned malformed or ungrounded data", name)
                    break
        raise NoProviderAvailable("All configured providers failed") from last_error
