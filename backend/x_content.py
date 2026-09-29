"""Local-first X content studio API. Keeps reference, personal and generated data separate."""
import base64
import csv
import difflib
import io
import json
import math
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from fastapi import APIRouter, HTTPException
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Ensure environment variables are loaded
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

router = APIRouter(prefix="/content", tags=["X content studio"])
DB_PATH = Path(os.getenv("X_CONTENT_DB", str(Path(__file__).resolve().parent.parent / "data" / "x_content.sqlite3")))
_schema_lock = threading.Lock()
_schema_ready = False


SCHEMA = """
CREATE TABLE IF NOT EXISTS reference_posts (
  id INTEGER PRIMARY KEY, text TEXT NOT NULL UNIQUE, author TEXT, topic TEXT,
  source TEXT, collected_at TEXT NOT NULL, hook TEXT, tone TEXT, format TEXT,
  char_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS personal_posts (
  id INTEGER PRIMARY KEY, text TEXT NOT NULL UNIQUE, topic TEXT, posted_at TEXT,
  source TEXT, collected_at TEXT NOT NULL, impressions REAL, likes REAL,
  replies REAL, reposts REAL, bookmarks REAL, engagement_rate REAL,
  hook TEXT, format TEXT, char_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS generation_requests (
  id INTEGER PRIMARY KEY, topic TEXT NOT NULL, count INTEGER NOT NULL,
  created_at TEXT NOT NULL, requirements TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS generated_posts (
  id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL REFERENCES generation_requests(id),
  text TEXT NOT NULL, topic TEXT NOT NULL, format TEXT, tone TEXT,
  created_at TEXT NOT NULL, feedback TEXT, published INTEGER NOT NULL DEFAULT 0,
  published_at TEXT, x_post_id TEXT, impressions REAL, likes REAL, replies REAL,
  reposts REAL, engagement_rate REAL, originality REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS metric_snapshots (
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL, snapshot_at TEXT NOT NULL,
  metrics_json TEXT NOT NULL, FOREIGN KEY(post_id) REFERENCES generated_posts(id)
);
CREATE INDEX IF NOT EXISTS idx_reference_topic ON reference_posts(topic);
CREATE INDEX IF NOT EXISTS idx_personal_topic ON personal_posts(topic);
CREATE INDEX IF NOT EXISTS idx_reference_topic_lower ON reference_posts(lower(topic));
CREATE INDEX IF NOT EXISTS idx_personal_topic_lower ON personal_posts(lower(topic));
CREATE INDEX IF NOT EXISTS idx_generated_created ON generated_posts(created_at);
CREATE INDEX IF NOT EXISTS idx_metrics_post_snapshot ON metric_snapshots(post_id, snapshot_at);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Yield a configured DB connection and reliably commit, rollback, and close it."""
    global _schema_ready
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    try:
        if not _schema_ready:
            with _schema_lock:
                if not _schema_ready:
                    db.execute("PRAGMA journal_mode=WAL")
                    db.executescript(SCHEMA)
                    _schema_ready = True
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def analyze(text: str) -> dict[str, str | int]:
    words = re.findall(r"\b[\w'-]+\b", text)
    first = text.split("\n", 1)[0].strip()
    if "?" in first:
        hook = "question"
    elif re.search(r"\d", first):
        hook = "statistic"
    elif re.search(r"\b(but|wrong|myth|actually|stop|never|why|don't)\b", first, re.I):
        hook = "contrarian"
    else:
        hook = "bold statement"

    is_thread = bool(re.search(r"\b1/\b|\b1\.\s|🧵", text))
    is_list = bool(re.search(r"(^|\n)\s*[-•\d]\.?\s+", text))
    post_format = "thread" if is_thread else "list" if is_list else "single post"
    return {"hook": hook, "format": post_format, "char_count": len(text), "word_count": len(words)}


def normalized_row(row: dict) -> dict[str, object]:
    """Normalize CSV/Excel/JSON field names before matching supported columns."""
    normalized = {}
    for key, value in row.items():
        field = re.sub(r"\s+", "_", str(key).replace("\ufeff", "").strip().lower())
        normalized[field] = value
    for alias in ("post_text", "tweet_text", "full_text"):
        if "text" not in normalized and alias in normalized:
            normalized["text"] = normalized[alias]
    if "posted_at" not in normalized and "created_at" in normalized:
        normalized["posted_at"] = normalized["created_at"]
    return normalized


