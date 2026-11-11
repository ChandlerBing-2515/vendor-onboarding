"""AI connection check: lists the models your key can use, then tests the
configured model with one tiny request.
Run:  python checks/check_ai.py"""

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI  # noqa: E402

from core.extraction import DEFAULT_MODELS, GEMINI_BASE_URL, KEY_NAMES  # noqa: E402

secrets_path = ROOT / ".streamlit" / "secrets.toml"
if not secrets_path.exists():
    raise SystemExit("No .streamlit/secrets.toml found.")
secrets = tomllib.loads(secrets_path.read_text())

provider = str(secrets.get("AI_PROVIDER", "openai")).lower()
key = secrets.get(KEY_NAMES.get(provider, ""), "")
model = secrets.get("AI_MODEL") or DEFAULT_MODELS.get(provider)
print(f"Provider: {provider} | configured model: {model} | key found: {bool(key)}")
if not key:
    raise SystemExit(f"Add {KEY_NAMES.get(provider)} to secrets.toml.")

client = (OpenAI(api_key=key, base_url=GEMINI_BASE_URL) if provider == "gemini"
          else OpenAI(api_key=key))

try:
    names = sorted(m.id.removeprefix("models/") for m in client.models.list())
    wanted = [n for n in names if ("flash" in n or "mini" in n) and "embed" not in n
              and "image" not in n and "tts" not in n and "audio" not in n]
    print("\nText models your key can use (pick one for AI_MODEL):")
    for n in wanted or names:
        print("  ", n)
except Exception as exc:
    print(f"\nCould not list models: {type(exc).__name__}: {exc}")

print(f"\nTesting '{model}' with one small request...")
try:
    reply = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": "Reply with the single word: OK"}])
    print("Success. The model replied:", reply.choices[0].message.content.strip())
except Exception as exc:
    print(f"FAILED: {type(exc).__name__}: {exc}")
    print("Copy a name from the list above into AI_MODEL in secrets.toml and run this again.")
