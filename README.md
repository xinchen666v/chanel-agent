# Chanel Agent



<p align="center">
  <strong>从「你问我答」到「我观我动」</strong><br>
  一个会主动观察你、理解你、在恰当时机开口的桌面级 AI Agent
</p>

<p align="center">
  <a href="#-演示回放"><img src="https://img.shields.io/badge/演示回放-HTML_单文件-blue?style=flat-square" alt="demo"></a>
  <a href="#-快速开始"><img src="https://img.shields.io/badge/启动-一键脚本-green?style=flat-square" alt="setup"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-orange?style=flat-square" alt="license"></a>
  <img src="https://img.shields.io/badge/platform-Windows-blue?style=flat-square" alt="platform">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square" alt="python">
</p>

---

## 这是什么？

大多数 AI 助手都是「被动响应」的——你问，它答。你不问，它就没有行动。

**Chanel Agent 不一样。** 它像一个坐在你身旁的贴身秘书，每隔一段时间自动观察你的桌面状态——你在用什么应用？窗口标题是什么？鼠标键盘空闲了多久？是不是在全屏？——然后基于这些信号，自主决定**该不该开口，什么时候开口，说些什么**。

它会记得你上次聊了什么，会追踪你的工作习惯，会在深夜看到你还在编码时轻轻问候一句，也会在你专注工作时懂事地保持安静。

> "好的秘书懂分寸——该说话时说，不该说时安静。"

---

## 核心特性

### 🔍 桌面感知
通过 Windows API 实时捕获你的桌面上下文：
- **当前活跃应用与窗口标题**（IDE、浏览器、终端……）
- **用户空闲时长**（刚离开？还是正专注？）
- **全屏状态检测**（全屏时不打扰，除非有重要的事）
- **时间与星期**（凌晨 2 点写代码和上午 10 点写代码，意义不同）

### 🧠 自主决策引擎
每一轮唤醒，Agent 都会经历完整的推理过程：

```
信号分析 → 态势判断 → 历史参考 → 行动决策
```

- **信号分析**：用户在用 Trae 编码，已空闲 30 秒
- **态势判断**：可能卡壳了，正在思考
- **历史参考**：上次我主动问要不要帮忙，用户说"不需要"
- **行动决策**：这次先不打扰，3 分钟后回看

所有推理过程记录在 SQLite 中，形成可追溯的**思维链条**。

### 💬 主动冒泡
当 Agent 判断该开口时，会通过 Windows 原生通知弹出一条消息。每条消息可以附带快捷回复按钮，用户点击即可响应，无需手动输入。

### 🧩 工具系统
Agent 不只是聊天——它可以使用工具：
| 工具 | 用途 |
|------|------|
| `bash` | 执行系统命令 |
| `read_file` / `write_file` / `edit_file` | 文件操作 |
| `query_memory` | 查询记忆库（时间线、搜索、统计、画像） |
| `update_profile` | 更新用户画像 |
| `schedule_next_wake` | 设定下次唤醒时间 |
| `send_message` | 主动发送消息 |

### 💾 持久化记忆
- **SQLite 数据库**：存储观察记录、推理过程、行动决策、会话信息
- **用户画像**：自动追踪 + LLM 写入，持续了解你的技术栈、项目、偏好
- **沉默计数**：连续多次不说话会触发提醒，打破"只观察不开口"的循环

### 🖥️ 双运行模式
- **TUI 模式**（默认）：三面板 Textual 界面——聊天 / 状态 / 工具日志
- **终端模式**（`--terminal`）：纯文本输出，便于日志捕获和分享

---

## 演示回放

克隆仓库后，直接用浏览器打开 `demo_replay.html` 即可观看一次完整的运行回放。

> 该回放基于 Chanel Agent 在真实运行中产生的日志数据生成，所有步骤、时间戳与决策推理均来自实际运行记录，并非手工编排的演示脚本。

---

## 快速开始

### 环境要求
- Python 3.10+
- Windows 操作系统

### 一键启动

```bash
# Windows
setup.bat

# macOS / Linux
bash setup.sh
```

脚本会自动完成：创建虚拟环境 → 安装依赖 → 启动 Agent。

### 手动安装

```bash
# 1. 克隆仓库
git clone https://github.com/your-username/chanel-agent.git
cd chanel-agent

# 2. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置
cp .env.example .env
# 编辑 .env，填入你的 API Key

# 5. 启动
python -m src.main              # TUI 模式
python -m src.main --terminal   # 终端模式
```

### 配置说明

在项目根目录创建 `.env` 文件：

```env
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
MODEL_ID=deepseek-chat
CHANEL_DB_PATH=data/chanel.db
```

---

## 项目架构

```
chanel-agent/
├── src/
│   ├── agent/          # Agent 核心循环、系统提示词
│   │   ├── core.py         # LLM 对话循环 + 工具调用
│   │   ├── event_loop.py   # 事件驱动主循环
│   │   └── prompt.py       # 系统提示词构建
│   ├── perception/     # 桌面感知层
│   │   ├── base.py         # 抽象接口
│   │   ├── snapshot.py     # 感知快照数据结构
│   │   └── windows.py      # Windows API 实现
│   ├── memory/         # 记忆与持久化
│   │   ├── store.py        # SQLite 存储
│   │   ├── chain.py        # 思维链条管理
│   │   └── profile.py      # 用户画像
│   ├── scheduler/      # 定时调度
│   │   └── timer.py        # 可取消的 Timer 实现
│   ├── tools/          # 工具注册与分发
│   │   ├── registry.py     # 工具注册表
│   │   ├── file_ops.py     # 文件读写
│   │   ├── shell.py        # Shell 命令
│   │   ├── wake.py         # 唤醒调度
│   │   ├── message.py      # 消息发送
│   │   └── memory_query.py # 记忆查询
│   ├── ui/             # 用户界面
│   │   ├── tui_app.py      # Textual 三面板 TUI
│   │   ├── terminal.py     # 终端输出
│   │   ├── notification.py # Windows 通知
│   │   └── callback_server.py # 快捷回复 HTTP 回调
│   ├── config.py       # 配置管理
│   └── main.py         # 入口
├── svg/               # 图标资源
├── demo_replay.html   # 演示回放页面
├── setup.bat / setup.sh  # 一键启动脚本
├── requirements.txt
└── README.md
```

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| LLM | Anthropic API（兼容 DeepSeek） |
| 桌面感知 | Windows API（ctypes） |
| 数据存储 | SQLite |
| TUI 界面 | [Textual](https://github.com/Textualize/textual) |
| 通知 | tkinter |

---

## 设计理念

Chanel 不追求"全能"，而是追求**"懂分寸"**。

- **不打扰是一种能力**：比起"每 5 分钟说一句话"，更难的决策是"知道什么时候不该说话"
- **记忆是温度的基础**：记住用户说过的事、做过的事，才能提供有连续性的陪伴
- **推理需要可追溯**：每个决策都有记录，每一轮都有推理过程，不是黑盒

---

## License

MIT © 2025