def numeric_metric(row: dict[str, object], name: str) -> float | None:
    value = row.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


class ImportPayload(BaseModel):
    category: Literal["reference", "personal"]
    filename: str = "upload"
    content: str = Field(max_length=10_000_000)
    encoding: Literal["text", "base64"] = "text"


class GeneratePayload(BaseModel):
    topic: str = Field(min_length=1, max_length=180)
    count: int = Field(default=5, ge=1, le=20)
    tone: str | None = None
    audience: str | None = None
    format: str | None = None
    length: str | None = None
    instructions: str | None = Field(default=None, max_length=1000)


class FeedbackPayload(BaseModel):
    feedback: Literal["good", "bad", "rewrite", "save", "published", "high-performing", "low-performing"]
    x_post_id: str | None = None


class MetricsPayload(BaseModel):
    impressions: float | None = Field(default=None, ge=0)
    likes: float | None = Field(default=None, ge=0)
    replies: float | None = Field(default=None, ge=0)
    reposts: float | None = Field(default=None, ge=0)
    engagement_rate: float | None = Field(default=None, ge=0)
    snapshot_at: str | None = None


@router.get("/overview")
def overview():
    with connect() as db:
        personal = db.execute(
            "SELECT COUNT(*) n, AVG(impressions) impressions, AVG(engagement_rate) er, "
            "SUM(likes) likes, SUM(replies) replies, SUM(reposts) reposts, SUM(bookmarks) bookmarks "
            "FROM personal_posts"
        ).fetchone()
        refs = db.execute("SELECT COUNT(*) FROM reference_posts").fetchone()[0]
        generated = db.execute("SELECT COUNT(*) FROM generated_posts").fetchone()[0]
        return {
            "reference_count": refs,
            "personal_count": personal["n"],
            "generated_count": generated,
            "average_impressions": personal["impressions"],
            "average_engagement_rate": personal["er"],
            "likes": personal["likes"] or 0,
            "replies": personal["replies"] or 0,
            "reposts": personal["reposts"] or 0,
            "bookmarks": personal["bookmarks"] or 0,
        }


