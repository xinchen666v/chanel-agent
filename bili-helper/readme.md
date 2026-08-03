# Bilibili Helper — B站观看记录本地服务

为 Chanel Agent 提供 B 站观看行为追踪能力。包含三个组件：

```
┌─────────────────┐      ┌─────────────────┐      ┌──────────────────┐
│  油猴脚本        │      │  本地 API 服务    │      │  Chanel Agent    │
│  api_server.js  │ ──→  │  server.py       │ ──→  │  (后续接入)       │
│  (浏览器中运行)   │      │  FastAPI + SQLite │      │  hook + tool     │
└─────────────────┘      └─────────────────┘      └──────────────────┘
```

## 组件

### 1. 油猴脚本 (`api_server.js`)

在 B 站视频/番剧页面运行时，按事件驱动上报进度：

| 事件 | 时机 | 作用 |
|------|------|------|
| `play` | 用户点击播放 / 自动播放 | **核心**：让 DB 立即知道正在看什么 |
| `timeupdate` (60s) | 播放中每分钟 | 长时间观看不丢失进度 |
| `pause` | 用户暂停 | 记录看到哪了 |
| `ended` | 播放完毕 | 标记已看完 |
| `pagehide` | 关闭/刷新页面 | 关闭前兜底上报 |

**安装方式**：将 `api_server.js` 添加到 Tampermonkey / Violentmonkey 等油猴管理器。

### 2. 本地 API 服务 (`server.py`)

FastAPI 服务，接收油猴脚本上报的数据，调用 B 站 API 获取视频分类，存入 SQLite。

```
POST /update   ← 油猴脚本上报观看记录
GET  /latest   → 返回最近一条记录（Agent hook 用）
GET  /progress → 所有追番的最新进度
GET  /stats    → 按分类聚合统计（周报/月报）
GET  /health   → 健康检查
```

### 3. 数据流

```
油猴脚本上报:
  { bvid, title, progress, currentTime, duration, timestamp }

server.py 处理:
  1. 调 B站 API → 获取 tname (分类, 如"动画"/"科技"/"生活") + 干净标题
  2. 存入 SQLite: watch_records { bvid, title, category, progress, ... }

Agent 后续接入:
  - 感知到 Bilibili 时 → hook 调 /latest → 注入 "[Bilibili] 正在看: 鬼灭之刃 (动画) 65%"
  - 需要分析时 → 调 /stats → "本周科技 8h vs 动画 2h"
```

## 快速开始

```bash
# 1. 安装依赖
cd bili-helper
pip install -r requirements.txt

# 2. 启动服务（默认端口 3000）
python server.py

# 3. 浏览器中安装油猴脚本 api_server.js
# 4. 打开 B 站任意视频，脚本会自动上报
```

## 数据库

自动创建在 `data/bilibili.db`，表结构：

```sql
CREATE TABLE watch_records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    bvid         TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    category     TEXT NOT NULL DEFAULT '未知',  -- B站 API 返回的 tname
    progress     TEXT NOT NULL DEFAULT '0%',
    current_time REAL DEFAULT 0,
    duration     REAL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
```

## 后续计划

1. Chanel Agent 感知层 hook：检测到 Bilibili 时自动注入观看上下文
2. `query_bilibili` 工具：让 Agent 能主动查询统计数据
3. 下班追番提醒、时间分配分析、兴趣演变追踪