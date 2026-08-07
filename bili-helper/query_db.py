"""查询 bili-helper SQLite 数据库中的观看记录

用法:
    python query_db.py              # 列出所有记录
    python query_db.py --latest     # 最近5条
    python query_db.py --stats      # 按分类统计
    python query_db.py --bvid BV1xx # 查指定视频
"""
import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "bilibili.db"


def get_conn():
    if not DB_PATH.exists():
        print(f"❌ 数据库不存在: {DB_PATH}")
        print("   请先启动 server.py 生成数据库")
        raise SystemExit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def show_all():
    """列出所有观看记录"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM watch_records ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    if not rows:
        print("📭 暂无记录")
        return

    print(f"📊 共 {len(rows)} 条记录\n")
    print(f"{'ID':>3}  {'分类':8s}  {'进度':>5s}  {'bvid':14s}  {'时间':20s}  标题")
    print("-" * 90)
    for r in rows:
        title = r["title"][:30] if r["title"] else ""
        print(f"{r['id']:3d}  {r['category']:8s}  {r['progress']:>5s}  {r['bvid']:14s}  {r['created_at']:20s}  {title}")


def show_latest(n=5):
    """显示最近 N 条记录"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM watch_records ORDER BY created_at DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()

    if not rows:
        print("📭 暂无记录")
        return

    print(f"📊 最近 {len(rows)} 条记录\n")
    for r in rows:
        print(f"  [{r['category']}] {r['progress']:>5s}  {r['bvid']}")
        print(f"    标题: {r['title']}")
        print(f"    时间: {r['created_at']}")
        ct = r["current_time"]
        dur = r["duration"]
        if dur and dur > 0:
            mm, ss = divmod(int(ct), 60)
            dm, ds = divmod(int(dur), 60)
            print(f"    播放: {mm}:{ss:02d} / {dm}:{ds:02d}")
        print()


def show_stats():
    """按分类统计"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT category,
                  COUNT(*) AS cnt,
                  ROUND(AVG(CAST(REPLACE(progress, '%', '') AS REAL)), 1) AS avg_progress,
                  MAX(created_at) AS last_watch
           FROM watch_records
           GROUP BY category
           ORDER BY cnt DESC"""
    ).fetchall()
    conn.close()

    if not rows:
        print("📭 暂无记录")
        return

    total = sum(r["cnt"] for r in rows)
    print(f"📊 共 {total} 条记录，{len(rows)} 个分类\n")
    print(f"{'分类':10s}  {'数量':>4s}  {'平均进度':>8s}  最近观看时间")
    print("-" * 60)
    for r in rows:
        print(f"{r['category']:10s}  {r['cnt']:4d}  {r['avg_progress']:>6.1f}%  {r['last_watch']}")


def show_bvid(bvid: str):
    """查指定视频的记录"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM watch_records WHERE bvid = ?", (bvid,)
    ).fetchone()
    conn.close()

    if not row:
        print(f"📭 未找到 bvid={bvid} 的记录")
        return

    print(f"🎬 {bvid}")
    print(f"  标题:   {row['title']}")
    print(f"  分类:   {row['category']}")
    print(f"  进度:   {row['progress']}")
    print(f"  播放:   {int(row['current_time'])}s / {int(row['duration'])}s")
    print(f"  更新:   {row['created_at']}")


def main():
    parser = argparse.ArgumentParser(description="查询 bili-helper 数据库")
    parser.add_argument("--latest", type=int, nargs="?", const=5, default=None,
                        help="显示最近 N 条记录（默认5条）")
    parser.add_argument("--stats", action="store_true",
                        help="按分类统计")
    parser.add_argument("--bvid", type=str, default=None,
                        help="查指定 bvid 的记录")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.latest:
        show_latest(args.latest)
    elif args.bvid:
        show_bvid(args.bvid)
    else:
        show_all()


if __name__ == "__main__":
    main()
