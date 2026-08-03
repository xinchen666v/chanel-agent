"""Bilibili watch-history recorder — local API server.

Receives watch progress from the Tampermonkey script (api_server.js),
enriches it with B站 API category data, and persists to SQLite.

Endpoints:
  POST /update   — Receive a watch record from the oil-monkey script
  GET  /latest   — Return the most recent record (for Agent hook)
  GET  /progress — Return all unique series/videos with their latest progress
  GET  /stats    — Aggregate watch time by category over a period
  GET  /health   — Health check
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ── Config ──

DB_PATH = Path(__file__).parent / "data" / "bilibili.db"
BILI_API_BASE = "https://api.bilibili.com/x/web-interface/view"
PORT = 3000

# ── DB setup ──

def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watch_records (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bvid        TEXT NOT NULL DEFAULT '',
            title       TEXT NOT NULL DEFAULT '',
            category    TEXT NOT NULL DEFAULT '未知',
            progress    TEXT NOT NULL DEFAULT '0%',
            current_time REAL DEFAULT 0,
            duration    REAL DEFAULT 1,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_watch_records_created
        ON watch_records(created_at DESC)
    """)
    conn.commit()
    conn.close()


# ── Data model ──

@dataclass
class WatchRecord:
    bvid: str
    title: str
    progress: str
    current_time: float
    duration: float
    category: str = "未知"
    timestamp: str = ""


# ── B站 API helper ──

def _fetch_category(bvid: str) -> tuple[str, str]:
    """Call B站 API to get video category and clean title.

    Note: B站 API 的 tname 字段经常为空（API 限制），
    此时 category 会回退为"未知"，不影响核心功能。

    Returns:
        (category, clean_title) — both default to empty string on failure.
    """
    if not bvid:
        return "", ""
    try:
        resp = httpx.get(f"{BILI_API_BASE}?bvid={bvid}", timeout=10)
        info = resp.json()
        if info.get("code") == 0:
            data = info.get("data", {})
            category = data.get("tname", "")
            title = data.get("title", "")
            return category, title
    except Exception:
        pass
    return "", ""


# ── FastAPI app ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    print(f"📦 Bilibili helper server started on http://localhost:{PORT}")
    print(f"   DB: {DB_PATH}")
    yield


app = FastAPI(title="Bilibili Helper", version="0.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoints ──

@app.post("/update")
async def update(request: Request):
    """Receive a watch record from the Tampermonkey script.

    Expected JSON body:
        { bvid, title, progress, currentTime, duration, timestamp }
    """
    body = await request.json()
    bvid = body.get("bvid", "")
    title = body.get("title", "")
    progress = body.get("progress", "0%")
    current_time = body.get("currentTime", 0)
    duration = body.get("duration", 1)
    timestamp = body.get("timestamp", "")

    # Enrich: call B站 API to get category + clean title
    category, api_title = _fetch_category(bvid)
    # 确保 category 不为空（API 可能返回空 tname）
    category = category or "未知"
    if api_title:
        title = api_title  # prefer the API's clean title

    # Fallback: if script didn't send a bvid (bangumi page), try to extract
    # from the User-Agent or other signals… for now just mark as "未知"
    if not bvid:
        category = "未知"

    # Persist
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """INSERT INTO watch_records (bvid, title, category, progress, current_time, duration, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (bvid, title, category, progress, current_time, duration,
             timestamp or datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"📥 [{category}] {title[:30]:30s} → {progress:>4s}  (bvid={bvid[:12]})")
    return {"status": "ok", "category": category}


@app.get("/latest")
async def get_latest(minutes: int = 5):
    """Return the most recent watch record within the last N minutes.

    Used by the Agent's perception hook to inject "what is the user watching"
    context when Bilibili is detected.
    """
    since = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """SELECT * FROM watch_records
               WHERE created_at >= ?
               ORDER BY created_at DESC LIMIT 1""",
            (since,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return {"found": False}
    return {"found": True, "record": dict(row)}


@app.get("/progress")
async def get_progress():
    """Return all unique series/videos with their latest progress.

    For each unique bvid, returns the most recent record.
    Useful for "what's my current追番进度" queries.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT r1.*
               FROM watch_records r1
               INNER JOIN (
                   SELECT bvid, MAX(created_at) AS max_ts
                   FROM watch_records
                   GROUP BY bvid
               ) r2 ON r1.bvid = r2.bvid AND r1.created_at = r2.max_ts
               WHERE r1.bvid != ''
               ORDER BY r1.created_at DESC""",
        ).fetchall()
    finally:
        conn.close()

    return {"series": [dict(r) for r in rows]}


@app.get("/stats")
async def get_stats(days: int = 7):
    """Aggregate watch records by category over the last N days.

    Returns:
        total: total number of records
        by_category: list of {category, count, avg_progress}
    """
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute(
            """SELECT category, COUNT(*) AS cnt,
                      ROUND(AVG(
                          CAST(REPLACE(progress, '%', '') AS REAL)
                      ), 1) AS avg_progress
               FROM watch_records
               WHERE created_at >= ?
               GROUP BY category
               ORDER BY cnt DESC""",
            (since,),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS total FROM watch_records WHERE created_at >= ?",
            (since,),
        ).fetchone()[0]
    finally:
        conn.close()

    return {
        "total": total,
        "by_category": [
            {"category": r[0], "count": r[1], "avg_progress": r[2]}
            for r in rows
        ],
    }


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "db": str(DB_PATH), "records": _count_records()}


def _count_records() -> int:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        return conn.execute("SELECT COUNT(*) FROM watch_records").fetchone()[0]
    finally:
        conn.close()


# ── Entry point ──

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)