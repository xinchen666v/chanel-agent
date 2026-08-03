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

# B站 tid → 分类名称映射（当 tname 为空时 fallback 使用）
# 来源: https://lxb007981.github.io/bilibili-API-collect/video/video_zone.html
TID_CATEGORY_MAP = {
    # 动画
    1: "动画", 24: "MAD·AMV", 25: "MMD·3D", 47: "短片·手书·配音",
    210: "手办·模玩", 86: "特摄", 27: "动画综合", 253: "动画综合",
    # 番剧
    13: "番剧", 33: "连载动画", 32: "完结动画", 51: "资讯", 152: "官方延伸",
    # 国创
    167: "国创", 153: "国产动画", 168: "国产原创相关",
    169: "布袋戏", 195: "动态漫·广播剧", 170: "国创资讯",
    # 音乐
    3: "音乐", 28: "原创音乐", 31: "翻唱", 30: "VOCALOID·UTAU",
    194: "电音", 59: "演奏", 193: "MV", 29: "音乐现场", 130: "音乐综合",
    # 舞蹈
    129: "舞蹈", 20: "宅舞", 198: "街舞", 199: "明星舞蹈",
    200: "中国舞", 154: "舞蹈综合", 156: "舞蹈教程",
    # 游戏
    4: "游戏", 17: "单机游戏", 171: "电子竞技", 172: "手机游戏",
    65: "网络游戏", 173: "桌游棋牌", 121: "GMV", 136: "音游", 19: "Mugen",
    # 知识
    36: "知识", 201: "科学科普", 124: "社科·法律·心理", 228: "人文历史",
    207: "财经商业", 208: "校园学习", 209: "职业职场", 229: "设计·创意",
    122: "野生技术协会",
    # 科技
    188: "科技", 95: "数码", 230: "软件应用", 231: "计算机技术",
    232: "工业·工程·机械", 233: "极客DIY",
    # 运动
    234: "运动", 235: "篮球·足球", 164: "健身", 236: "竞技体育",
    237: "运动文化", 238: "运动综合",
    # 汽车
    223: "汽车", 176: "汽车生活", 224: "汽车文化", 225: "汽车极客",
    226: "智能出行", 227: "购车攻略",
    # 生活
    160: "生活", 138: "搞笑", 239: "家居房产", 161: "手工",
    162: "绘画", 21: "日常",
    # 美食
    211: "美食", 76: "美食制作", 212: "美食侦探", 213: "美食测评",
    214: "田园美食", 215: "美食记录",
    # 动物圈
    217: "动物圈", 218: "喵星人", 219: "汪星人", 220: "大熊猫",
    221: "野生动物", 222: "爬宠", 75: "动物综合",
    # 鬼畜
    155: "鬼畜", 22: "鬼畜调教", 26: "音MAD", 126: "人力VOCALOID",
    216: "鬼畜剧场", 127: "教程演示",
    # 时尚
    157: "时尚", 158: "美妆", 159: "服饰", 192: "健身", 175: "T台", 196: "风尚",
    # 影视
    181: "影视", 182: "影视杂谈", 183: "影视剪辑", 85: "小剧场", 184: "预告·花絮",
    # 综艺·娱乐
    174: "综艺", 71: "娱乐", 241: "娱乐杂谈", 242: "欢乐剧场", 243: "相声曲艺",
    # 资讯
    119: "资讯", 203: "热点", 204: "环球", 205: "社会", 206: "政务",
    # 纪录片·电影·电视剧
    247: "纪录片", 248: "电影", 249: "电视剧",
    # tid_v2（新版分类体系）
    2026: "人文社科", 2027: "科学科普", 2028: "社会观察",
    2029: "职业职场", 2030: "财经商业", 2031: "设计创意",
    2032: "计算机技术", 2033: "演讲辩论", 2034: "校园学习",
    2035: "汽车出行", 2036: "购车攻略", 2037: "赛车赛事",
    2038: "改装玩车", 2039: "摩托车", 2040: "新能源车",
    2041: "极速体验", 2043: "动画综合",
}


def _tid_to_category(tid: int, tid_v2: int = 0) -> str:
    """Convert B站 numeric tid to category name string."""
    if tid_v2 and tid_v2 in TID_CATEGORY_MAP:
        return TID_CATEGORY_MAP[tid_v2]
    if tid in TID_CATEGORY_MAP:
        return TID_CATEGORY_MAP[tid]
    return ""


def _fetch_category(bvid: str) -> tuple[str, str]:
    """Call B站 API to get video category and clean title.

    Returns:
        (category, clean_title) — both default to empty string on failure.
    """
    if not bvid:
        return "", ""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
        }
        resp = httpx.get(f"{BILI_API_BASE}?bvid={bvid}", headers=headers, timeout=10)
        info = resp.json()
        if info.get("code") == 0:
            data = info.get("data", {})
            tid = data.get("tid", 0)
            tid_v2 = data.get("tid_v2", 0)
            # Try tname first, fallback to tid mapping
            category = (data.get("tname", "") or
                        _tid_to_category(tid, tid_v2))
            title = data.get("title", "")
            print(f"  [API] bvid={bvid} tid={tid} tid_v2={tid_v2} tname='{data.get('tname','')}' category='{category}'")
            return category, title
        else:
            print(f"  [API] bvid={bvid} code={info.get('code')} msg={info.get('message','')}")
    except Exception as e:
        print(f"  [API] bvid={bvid} error: {e}")
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

    # Normalize timestamp: use local time (ignore JS's UTC timestamp)
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    # Persist
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """INSERT INTO watch_records (bvid, title, category, progress, current_time, duration, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (bvid, title, category, progress, current_time, duration, ts),
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
    since = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")
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