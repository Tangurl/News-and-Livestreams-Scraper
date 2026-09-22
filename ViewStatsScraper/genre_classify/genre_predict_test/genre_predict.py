"""
genre_predict — จัดหมวดรายการทีวี (19 หมวด ตาม classification.txt)
โมเดล: scikit-learn (TF-IDF char n-gram + pythainlp word) + LinearSVC

โมดูลนี้ "ยืนได้ด้วยตัวเอง" — โปรแกรมอื่น import ไปใช้ได้เลย

    from genre_predict import genre_predict
    genre_predict("ข่าวค่ำ")                         # -> "ข่าวทั่วไป"
    genre_predict("Foodwork", "ตลาดน้ำอัมพวา ของกินเพียบ")
    genre_predict(program_name="...", description="...")

ต้องมี:  genre_predict.py + genre_clf_newtax.joblib (โฟลเดอร์เดียวกัน หรือชี้ path เอง)
pip:     scikit-learn  pythainlp  joblib  numpy

CLI:
    python genre_predict.py "ข่าวค่ำ"
    echo "ข่าวค่ำ" | python genre_predict.py         # อ่านทีละบรรทัดจาก stdin
"""

from __future__ import annotations

import os
import re
import sys
from functools import lru_cache

__all__ = ["genre_predict", "genre_predict_scores", "CATEGORIES", "load_model"]

# 19 หมวดตาม classification.txt
CATEGORIES = [
    "นำเสนอ/ขายสินค้า(สุขภาพ)", "ข่าวทั่วไป", "ข่าวด่วน", "ข่าวการเมือง",
    "ข่าววิเคราะห์/สรุปประเด็น", "ข่าวต่างประเทศ/ทั่วโลก", "ซีรี่ย์/ละคร", "สารคดี",
    "วาไรตี้", "บันเทิง", "การศึกษา/ความรู้", "ศาสนา/ธรรมะ", "สังคม/ชุมชน",
    "เด็ก/การ์ตูน", "ทอล์ก/สัมภาษณ์", "อาหาร", "กีฬา", "เพลง", "ปิดสถานี",
]

_MODEL_FILENAME = "genre_clf_newtax.joblib"
_KEEP = re.compile(r"[ก-๙A-Za-z0-9]")


@lru_cache(maxsize=1)
def _stopwords() -> frozenset:
    try:
        from pythainlp.corpus import thai_stopwords
        return frozenset(thai_stopwords())
    except Exception:
        return frozenset()


@lru_cache(maxsize=50000)
def thai_tokenizer_list(text: str) -> tuple[str, ...]:
    """ตัดคำไทยด้วย pythainlp (newmm) + ตัดช่องว่าง/เครื่องหมาย/stopword
    ** ใช้เป็น tokenizer ของ TfidfVectorizer ตอนเทรน — ห้ามเปลี่ยนพฤติกรรม **
    """
    from pythainlp.tokenize import word_tokenize
    sw = _stopwords()
    out = []
    for t in word_tokenize(str(text), engine="newmm", keep_whitespace=False):
        t = t.strip().lower()
        if not t or not _KEEP.search(t) or t in sw or t.isdigit():
            continue
        out.append(t)
    return tuple(out)


def make_text(program_name: str, episode_name: str = "", description: str = "") -> str:
    """รวมข้อความเป็น 1 feature — ชื่อรายการซ้ำ 2 ครั้งเพื่อเพิ่มน้ำหนัก"""
    name = " ".join(str(program_name or "").split())
    return " ".join([name, name, str(episode_name or ""), str(description or "")]).strip()


_model = None


def _find_model() -> str:
    env = os.environ.get("GENRE_MODEL_PATH")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, _MODEL_FILENAME),
                 os.path.join(here, "model", _MODEL_FILENAME),
                 os.path.join(here, "..", "model", _MODEL_FILENAME)):
        if os.path.isfile(cand):
            return cand
    return os.path.join(here, _MODEL_FILENAME)   # ให้ error ชี้ตำแหน่งที่คาดไว้


def load_model(path: str | os.PathLike | None = None):
    """โหลด (และ cache) โมเดล
    path ปริยาย: env GENRE_MODEL_PATH > ./genre_clf_newtax.joblib > ./model/... > ../model/...
    """
    global _model
    if _model is not None and path is None:
        return _model
    import joblib
    bundle = joblib.load(path or _find_model())
    if path is None:
        _model = bundle
    return bundle


def genre_predict(program_name: str, episode_name: str = "", description: str = "",
                  *, model_path: str | None = None) -> str:
    """คืนชื่อหมวด (1 ใน CATEGORIES)"""
    pipe = load_model(model_path)["pipeline"]
    return str(pipe.predict([make_text(program_name, episode_name, description)])[0])


def genre_predict_scores(program_name: str, episode_name: str = "", description: str = "",
                         *, top: int = 5, model_path: str | None = None) -> list[tuple[str, float]]:
    """คืน [(หมวด, คะแนน)] เรียงจากมากไปน้อย (คะแนน = decision_function ของ LinearSVC)"""
    import numpy as np
    pipe = load_model(model_path)["pipeline"]
    text = make_text(program_name, episode_name, description)
    classes = list(pipe.classes_)
    if hasattr(pipe, "predict_proba"):
        vals = np.asarray(pipe.predict_proba([text])[0], dtype=float)
    else:
        vals = np.asarray(pipe.decision_function([text])[0], dtype=float)
    order = np.argsort(vals)[::-1][:top]
    return [(str(classes[i]), float(vals[i])) for i in order]


def _cli() -> None:
    args = sys.argv[1:]
    if args:
        print(genre_predict(args[0], args[1] if len(args) > 1 else "",
                            args[2] if len(args) > 2 else ""))
        return
    for line in sys.stdin:
        line = line.strip()
        if line:
            print(f"{line}\t{genre_predict(line)}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    _cli()