@router.post("/import")
def import_posts(payload: ImportPayload):
    suffix = Path(payload.filename).suffix.lower()
    if suffix not in {".csv", ".json", ".jsonl", ".txt", ".xlsx", ".xls"}:
        raise HTTPException(415, "Supported formats: CSV, JSON, JSONL, TXT, XLS and XLSX.")
    try:
        if suffix in {".xlsx", ".xls"}:
            if payload.encoding != "base64":
                raise HTTPException(400, "Excel uploads must be base64 encoded.")
            import pandas as pd

            binary = base64.b64decode(payload.content, validate=True)
            frame = pd.read_excel(io.BytesIO(binary)).astype(object)
            rows = frame.where(pd.notna(frame), None).to_dict(orient="records")
        elif payload.encoding == "base64":
            raise HTTPException(400, "Base64 encoding is only accepted for Excel files.")
        elif suffix == ".csv":
            rows = list(csv.DictReader(io.StringIO(payload.content)))
        elif suffix == ".jsonl":
            rows = [json.loads(line) for line in payload.content.splitlines() if line.strip()]
        elif suffix == ".json":
            parsed = json.loads(payload.content)
            if isinstance(parsed, list):
                rows = parsed
            elif isinstance(parsed, dict):
                rows = parsed.get("posts", [parsed])
                if not isinstance(rows, list):
                    raise HTTPException(400, "The JSON 'posts' field must contain a list.")
            else:
                raise HTTPException(400, "JSON upload must be an object or a list of objects.")
        else:
            rows = [{"text": line} for line in payload.content.splitlines() if line.strip()]
    except ImportError as exc:
        raise HTTPException(503, f"Excel import dependency is missing; install requirements.txt: {exc}")
    except (ValueError, TypeError, OSError) as exc:
        raise HTTPException(400, f"Could not parse upload: {exc}")
    if not isinstance(rows, list):
        raise HTTPException(400, "Upload must contain a list of post records.")
    if len(rows) > 100_000:
        raise HTTPException(413, "Upload contains too many records (maximum 100,000).")
    table = "reference_posts" if payload.category == "reference" else "personal_posts"
    inserted = skipped = 0
    collected = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        for raw_row in rows:
            if not isinstance(raw_row, dict):
                skipped += 1
                continue
            row = normalized_row(raw_row)
            text = str(row.get("text") or row.get("post") or row.get("content") or "").strip()
            if not text or len(text) > 10000 or len(text) < 3:
                skipped += 1
                continue
            a = analyze(text)
            if table == "reference_posts":
                cur = db.execute(
                    "INSERT OR IGNORE INTO reference_posts(text,author,topic,source,collected_at,hook,tone,format,char_count) VALUES(?,?,?,?,?,?,?,?,?)",
                    (text, row.get("author"), row.get("topic"), str(row.get("source") or payload.filename), collected, a["hook"], row.get("tone"), row.get("format") or a["format"], a["char_count"]),
                )
            else:
                cur = db.execute(
                    "INSERT OR IGNORE INTO personal_posts(text,topic,posted_at,source,collected_at,impressions,likes,replies,reposts,bookmarks,engagement_rate,hook,format,char_count) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (text, row.get("topic"), row.get("timestamp") or row.get("posted_at"), str(row.get("source") or payload.filename), collected, numeric_metric(row, "impressions"), numeric_metric(row, "likes"), numeric_metric(row, "replies"), numeric_metric(row, "reposts"), numeric_metric(row, "bookmarks"), numeric_metric(row, "engagement_rate"), a["hook"], row.get("format") or a["format"], a["char_count"]),
                )
            inserted += cur.rowcount
            skipped += 1 - cur.rowcount
    return {"inserted": inserted, "skipped": skipped, "category": payload.category}


def extract_posts_from_content(content: str) -> list[dict]:
    if not content or not isinstance(content, str):
        return []
    cleaned = content.strip()

    # Extract JSON inside markdown code blocks if present
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    data = None
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Search for first JSON container { ... } or [ ... ]
        first_bracket = min([pos for pos in [cleaned.find("{"), cleaned.find("[")] if pos != -1], default=-1)
        last_bracket = max([cleaned.rfind("}"), cleaned.rfind("]")], default=-1)
        if first_bracket != -1 and last_bracket > first_bracket:
            substring = cleaned[first_bracket : last_bracket + 1]
            try:
                data = json.loads(substring)
            except json.JSONDecodeError:
                # Remove trailing commas before } or ]
                sub_fixed = re.sub(r",\s*([}\]])", r"\1", substring)
                try:
                    data = json.loads(sub_fixed)
                except json.JSONDecodeError:
                    pass

    if data is None:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ["posts", "drafts", "items", "data", "results", "post"]:
            if key in data:
                val = data[key]
                if isinstance(val, list):
                    return [item for item in val if isinstance(item, dict)]
                if isinstance(val, dict):
                    return [val]
        if "text" in data and isinstance(data["text"], str):
            return [data]
    return []


