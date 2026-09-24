import json
from pathlib import Path
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
env = dotenv_values(HERE.parent / ".env")

with open(HERE / "config.js", "w", encoding="utf-8") as f:
    f.write("const ENV = " + json.dumps(env, ensure_ascii=False) + ";")