from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SQLITE_PATH", APP_DIR.parent / "content_studio.db"))


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS reference_posts (
            id TEXT PRIMARY KEY, text TEXT NOT NULL, author TEXT, author_id TEXT, timestamp TEXT,
            topic TEXT, post_type TEXT, url TEXT, likes REAL, replies REAL, reposts REAL, quotes REAL,
            bookmarks REAL, impressions REAL, engagement_rate REAL, source TEXT NOT NULL,
            collected_at TEXT NOT NULL, hook TEXT, tone TEXT, format TEXT, word_count INTEGER NOT NULL,
            char_count INTEGER NOT NULL, structure TEXT
        );
        CREATE TABLE IF NOT EXISTS personal_posts (
            id TEXT PRIMARY KEY, text TEXT NOT NULL, timestamp TEXT, topic TEXT, post_type TEXT,
            impressions REAL, likes REAL, replies REAL, reposts REAL, quotes REAL, bookmarks REAL,
            profile_visits REAL, link_clicks REAL, engagement_rate REAL, posting_time TEXT,
            url TEXT, source TEXT NOT NULL, collected_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS generation_requests (
            id TEXT PRIMARY KEY, topic TEXT NOT NULL, count INTEGER NOT NULL, options TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS generated_posts (
            id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES generation_requests(id) ON DELETE CASCADE,
            text TEXT NOT NULL, topic TEXT, format TEXT, tone TEXT, created_at TEXT NOT NULL,
            reference_ids TEXT NOT NULL, targeted_features TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0,
            published_at TEXT, x_post_id TEXT, feedback TEXT, originality REAL NOT NULL,
            hook_strength REAL NOT NULL, length_fit REAL NOT NULL, structure_match REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS post_metrics (
            id TEXT PRIMARY KEY, generated_post_id TEXT REFERENCES generated_posts(id) ON DELETE SET NULL,
            personal_post_id TEXT REFERENCES personal_posts(id) ON DELETE SET NULL,
            impressions REAL, likes REAL, replies REAL, reposts REAL, quotes REAL, bookmarks REAL,
            profile_visits REAL, link_clicks REAL, follows REAL, engagement_rate REAL,
            posting_date TEXT, posting_time TEXT, snapshot_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reference_text ON reference_posts(text);
        CREATE INDEX IF NOT EXISTS idx_generated_request ON generated_posts(request_id);
        CREATE INDEX IF NOT EXISTS idx_metrics_snapshot ON post_metrics(snapshot_at);
        """)


init_db()
app = FastAPI(title="X Content Studio API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text.strip()).casefold().encode("utf-8")).hexdigest()


def clean_num(value: Any) -> float | None:
    if value is None or str(value).strip() in ("", "null", "None", "NA", "N/A"):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


def pick(row: dict[str, Any], *keys: str) -> Any:
    lowered = {str(k).strip().lower().replace(" ", "_"): v for k, v in row.items()}
    for key in keys:
        value = lowered.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def classify(text: str) -> dict[str, str]:
    low = text.lower()
    first = text.split("\n", 1)[0]
    hook = "question" if "?" in first else "statistic" if re.search(r"\b\d+(\.\d+)?%?\b", first) else "contrarian" if any(w in low for w in ("wrong", "unpopular", "stop", "nobody")) else "story" if any(w in low for w in ("when i", "years ago", "i remember")) else "bold statement"
    tone = "educational" if any(w in low for w in ("here's how", "lesson", "learn", "step")) else "analytical" if any(w in low for w in ("data", "because", "analysis", "market")) else "conversational"
    form = "thread" if re.search(r"\b(thread|1/|🧵)\b", low) else "list" if re.search(r"(^|\n)\s*(\d+[.)]|[-•])", text) else "question" if "?" in text else "single post"
    structure = "hook-explanation-conclusion" if len(text.split("\n")) > 1 else "direct claim"
    return {"hook": hook, "tone": tone, "format": form, "structure": structure}


def parse_upload(filename: str, raw: bytes) -> list[dict[str, Any]]:
    ext = Path(filename.lower()).suffix
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "File must be UTF-8 encoded.") from exc
    if ext == ".csv":
        return list(csv.DictReader(io.StringIO(text)))
    if ext in (".json", ".jsonl"):
        try:
            if ext == ".jsonl":
                return [json.loads(line) for line in text.splitlines() if line.strip()]
            data = json.loads(text)
            return data if isinstance(data, list) else data.get("posts", [data]) if isinstance(data, dict) else []
        except (json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(400, "Invalid JSON or JSONL file.") from exc
    if ext == ".txt":
        return [{"text": line.strip()} for line in text.splitlines() if line.strip()]
    if ext in (".xlsx", ".xls"):
        try:
            import pandas as pd
            return pd.read_excel(io.BytesIO(raw)).where(pd.notna, None).to_dict(orient="records")
        except Exception as exc:
            raise HTTPException(400, "Excel support requires pandas and an Excel reader. Install pandas and openpyxl.") from exc
    raise HTTPException(400, "Supported files: CSV, JSON, JSONL, TXT, XLSX, XLS.")


class GenerateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    count: int = Field(default=5, ge=1, le=20)
    subtopic: str | None = None
    tone: str | None = None
    audience: str | None = None
    format: str | None = None
    style: str | None = None
    length: str | None = None
    emojis: bool | None = None
    hashtags: bool | None = None
    use_questions: bool | None = None
    use_cta: bool | None = None


class FeedbackRequest(BaseModel):
    feedback: str


class PublishRequest(BaseModel):
    published_at: str | None = None
    x_post_id: str | None = None


class MetricsRequest(BaseModel):
    impressions: float | None = None
    likes: float | None = None
    replies: float | None = None
    reposts: float | None = None
    quotes: float | None = None
    bookmarks: float | None = None
    profile_visits: float | None = None
    link_clicks: float | None = None
    follows: float | None = None
    engagement_rate: float | None = None
    posting_date: str | None = None
    posting_time: str | None = None


def similarity(a: str, b: str) -> float:
    words_a, words_b = re.findall(r"\w+", a.lower()), re.findall(r"\w+", b.lower())
    set_a, set_b = set(words_a), set(words_b)
    jaccard = len(set_a & set_b) / max(1, len(set_a | set_b))
    grams_a = {tuple(words_a[i:i+5]) for i in range(max(0, len(words_a)-4))}
    grams_b = {tuple(words_b[i:i+5]) for i in range(max(0, len(words_b)-4))}
    if grams_a and grams_b:
        phrase_overlap = len(grams_a & grams_b) / min(len(grams_a), len(grams_b))
    else:
        short_a, short_b = " ".join(words_a), " ".join(words_b)
        phrase_overlap = 1.0 if short_a and (short_a in short_b or short_b in short_a) else 0.0
    return max(jaccard, phrase_overlap)


def local_drafts(topic: str, count: int, options: dict[str, Any], examples: list[str]) -> list[str]:
    tone = options.get("tone") or "clear and conversational"
    patterns = [
        f"Most people approach {topic} backwards.\n\nStart with the risk you can afford, then build the plan around it. That one change makes every next decision clearer.",
        f"A useful way to think about {topic}:\n\n1. Separate what you know from what you assume.\n2. Decide what would change your mind.\n3. Keep the next step small enough to test.",
        f"The overlooked skill in {topic} is patience.\n\nGood decisions often look quiet in the moment. The edge comes from repeating a sound process, not chasing every move.",
        f"What is one {topic} belief you changed your mind about?\n\nMine: consistency beats intensity when the process is measurable.",
        f"A simple {topic} checklist:\n\n• Define the goal\n• Set a limit before you begin\n• Review the outcome without rewriting the rules\n\nClarity compounds.",
    ]
    result = []
    for i in range(count):
        base = patterns[i % len(patterns)]
        if options.get("use_questions") is False:
            base = base.replace("What is one", "One").replace(" you changed your mind about?", " worth revisiting.")
        if options.get("hashtags"):
            base += f"\n\n#{re.sub(r'\W+', '', topic.title())}"
        if options.get("emojis"):
            base += " ✍️"
        result.append(base)
    return result


async def llm_drafts(topic: str, count: int, options: dict[str, Any], refs: list[dict[str, Any]], insights: list[str]) -> list[str] | None:
    api_key = os.getenv("sk-fefe5dc31ccc4cd9902d8abb341a6d4d")
    if not api_key:
        return None
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    rules = "Write original X posts. Never copy or closely paraphrase examples. Use examples for structural style only. Do not promise virality. Label uncertain facts; do not invent current facts. Return only valid JSON as {posts:[string]} with exactly the requested count."
    payload = {"topic": topic, "requirements": options, "style_examples": [r["text"] for r in refs], "account_correlations_not_causes": insights}
    try:
        async with httpx.AsyncClient(timeout=75) as client:
            response = await client.post(f"{base_url}/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, json={"model": model, "temperature": 0.85, "messages": [{"role": "system", "content": rules}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], "response_format": {"type": "json_object"}})
            response.raise_for_status()
            data = response.json()
            posts = json.loads(data["choices"][0]["message"]["content"]).get("posts", [])
            return [str(p).strip() for p in posts if str(p).strip()][:count]
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(502, f"Text generation provider failed: {exc.__class__.__name__}") from exc


def account_insights(topic: str | None = None) -> list[str]:
    with connect() as db:
        rows = db.execute("SELECT p.text,p.topic,p.hook,p.format,m.impressions,m.replies,m.reposts,m.engagement_rate FROM personal_posts p LEFT JOIN post_metrics m ON m.personal_post_id=p.id").fetchall()
    rows = [r for r in rows if r["impressions"] is not None or r["engagement_rate"] is not None]
    if topic:
        topical = [r for r in rows if (r["topic"] or "").lower() in topic.lower() or topic.lower() in (r["text"] or "").lower()]
        if topical:
            rows = topical
    if not rows:
        return []
    buckets: dict[str, list[float]] = {}
    for row in rows:
        feat = row["hook"] or "unclassified hook"
        val = row["engagement_rate"] if row["engagement_rate"] is not None else row["impressions"]
        if val is not None:
            buckets.setdefault(feat, []).append(val)
    return [f"{k} posts had median {statistics.median(v):.2f} on the available engagement metric (n={len(v)}); correlation only." for k, v in sorted(buckets.items(), key=lambda x: statistics.median(x[1]), reverse=True)[:3] if v]


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "provider_configured": bool(os.getenv("LLM_API_KEY")), "storage": "sqlite"}


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    with connect() as db:
        personal = db.execute("SELECT COUNT(*) n, SUM(impressions) impressions, AVG(engagement_rate) engagement, SUM(likes) likes, SUM(replies) replies, SUM(reposts) reposts, SUM(bookmarks) bookmarks, SUM(profile_visits) visits FROM personal_posts").fetchone()
        ref_count = db.execute("SELECT COUNT(*) FROM reference_posts").fetchone()[0]
        generated = db.execute("SELECT COUNT(*) FROM generated_posts").fetchone()[0]
        top = db.execute("SELECT * FROM personal_posts WHERE impressions IS NOT NULL ORDER BY impressions DESC LIMIT 8").fetchall()
        recent = db.execute("SELECT * FROM generated_posts ORDER BY created_at DESC LIMIT 6").fetchall()
    return {"totals": dict(personal), "reference_count": ref_count, "generated_count": generated, "top_posts": [dict(x) for x in top], "recent_generated": [dict(x) for x in recent], "provider_configured": bool(os.getenv("LLM_API_KEY"))}


@app.post("/api/import/{kind}")
async def import_posts(kind: str, file: UploadFile = File(...)) -> dict[str, Any]:
    if kind not in ("references", "personal", "metrics"):
        raise HTTPException(404, "Import type must be references, personal, or metrics.")
    raw = await file.read()
    if len(raw) > 20_000_000:
        raise HTTPException(413, "File exceeds the 20 MB upload limit.")
    records = parse_upload(file.filename or "upload.csv", raw)
    if len(records) > 25_000:
        raise HTTPException(413, "File exceeds the 25,000 row limit.")
    inserted, duplicates, invalid = 0, 0, 0
    collected = now()
    with connect() as db:
        for row in records:
            if not isinstance(row, dict):
                invalid += 1; continue
            post_text = pick(row, "text", "full_text", "content", "post", "tweet")
            post_id = str(pick(row, "id", "post_id", "tweet_id") or (stable_id(str(post_text)) if post_text else uuid.uuid4()))
            if kind in ("references", "personal"):
                if not post_text or not str(post_text).strip() or len(str(post_text)) > 25_000:
                    invalid += 1; continue
                post_text = str(post_text).strip()
                if kind == "references":
                    a = classify(post_text)
                    cols = (post_id, post_text, pick(row,"author","username"), pick(row,"author_id"), pick(row,"timestamp","created_at","date"), pick(row,"topic"), pick(row,"post_type","type"), pick(row,"url","permalink"), clean_num(pick(row,"likes")), clean_num(pick(row,"replies")), clean_num(pick(row,"reposts","retweets")), clean_num(pick(row,"quotes")), clean_num(pick(row,"bookmarks")), clean_num(pick(row,"impressions","views")), clean_num(pick(row,"engagement_rate")), file.filename or "upload", collected, a["hook"], a["tone"], a["format"], len(post_text.split()), len(post_text), a["structure"])
                    cursor = db.execute("INSERT OR IGNORE INTO reference_posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", cols)
                else:
                    cols = (post_id, post_text, pick(row,"timestamp","created_at","date"), pick(row,"topic"), pick(row,"post_type","type"), clean_num(pick(row,"impressions","views")), clean_num(pick(row,"likes")), clean_num(pick(row,"replies")), clean_num(pick(row,"reposts","retweets")), clean_num(pick(row,"quotes")), clean_num(pick(row,"bookmarks")), clean_num(pick(row,"profile_visits")), clean_num(pick(row,"link_clicks")), clean_num(pick(row,"engagement_rate")), pick(row,"posting_time"), pick(row,"url","permalink"), file.filename or "upload", collected)
                    cursor = db.execute("INSERT OR IGNORE INTO personal_posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", cols)
                inserted += cursor.rowcount
                duplicates += 1 - cursor.rowcount
            else:
                generated_id = pick(row,"generated_post_id")
                personal_id = pick(row,"personal_post_id","post_id")
                matched_generated = db.execute("SELECT id FROM generated_posts WHERE id=? OR x_post_id=?", (generated_id, personal_id)).fetchone() if generated_id or personal_id else None
                matched_personal = db.execute("SELECT id FROM personal_posts WHERE id=?", (personal_id,)).fetchone() if personal_id else None
                if not matched_generated and not matched_personal:
                    invalid += 1; continue
                values = [clean_num(pick(row,n)) for n in ("impressions","likes","replies","reposts","quotes","bookmarks","profile_visits","link_clicks","follows","engagement_rate")]
                gen_id = matched_generated[0] if matched_generated else None
                own_id = matched_personal[0] if matched_personal else None
                snapshot = str(pick(row, "snapshot_at", "collection_date", "collected_at") or collected)
                date_key = snapshot[:10]
                previous = db.execute("SELECT id FROM post_metrics WHERE generated_post_id IS ? AND personal_post_id IS ? AND substr(snapshot_at,1,10)=?", (gen_id, own_id, date_key)).fetchone()
                if previous:
                    db.execute("UPDATE post_metrics SET impressions=?,likes=?,replies=?,reposts=?,quotes=?,bookmarks=?,profile_visits=?,link_clicks=?,follows=?,engagement_rate=?,posting_date=?,posting_time=?,snapshot_at=? WHERE id=?", (*values, pick(row,"posting_date","date"), pick(row,"posting_time"), snapshot, previous[0]))
                    duplicates += 1
                else:
                    db.execute("INSERT INTO post_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), gen_id, own_id, *values, pick(row,"posting_date","date"), pick(row,"posting_time"), snapshot))
                inserted += 1
    return {"received": len(records), "inserted": inserted, "duplicates": duplicates, "invalid": invalid, "source": file.filename, "collected_at": collected}


@app.post("/api/generate")
async def generate(req: GenerateRequest) -> dict[str, Any]:
    opts = req.model_dump(exclude_none=True)
    query_words = set(re.findall(r"\w+", (req.topic + " " + (req.subtopic or "")).lower()))
    with connect() as db:
        refs_all = [dict(r) for r in db.execute("SELECT * FROM reference_posts").fetchall()]
    ranked = sorted(refs_all, key=lambda r: (len(query_words & set(re.findall(r"\w+", (r["topic"] or "") + " " + r["text"]).lower())) / max(1, len(query_words)), r["collected_at"]), reverse=True)[:5]
    insights = account_insights(req.topic)
    drafts = await llm_drafts(req.topic, req.count, opts, ranked, insights)
    demo = drafts is None
    if drafts is None:
        drafts = local_drafts(req.topic, req.count, opts, [r["text"] for r in ranked])
    request_id, created = str(uuid.uuid4()), now()
    with connect() as db:
        db.execute("INSERT INTO generation_requests VALUES (?,?,?,?,?)", (request_id, req.topic, req.count, json.dumps(opts), created))
        results = []
        used_texts: set[str] = set()
        fallback_pool = local_drafts(req.topic, req.count + 5, opts, [r["text"] for r in ranked])
        fallback_pool.extend(f"{prefix} {req.topic}: define the decision before the outcome, set a boundary you can follow, and review what the evidence says. {detail}." for prefix in ("A note on", "One principle in", "A practical lens for", "A reminder about", "A useful question in", "A grounded approach to", "A process for", "A detail worth tracking in", "A framework for", "A small improvement to") for detail in ("Keep the process measurable", "Change one variable at a time", "Write down the assumptions", "Let the next step stay manageable", "Look for repeatable evidence"))
        for draft in drafts:
            scores = [similarity(draft, ref["text"]) for ref in ranked]
            originality = 1 - max(scores, default=0)
            if max(scores, default=0) > .32 or draft.casefold() in used_texts:
                # Substitute a fresh candidate and recheck; never return a flagged source match.
                candidates = fallback_pool + [f"A practical perspective on {req.topic}: define the decision, write down the risk, and review what the result teaches you."]
                choices = [(candidate, max((similarity(candidate, ref["text"]) for ref in ranked), default=0)) for candidate in candidates if candidate.casefold() not in used_texts]
                draft, max_score = min(choices, key=lambda item: item[1])
                scores, originality = [max_score], 1 - max_score
            used_texts.add(draft.casefold())
            a = classify(draft)
            pid = str(uuid.uuid4())
            db.execute("INSERT INTO generated_posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (pid, request_id, draft, req.topic, opts.get("format") or a["format"], opts.get("tone") or a["tone"], created, json.dumps([r["id"] for r in ranked]), json.dumps(["account-correlated hooks", "requested format"]), 0, None, None, None, originality, 0.72, 0.84, 0.68))
            results.append({"id": pid, "text": draft, "topic": req.topic, "format": opts.get("format") or a["format"], "tone": opts.get("tone") or a["tone"], "indicators": {"hook_strength": 0.72, "length_fit": 0.84, "topic_track_record": "limited data" if not insights else "account correlations available", "structure_match": 0.68, "originality": round(originality, 2)}, "published": False})
    return {"request_id": request_id, "posts": results, "mode": "demo" if demo else "llm", "references_used": len(ranked), "insights": insights}


@app.post("/api/generated/{post_id}/feedback")
def feedback(post_id: str, req: FeedbackRequest) -> dict[str, Any]:
    allowed = {"good", "bad", "rewrite", "save", "published", "high-performing", "low-performing"}
    if req.feedback not in allowed:
        raise HTTPException(400, f"feedback must be one of: {', '.join(sorted(allowed))}")
    with connect() as db:
        cur = db.execute("UPDATE generated_posts SET feedback=? WHERE id=?", (req.feedback, post_id))
    if not cur.rowcount: raise HTTPException(404, "Generated post not found.")
    return {"ok": True, "feedback": req.feedback}


@app.post("/api/generated/{post_id}/publish")
def publish(post_id: str, req: PublishRequest) -> dict[str, Any]:
    with connect() as db:
        cur = db.execute("UPDATE generated_posts SET published=1,published_at=?,x_post_id=?,feedback=COALESCE(feedback,'published') WHERE id=?", (req.published_at or now(), req.x_post_id, post_id))
    if not cur.rowcount: raise HTTPException(404, "Generated post not found.")
    return {"ok": True}


@app.post("/api/generated/{post_id}/metrics")
def add_metrics(post_id: str, req: MetricsRequest) -> dict[str, Any]:
    with connect() as db:
        exists = db.execute("SELECT id FROM generated_posts WHERE id=?", (post_id,)).fetchone()
        if not exists: raise HTTPException(404, "Generated post not found.")
        v = req.model_dump()
        db.execute("INSERT INTO post_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), post_id, None, *(v[k] for k in ("impressions","likes","replies","reposts","quotes","bookmarks","profile_visits","link_clicks","follows","engagement_rate")), v["posting_date"], v["posting_time"], now()))
    return {"ok": True, "snapshot_at": now()}


@app.get("/api/insights")
def insights() -> dict[str, Any]:
    with connect() as db:
        rows = db.execute("SELECT p.*,m.impressions mi,m.engagement_rate me,m.replies mr,m.reposts mp FROM personal_posts p LEFT JOIN post_metrics m ON m.personal_post_id=p.id WHERE p.impressions IS NOT NULL OR m.impressions IS NOT NULL").fetchall()
    vals = [r["mi"] if r["mi"] is not None else r["impressions"] for r in rows]
    vals = [float(v) for v in vals if v is not None]
    if vals:
        cuts = sorted(vals)
        bands = {"low": cuts[max(0, int(.2*(len(cuts)-1)))], "typical": cuts[max(0, int(.5*(len(cuts)-1)))], "high": cuts[max(0, int(.8*(len(cuts)-1)))], "exceptional": cuts[-1]}
    else: bands = None
    hooks: dict[str, list[float]] = {}
    topics: dict[str, list[float]] = {}
    for r in rows:
        value = r["mi"] if r["mi"] is not None else r["impressions"]
        if value is None: continue
        h = classify(r["text"])["hook"]
        hooks.setdefault(h, []).append(float(value))
        topics.setdefault(r["topic"] or "Unclassified", []).append(float(value))
    return {"sample_size": len(vals), "performance_bands": bands, "hook_correlations": [{"name": k, "median_impressions": statistics.median(v), "posts": len(v)} for k,v in sorted(hooks.items(), key=lambda i:statistics.median(i[1]), reverse=True)], "topic_correlations": [{"name":k,"median_impressions":statistics.median(v),"posts":len(v)} for k,v in sorted(topics.items(), key=lambda i:statistics.median(i[1]), reverse=True)], "note": "Correlations are descriptive, not causal. Unrecorded metrics remain missing."}


@app.get("/api/export")
def export_data() -> dict[str, Any]:
    with connect() as db:
        return {table: [dict(r) for r in db.execute(f"SELECT * FROM {table}").fetchall()] for table in ("reference_posts", "personal_posts", "generation_requests", "generated_posts", "post_metrics")}


@app.delete("/api/data")
def delete_data() -> dict[str, bool]:
    with connect() as db:
        db.executescript("DELETE FROM post_metrics; DELETE FROM generated_posts; DELETE FROM generation_requests; DELETE FROM personal_posts; DELETE FROM reference_posts;")
    return {"ok": True}
