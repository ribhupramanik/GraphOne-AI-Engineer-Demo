"""Conservative, provenance-aware organization name resolution.

A directory-observed name is not presented as an independently verified alias.
Fuzzy scores do not establish identity, so similarity alone never merges entities.
"""

import html
import re
import unicodedata
from collections import defaultdict


SEED_ENTITIES = [
    "OpenAI", "Anthropic", "Google DeepMind", "Hugging Face", "Mistral AI", "Cohere",
    "Perplexity", "Stability AI", "Runway", "Midjourney", "Databricks", "Scale AI",
    "Together AI", "Replicate", "Pinecone", "Weaviate", "LangChain", "LlamaIndex",
    "Weights & Biases", "Character.AI", "ElevenLabs", "Suno", "Pika", "Synthesia",
    "Jasper", "Copy.ai", "Glean", "Harvey", "Cursor", "Anysphere", "Replit",
    "Poolside", "Sakana AI", "Cognition", "Devin", "Adept", "Inflection AI",
    "Groq", "Fireworks AI", "Modal", "Baseten", "OctoAI", "Deepgram", "AssemblyAI",
    "Speechmatics", "Hume AI", "Rasa", "Vercel", "Figma", "Canva", "Notion",
]

LEGAL_SUFFIXES = frozenset({
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
    "co", "company", "gmbh", "plc", "pvt", "private", "pte", "ag", "bv",
    "sa", "sas", "sarl", "oy", "ab", "kg",
})


def clean_name(name):
    if not isinstance(name, str):
        return ""
    return " ".join(html.unescape(name).strip().split())


def normalise_name(name):
    """Compute a comparison key, never a display name."""
    name = clean_name(name)
    if not name:
        return ""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    words = re.findall(r"[a-z0-9]+", name)
    while len(words) > 1 and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return "".join(words)


def _register(index, canonical):
    key = normalise_name(canonical)
    if key:
        index[key].add(canonical)


def _preferred_label(names):
    """Prefer readable labels from actual source records, never invent casing."""
    return sorted(names, key=lambda s: (
        -(" " in s),
        -(sum(c.isupper() for c in s[1:]) > 0),
        -(s[:1].isupper()),
        -(sum(c.isupper() for c in s) < len(s)),
        len(s), s.casefold()
    ))[0]


class Resolver:
    def __init__(self, seeds=None, directory_names=(), observed_job_names=()):
        self.canonicals = list(SEED_ENTITIES if seeds is None else seeds)
        self.aliases = {}
        self._seed_collisions = set()
        for name in self.canonicals:
            key = normalise_name(name)
            if key in self.aliases and self.aliases[key] != name:
                self._seed_collisions.add(key)
            else:
                self.aliases[key] = name
        for key in self._seed_collisions:
            self.aliases.pop(key, None)
        self.aliases.update({"gdeepmind": "Google DeepMind"})

        directory = defaultdict(set)
        for name in directory_names:
            name = clean_name(name)
            if name:
                _register(directory, name)
        self.directory = {
            key: _preferred_label(names)
            for key, names in directory.items()
            if len({n.casefold() for n in names}) == 1
        }
        self.directory_collisions = {
            key for key, names in directory.items()
            if len({n.casefold() for n in names}) > 1
        }

        jobs = defaultdict(set)
        for name in observed_job_names:
            name = clean_name(name)
            if name:
                _register(jobs, name)
        self.job_variants = {
            key: _preferred_label(names)
            for key, names in jobs.items()
            if len(names) > 1 and key not in self.directory_collisions
        }

    def resolve(self, raw, *, source="job", company_domain=None):
        """Return (label, evidence-qualified method, confidence).

        The unused domain argument is accepted for backward compatibility; domains
        cannot substantiate ownership without an independently verified domain map.
        """
        name = clean_name(raw)
        if not name:
            return None, "missing", 0.0
        key = normalise_name(name)
        if not key:
            return name, "unresolved_preserved", 0.0

        if key in self.aliases:
            return self.aliases[key], "exact_seed_alias", 1.0

        if source == "directory":
            return name, "directory_observed_name", 0.8

        if key in self.directory and len(key) >= 6:
            return self.directory[key], "directory_name_match", 0.95

        if key in self.job_variants and len(key) >= 6:
            return self.job_variants[key], "observed_name_variants", 0.9

        return name, "unresolved_preserved", 0.0
