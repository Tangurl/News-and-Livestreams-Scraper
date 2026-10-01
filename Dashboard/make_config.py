import json
from pathlib import Path
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
env = dotenv_values(HERE.parent / ".env")

# config.js is loaded by dashboard.html in the browser, so only export the keys it needs.
# Never dump the whole .env here (it holds secrets such as FB_EMAIL / FB_PASSWORD).
PUBLIC_KEYS = ("NEWS_SHEET_ID",)
public_env = {key: env.get(key, "") for key in PUBLIC_KEYS}

with open(HERE / "config.js", "w", encoding="utf-8") as f:
    f.write("const ENV = " + json.dumps(public_env, ensure_ascii=False) + ";")