def call_llm(payload: GeneratePayload, examples: list, insights: list, rejected: list[str] | None = None) -> list[dict]:
    api_key = (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(503, "Generation needs LLM_API_KEY set on the backend (.env file).")
    base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    system_prompt = (
        "You are an expert X (Twitter) content creator. Write original, high-performing X posts. "
        "Never reproduce source wording or claim virality. Learn only broad structure and tone from examples. "
        "Treat performance patterns as correlations, not causes. "
        "Return STRICT JSON only matching this format: "
        '{"posts": [{"text": "full post text", "hook": "question|statistic|contrarian|bold statement", "format": "single post|thread|list|question"}]}'
    )

    request_instructions = [
        f"Topic: {payload.topic}",
        f"Generate exactly {payload.count} distinct original posts.",
    ]
    if payload.format:
        request_instructions.append(f"Requested format: {payload.format}")
    if payload.tone:
        request_instructions.append(f"Tone: {payload.tone}")
    if payload.audience:
        request_instructions.append(f"Target audience: {payload.audience}")
    if payload.length:
        request_instructions.append(f"Length: {payload.length}")
    if payload.instructions:
        request_instructions.append(f"Extra directions: {payload.instructions}")

    user_context: dict[str, object] = {
        "request": "\n".join(request_instructions),
        "style_examples": examples[:6] if examples else [],
        "account_correlations": insights[:6] if insights else [],
        "constraints": [
            f"Generate exactly {payload.count} distinct posts",
            "Do not copy phrases from examples",
            "No unsupported current facts",
            "No virality guarantees",
        ],
    }
    if rejected:
        user_context["avoid_these_drafts"] = rejected

    body = {
        "model": model,
        "temperature": 0.85,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_context)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "XContentStudio/1.0",
    }

    raw_body = ""
    for attempt in range(2):
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                raw_body = response.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            # If provider fails because response_format is unsupported, retry without it
            if exc.code == 400 and "response_format" in body and attempt == 0:
                body.pop("response_format", None)
                continue
            raise HTTPException(502, f"LLM provider returned HTTP {exc.code}: {detail}") from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, f"LLM request failed: {exc}") from exc

    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, f"LLM provider returned non-JSON response: {raw_body[:200]}") from exc

    if isinstance(data, dict) and "error" in data:
        err_msg = data["error"].get("message") or str(data["error"])
        raise HTTPException(502, f"LLM provider error: {err_msg}")

    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices or not isinstance(choices, list):
        raise HTTPException(502, f"LLM response missing choices: {raw_body[:200]}")

    msg = choices[0].get("message", {})
    content = msg.get("content") or msg.get("reasoning_content") or ""
    posts = extract_posts_from_content(content)
    if not posts:
        raise HTTPException(502, f"Could not parse valid posts from LLM response: {content[:300]}")
    return posts


@router.post("/generate")
def generate(payload: GeneratePayload):
    topic_query = payload.topic.casefold()

    # Step 1: Read refs and personal posts in a brief connection
    with connect() as db:
        refs = [
            dict(row)
            for row in db.execute(
                "SELECT text,hook,tone,format,topic FROM reference_posts "
                "WHERE topic IS NULL OR lower(topic) = ? "
                "ORDER BY CASE WHEN lower(COALESCE(topic, '')) = ? THEN 0 ELSE 1 END, id DESC LIMIT 6",
                (topic_query, topic_query),
            )
        ]
        personal = [
            dict(row)
            for row in db.execute(
                "SELECT text,topic,hook,format,impressions,engagement_rate FROM personal_posts "
                "WHERE topic IS NULL OR lower(topic) = ? "
                "ORDER BY CASE WHEN lower(COALESCE(topic, '')) = ? THEN 0 ELSE 1 END, id DESC LIMIT 6",
                (topic_query, topic_query),
            )
        ]
        insights = [
            dict(row)
            for row in db.execute(
                "SELECT hook, AVG(engagement_rate) AS mean_engagement_rate, "
                "COUNT(*) AS sample_size FROM personal_posts "
                "WHERE (topic IS NULL OR lower(topic) = ?) AND engagement_rate IS NOT NULL "
                "GROUP BY hook ORDER BY mean_engagement_rate DESC",
                (topic_query,),
            )
        ]

    sources = [row["text"] for row in refs] + [row["text"] for row in personal]
    output = []
    rejected = []
    seen_texts = set()

    # Step 2: Call LLM outside of the database connection
    for attempt in range(2):
        result = call_llm(payload, refs, insights, rejected=rejected if attempt > 0 else None)
        if not isinstance(result, list):
            continue

        for item in result:
            if len(output) >= payload.count:
                break
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text or text.casefold() in seen_texts:
                continue

            # Compare similarity against source posts and already accepted outputs
            comparison = sources + list(seen_texts)
            similarity = max(
                (difflib.SequenceMatcher(None, text.casefold(), s.casefold()).ratio() for s in comparison),
                default=0.0,
            )
            # Threshold: in attempt 0, use strict 0.72; if retrying, allow up to 0.82 if needed
            max_sim = 0.72 if attempt == 0 else 0.82
            if similarity >= max_sim:
                rejected.append(text)
                continue

            seen_texts.add(text.casefold())
            analysis = analyze(text)
            originality = round(1.0 - similarity, 3)
            post_format = payload.format or item.get("format") or analysis["format"]
            hook = item.get("hook") or analysis["hook"]

            output.append({
                "text": text,
                "hook": hook,
                "format": post_format,
                "char_count": analysis["char_count"],
                "originality_score": originality,
                "topic_track_record": "limited data" if not personal else "based on account history",
                "structure_match": "indicator only",
            })

        if len(output) >= payload.count:
            break

    # If all drafts were rejected due to similarity, take best available from rejected
    if not output and rejected:
        for text in rejected[:payload.count]:
            if text.casefold() in seen_texts:
                continue
            seen_texts.add(text.casefold())
            analysis = analyze(text)
            comparison = sources + list(seen_texts)
            sim = max((difflib.SequenceMatcher(None, text.casefold(), s.casefold()).ratio() for s in comparison), default=0.0)
            originality = round(1.0 - sim, 3)
            post_format = payload.format or analysis["format"]
            output.append({
                "text": text,
                "hook": analysis["hook"],
                "format": post_format,
                "char_count": analysis["char_count"],
                "originality_score": originality,
                "topic_track_record": "limited data" if not personal else "based on account history",
                "structure_match": "indicator only",
            })

    # Step 3: Fast write to SQLite
    now_iso = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        cur = db.execute(
            "INSERT INTO generation_requests(topic,count,created_at,requirements) VALUES(?,?,?,?)",
            (payload.topic, payload.count, now_iso, payload.model_dump_json()),
        )
        request_id = cur.lastrowid
        for post in output:
            c = db.execute(
                "INSERT INTO generated_posts(request_id,text,topic,format,tone,created_at,originality) "
                "VALUES(?,?,?,?,?,?,?)",
                (request_id, post["text"], payload.topic, post["format"], payload.tone, now_iso, post["originality_score"]),
            )
            post["id"] = c.lastrowid

    return {
        "request_id": request_id,
        "posts": output,
        "note": "Indicators summarize available data; they do not predict or guarantee outcomes.",
    }


@router.get("/generated")
def generated():
    with connect() as db:
        posts = [dict(row) for row in db.execute("SELECT * FROM generated_posts ORDER BY id DESC LIMIT 100")]
        for post in posts:
            analysis = analyze(post["text"])
            post["hook"] = analysis["hook"]
            post["char_count"] = analysis["char_count"]
        return posts


@router.post("/generated/{post_id}/feedback")
def feedback(post_id: int, payload: FeedbackPayload):
    with connect() as db:
        now = datetime.now(timezone.utc).isoformat()
        cursor = db.execute(
            "UPDATE generated_posts SET feedback=?, "
            "published=CASE WHEN ?='published' THEN 1 ELSE published END, "
            "published_at=CASE WHEN ?='published' THEN ? ELSE published_at END, "
            "x_post_id=COALESCE(?,x_post_id) WHERE id=?",
            (payload.feedback, payload.feedback, payload.feedback, now, payload.x_post_id, post_id),
        )
        if not cursor.rowcount:
            raise HTTPException(404, "Generated post not found")
    return {"ok": True}


@router.post("/generated/{post_id}/metrics")
def metrics(post_id: int, payload: MetricsPayload):
    with connect() as db:
        row = db.execute("SELECT id FROM generated_posts WHERE id=?", (post_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Generated post not found")
        db.execute(
            "UPDATE generated_posts SET impressions=COALESCE(?,impressions), likes=COALESCE(?,likes), "
            "replies=COALESCE(?,replies), reposts=COALESCE(?,reposts), "
            "engagement_rate=COALESCE(?,engagement_rate) WHERE id=?",
            (payload.impressions, payload.likes, payload.replies, payload.reposts, payload.engagement_rate, post_id),
        )
        db.execute(
            "INSERT INTO metric_snapshots(post_id,snapshot_at,metrics_json) VALUES(?,?,?)",
            (post_id, payload.snapshot_at or datetime.now(timezone.utc).isoformat(), payload.model_dump_json(exclude_none=True)),
        )
    return {"ok": True}
