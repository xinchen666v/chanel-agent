"""Event-driven main loop - orchestrates user input and autonomous wake events."""

import platform
import queue
import threading
from pathlib import Path

from anthropic import Anthropic

from config import Config
from perception.base import AbstractPerception
from scheduler.timer import Scheduler
from tools.registry import ToolRegistry, Tool
from tools.file_ops import FileOps
from tools.shell import Shell
from tools.wake import WakeTool
from tools.message import MessageTool
from tools.memory_query import MemoryQueryTool
from tools.memory_manage import MemoryManageTool
from tools.permissions import PermissionGate
from tools.reminder import ReminderTool
from tools.feedback import FeedbackTool
from tools.todo import TodoTool
from agent.hooks import HookRegistry
from memory.store import MemoryStore
from memory.chain import ThoughtChain
from memory.profile import UserProfile
from memory.bank import MemoryBank
from memory.feedback import FeedbackBank
from agent.core import AgentCore
from agent.prompt import PromptBuilder
from ui.terminal import Terminal
from ui.notification import Notifier
from ui.callback_server import ReplyHTTPServer


# Port for the local HTTP server that receives notification button clicks
CALLBACK_PORT = 18739


class EventLoop:
    """Main event loop that integrates perception, agent, scheduler, and memory.

    Events: user input, wake timer, shutdown.
    All events flow through a single queue to the agent core.
    """

    def __init__(self, config: Config, tui_mode: bool = False):
        self._config = config
        self._tui_mode = tui_mode
        self._event_queue: queue.Queue = queue.Queue()
        self._running = False

        # Initialize subsystems
        self._perception = self._create_perception()
        self._scheduler = Scheduler(self._event_queue, config.min_wake_interval)
        self._notifier = Notifier(event_queue=self._event_queue, callback_port=CALLBACK_PORT)
        self._callback_server = ReplyHTTPServer(CALLBACK_PORT, self._event_queue)
        self._memory_store = MemoryStore(config.db_path)

        # File-based memory bank (s09_memory inspired)
        self._memory_bank = MemoryBank(config.db_path.parent / "memory")
        self._migrate_old_profile(config.db_path.parent)
        self._profile = UserProfile(self._memory_bank)
        self._memory = ThoughtChain(self._memory_store, self._profile)

        # Task-level feedback bank
        self._feedback_bank = FeedbackBank(config.db_path.parent / "feedback")

        # Initialize tools
        self._todo_tool = TodoTool()
        self._reminder_tool = ReminderTool(self._event_queue, self._notifier)
        self._tools = self._build_tools()

        # Hook registry: agent behavior extensions without modifying the loop.
        self._hook_registry = self._build_hook_registry(config.workdir)

        # Initialize Anthropic client
        self._client = Anthropic(
            base_url=config.api_base_url,
            api_key=config.api_key,
        )

        # Build system prompt at runtime from independent sections.
        # Context reflects real state: enabled tools, workspace, memories, profile.
        system_context = {
            "workdir": str(config.workdir),
            "os": platform.system(),
            "shell": "PowerShell" if platform.system() == "Windows" else "Bash",
            "enabled_tools": self._tools.get_tool_names(),
            "memory_index": self._memory_bank.list_index(),
            "profile_context": self._memory.get_profile_context(),
        }
        self._system_prompt = PromptBuilder.get_system_prompt(system_context)

        # Initialize agent core
        self._agent = AgentCore(
            client=self._client,
            model=config.model,
            system_prompt=self._system_prompt,
            tools=self._tools,
            memory=self._memory,
            hook_registry=self._hook_registry,
        )

    def _create_perception(self) -> AbstractPerception:
        """Create platform-appropriate perception implementation."""
        import platform

        system = platform.system()
        if system == "Windows":
            from perception.windows import WindowsPerception

            return WindowsPerception()
        elif system == "Darwin":
            from perception.macos import MacOSPerception

            return MacOSPerception()
        else:
            raise RuntimeError(f"Unsupported platform: {system}")

    def _migrate_old_profile(self, data_dir: Path):
        """Migrate old data/user_profile.md to the memory bank if needed."""
        old_path = data_dir / "user_profile.md"
        new_path = data_dir / "memory" / "user_profile.md"
        if old_path.exists() and not new_path.exists():
            try:
                self._memory_bank.create(
                    name="user_profile",
                    description="Aggregated user behavior profile and semantic notes (migrated)",
                    content=old_path.read_text(encoding="utf-8"),
                    type="user",
                    tags=["auto-tracked", "profile", "migrated"],
                )
                print(f"[Migration] Moved old profile to {new_path}")
            except Exception as e:
                print(f"[Migration] Failed to migrate old profile: {e}")

    def _build_tools(self) -> ToolRegistry:
        """Build and register all tools."""
        registry = ToolRegistry()
        file_ops = FileOps(self._config.workdir)
        shell = Shell(self._config.workdir)
        wake_tool = WakeTool(self._scheduler)
        message_tool = MessageTool(self._notifier)
        memory_query_tool = MemoryQueryTool(
            self._memory_store,
            profile=self._profile,
            memory_bank=self._memory_bank,
        )
        memory_manage_tool = MemoryManageTool(self._memory_bank)
        feedback_tool = FeedbackTool(self._feedback_bank)

        registry.register(Tool(
            name="bash",
            description="Run a shell command.",
            input_schema={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            handler=lambda **kw: shell.execute(kw["command"]),
        ))
        registry.register(Tool(
            name="read_file",
            description="Read file contents.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
            handler=lambda **kw: file_ops.read(kw["path"], kw.get("limit")),
        ))
        registry.register(Tool(
            name="write_file",
            description="Write content to a file.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=lambda **kw: file_ops.write(kw["path"], kw["content"]),
        ))
        registry.register(Tool(
            name="edit_file",
            description="Replace exact text in a file.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
            handler=lambda **kw: file_ops.edit(kw["path"], kw["old_text"], kw["new_text"]),
        ))
        registry.register(Tool(
            name="query_memory",
            description=(
                "查询 Agent 自己的记忆。这是查询记忆的唯一正确方式，禁止用 bash 跑 sqlite3 命令。"
                "query_type 选项：\n"
                "  - recent_chains: 最近的思维链条（含窗口标题、应用名、空闲时间等观察详情）\n"
                "  - search_observations: 按关键词搜索观察记录（如 keyword='Trae' 查找所有包含 Trae 的记录）\n"
                "  - timeline: 可读的观察时间线\n"
                "  - session_stats: 当前会话统计\n"
                "  - profile_get: 查用户画像section。key='about_me'|'projects'|'preferences'\n"
                "  - profile_all: 查完整用户画像（markdown格式，含自动追踪数据和LLM写入的语义信息）\n"
                "  - chain_detail: 查指定思维链条详情（需传 key 参数为 chain_id）\n"
                "  - memory_index: 查看长期记忆库索引（MEMORY.md）\n"
                "  - memory_search: 按关键词搜索长期记忆文件（keyword='...'）\n"
                "  - memory_load: 加载指定记忆的完整内容（key='memory-name'）"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "description": "查询类型: recent_chains, search_observations, timeline, session_stats, profile_get, profile_all, chain_detail, memory_index, memory_search, memory_load",
                    },
                    "key": {
                        "type": "string",
                        "description": "profile_get 时传 section 名(about_me/projects/preferences)；chain_detail 时传 chain_id；memory_load 时传记忆名。",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "search_observations / memory_search 时传搜索关键词（如 'Trae', 'VSCode', 'Chrome'）。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最大返回行数（默认 10）。",
                    },
                },
                "required": ["query_type"],
            },
            handler=lambda **kw: memory_query_tool.handle(
                kw["query_type"],
                kw.get("key", ""),
                kw.get("keyword", ""),
                kw.get("limit", 10),
            ),
        ))
        registry.register(Tool(
            name="manage_memory",
            description=(
                "管理长期记忆库（data/memory/）。当用户说'记住'、表达稳定偏好、或需要记录项目/参考信息时使用。"
                "action 选项：\n"
                "  - create: 创建新记忆。需传 name, description, content, type（user/feedback/project/reference/agent）\n"
                "  - update: 更新已有记忆。需传 name, content, mode='replace'|'append'\n"
                "  - delete: 删除记忆。需传 name\n"
                "  - load: 查看记忆内容。需传 name"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "update", "delete", "load"],
                        "description": "操作类型",
                    },
                    "name": {
                        "type": "string",
                        "description": "记忆名称（用作文件名）。例如 'project-chanel-agent', 'user-preference-tabs'。",
                    },
                    "description": {
                        "type": "string",
                        "description": "简短描述，会显示在 MEMORY.md 索引中。",
                    },
                    "content": {
                        "type": "string",
                        "description": "记忆正文（markdown）。",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["user", "feedback", "project", "reference", "agent"],
                        "description": "记忆类型。user=用户画像, feedback=用户反馈/做事方式, project=项目上下文, reference=参考信息, agent=Agent经验。",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选标签列表。",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["replace", "append"],
                        "description": "update 时生效：replace=替换, append=追加。",
                    },
                },
                "required": ["action"],
            },
            handler=lambda **kw: memory_manage_tool.handle(
                kw["action"],
                kw.get("name", ""),
                kw.get("description", ""),
                kw.get("content", ""),
                kw.get("type", "reference"),
                kw.get("tags"),
                kw.get("mode", "replace"),
            ),
        ))
        registry.register(Tool(
            name="schedule_next_wake",
            description=(
                "Schedule the next autonomous wake time. Call at the end of EVERY turn "
                "to decide when to observe the user next. Minimum 5s."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "delay_seconds": {
                        "type": "integer",
                        "description": (
                            "Seconds until next wake. Short (30-120s) if user active. "
                            "Long (300-900s) if user focused or away."
                        ),
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why you chose this time. Be specific.",
                    },
                },
                "required": ["delay_seconds", "reason"],
            },
            handler=lambda **kw: wake_tool.handle(kw["delay_seconds"], kw["reason"]),
        ))
        registry.register(Tool(
            name="send_message",
            description=(
                "Send a proactive message to the user via Windows toast notification + terminal. "
                "Use this to offer help, share observations, or check in. "
                "You can optionally include quick_replies - clickable buttons on the notification."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The message to send. Keep it concise and natural.",
                    },
                    "quick_replies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional list of 1-2 short reply buttons (e.g. ['Yes please', 'No thanks']). "
                            "User can click to respond instantly."
                        ),
                    },
                },
                "required": ["content"],
            },
            handler=lambda **kw: message_tool.handle(
                kw["content"], kw.get("quick_replies")
            ),
        ))
        registry.register(Tool(
            name="set_reminder",
            description=(
                "设置定时提醒，到时间后自动弹出通知。不依赖唤醒周期，精确到分钟。"
                "action 选项：\n"
                "  - set: 创建新提醒。需传 time='YYYY-MM-DD HH:MM' 或 'HH:MM'（今天），content='提醒内容'\n"
                "  - list: 查看所有待处理的提醒\n"
                "  - cancel: 取消指定提醒。需传 reminder_id"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["set", "list", "cancel"],
                        "description": "操作类型：set=创建提醒, list=查看所有提醒, cancel=取消提醒",
                    },
                    "time": {
                        "type": "string",
                        "description": "提醒时间。格式：'YYYY-MM-DD HH:MM'（如 '2026-07-16 09:00'）或 'HH:MM'（今天，如 '17:30'）。仅 set 时需要。",
                    },
                    "content": {
                        "type": "string",
                        "description": "提醒内容。仅 set 时需要。",
                    },
                    "repeat": {
                        "type": "boolean",
                        "description": "是否重复提醒（暂不支持，可忽略）。",
                    },
                    "reminder_id": {
                        "type": "string",
                        "description": "要取消的提醒 ID。仅 cancel 时需要。",
                    },
                },
                "required": ["action"],
            },
            handler=lambda **kw: self._reminder_tool.handle(
                kw["action"],
                kw.get("time", ""),
                kw.get("content", ""),
                kw.get("repeat", False),
                kw.get("reminder_id", ""),
            ),
        ))
        registry.register(Tool(
            name="update_profile",
            description=(
                "更新你对用户的了解。当你通过对话了解到用户的新信息时，用此工具记录到用户画像中。"
                "可选的 section：\n"
                "  - about_me: 用户的角色、技术栈、身份等\n"
                "  - projects: 用户的当前项目及进展\n"
                "  - preferences: 用户的偏好（沟通风格、工作习惯等）\n"
                "注意：不要在无用户确认时擅自填充虚构信息。只记录用户明确告知或你从对话中合理推断的信息。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "enum": ["about_me", "projects", "preferences"],
                        "description": "要更新的section：about_me, projects, preferences",
                    },
                    "content": {
                        "type": "string",
                        "description": "更新内容。应简洁、事实性，直接来自用户对话。",
                    },
                },
                "required": ["section", "content"],
            },
            handler=lambda **kw: (
                self._profile.set_about_me(kw["content"])
                if kw["section"] == "about_me"
                else self._profile.set_projects(kw["content"])
                if kw["section"] == "projects"
                else self._profile.set_preferences(kw["content"])
            ) or f"Updated profile section '{kw['section']}'.",
        ))
        registry.register(Tool(
            name="record_feedback",
            description=(
                "记录用户对某个任务产出的反馈。同类任务下次执行前可用 get_feedback 查看历史偏好。\n"
                "task_type 示例：write_readme、refactor_code、write_test。\n"
                "rating 只能是 positive / neutral / negative。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task_type": {
                        "type": "string",
                        "description": "任务类型，例如 'write_readme'。",
                    },
                    "artifact": {
                        "type": "string",
                        "description": "产物路径或名称，例如 'README.md'。",
                    },
                    "request_summary": {
                        "type": "string",
                        "description": "用户原始需求的一句话摘要。",
                    },
                    "feedback": {
                        "type": "string",
                        "description": "用户的实际反馈内容。",
                    },
                    "rating": {
                        "type": "string",
                        "enum": ["positive", "neutral", "negative"],
                        "description": "反馈倾向。",
                    },
                    "style_notes": {
                        "type": "string",
                        "description": "从反馈中提取出的、下次执行同类任务时应遵循的风格要点。",
                    },
                },
                "required": ["task_type", "artifact", "request_summary", "feedback"],
            },
            handler=lambda **kw: feedback_tool.handle_record(
                kw["task_type"],
                kw["artifact"],
                kw["request_summary"],
                kw["feedback"],
                kw.get("rating", "neutral"),
                kw.get("style_notes", ""),
            ),
        ))
        registry.register(Tool(
            name="get_feedback",
            description=(
                "在开始同类任务前，查看该任务类型的历史反馈，以继承用户的风格偏好。\n"
                "例如：写 README 前先 get_feedback(task_type='write_readme')。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task_type": {
                        "type": "string",
                        "description": "任务类型，例如 'write_readme'。",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回最近几条反馈（默认 3）。",
                    },
                },
                "required": ["task_type"],
            },
            handler=lambda **kw: feedback_tool.handle_get(
                kw["task_type"],
                kw.get("top_k", 3),
            ),
        ))
        registry.register(Tool(
            name="todo_write",
            description=(
                "Create and manage a task list for your current coding session. "
                "This tool does NOT perform any actual work — it only helps you "
                "plan and track progress. Use it BEFORE starting complex tasks "
                "(3+ distinct steps).\n\n"
                "Rules:\n"
                "- Only ONE task in_progress at a time.\n"
                "- Mark tasks completed IMMEDIATELY after finishing.\n"
                "- Use merge=true to update individual task statuses without "
                "re-sending the entire list.\n"
                "- Include a brief summary when marking tasks as completed."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "The task list. Each item must have content, status, and id.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Unique identifier for this task (e.g. '1', '2', '3'). Required for merge mode.",
                                },
                                "content": {
                                    "type": "string",
                                    "description": "The task description.",
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                    "description": "Current status of the task.",
                                },
                                "priority": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                    "description": "Task priority (optional).",
                                },
                            },
                            "required": ["content", "status", "id"],
                        },
                    },
                    "merge": {
                        "type": "boolean",
                        "description": "Whether to merge the todos with the existing list. If true, only matching ids are updated; new items are appended. If false, the entire list is replaced.",
                    },
                },
                "required": ["todos", "merge"],
            },
            handler=lambda **kw: (
                self._todo_tool.handle_merge(kw["todos"])
                if kw.get("merge")
                else self._todo_tool.handle(kw["todos"])
            ),
        ))
        return registry

    def _build_hook_registry(self, workdir: Path) -> HookRegistry:
        """Register default hooks (permissions, logging, etc.)."""
        registry = HookRegistry()

        # PreToolUse: permission gate (from s03, now external to the loop)
        permission_gate = PermissionGate(
            workdir,
            prompt_func=Terminal.prompt,
        )
        registry.register("PreToolUse", permission_gate.pre_tool_use_hook)

        # PreToolUse: debug log
        def _log_pre_tool_use(block):
            Terminal.tool_debug(f"[HOOK] PreToolUse: {block.name}")
            return None

        registry.register("PreToolUse", _log_pre_tool_use)

        # PostToolUse: large-output warning
        def _warn_large_output(block, output):
            out_str = str(output)
            if len(out_str) > 50000:
                Terminal.info(f"[HOOK] Large output from {block.name}: {len(out_str)} chars")
            return None

        registry.register("PostToolUse", _warn_large_output)

        return registry

    def start(self):
        """Start the main event loop."""
        self._running = True
        if not self._tui_mode:
            self._print_banner()

        # Start callback HTTP server for notification button clicks
        self._callback_server.start()

        # Start input reader thread (not needed in TUI mode)
        if not self._tui_mode:
            threading.Thread(target=self._input_reader, daemon=True).start()

        # Initial wake
        self._scheduler.schedule(5, "Initial boot - start observing user")

        # Main event loop
        while self._running:
            etype, data = self._event_queue.get()

            if etype == "shutdown":
                self._shutdown()
                break
            elif etype == "user":
                self._handle_user_input(data)
            elif etype == "wake":
                self._handle_wake(data)
            elif etype == "reminder":
                self._handle_reminder(data)

    def _input_reader(self):
        """Background thread that reads user input."""
        while self._running:
            try:
                line = Terminal.prompt("")
            except (EOFError, KeyboardInterrupt):
                self._event_queue.put(("shutdown", None))
                return
            stripped = line.strip().lower()
            if stripped in ["q", "exit"]:
                self._event_queue.put(("shutdown", None))
                return
            if stripped == "":
                continue
            self._event_queue.put(("user", line))

    def submit_user_input(self, text: str) -> None:
        """Submit user input from TUI (or external source)."""
        self._event_queue.put(("user", text))

    def _handle_user_input(self, text: str):
        """Handle a user text input event."""
        self._agent.history.append({"role": "user", "content": text})
        self._maybe_inject_todo_reminder()
        self._agent.run_turn(is_proactive=False)
        self._todo_tool.increment_rounds()
        if not self._tui_mode:
            print()

    def _handle_wake(self, reason: str):
        """Handle an autonomous wake event."""
        snapshot = self._perception.get_snapshot()
        perception_text = snapshot.to_text_prompt()

        # Record observation in memory
        self._memory.record_observation(snapshot.to_json())

        # Get memory context
        memory_context = self._memory.get_context_for_llm(
            self._config.memory_context_turns
        )

        # Check silent streak — provides optional context for the LLM
        silent_streak = self._memory.get_silent_streak()

        # Build wake prompt with context
        wake_msg = PromptBuilder.build_wake_prompt(
            reason,
            perception_text,
            memory_context,
            silent_streak=silent_streak,
        )

        Terminal.info(f"[Wake] {reason}")
        if silent_streak >= 5:
            Terminal.info(f"(已连续 {silent_streak} 次沉默，已注入上下文提醒)")

        self._agent.history.append({"role": "user", "content": wake_msg})
        self._maybe_inject_todo_reminder()
        self._agent.run_turn(is_proactive=True)
        self._todo_tool.increment_rounds()
        if not self._tui_mode:
            print()

    def _handle_reminder(self, data: dict):
        """Handle a reminder that has fired.

        The notification was already sent by the Reminder itself.
        Here we inject the reminder into the agent's conversation so it
        knows the reminder went off and can follow up if needed.
        """
        content = data.get("content", "")
        Terminal.info(f"[Reminder Fired] {content}")

        # Inject as a system message so the agent is aware
        reminder_msg = (
            f"[SYSTEM REMINDER FIRED] 你的提醒到期了：{content}\n"
            "用户已经收到了通知弹窗。你可以 send_message 跟进一下，"
            "或者直接 schedule_next_wake 继续观察。"
        )
        self._agent.history.append({"role": "user", "content": reminder_msg})
        self._maybe_inject_todo_reminder()
        self._agent.run_turn(is_proactive=True)
        self._todo_tool.increment_rounds()
        if not self._tui_mode:
            print()

    def _maybe_inject_todo_reminder(self):
        """Inject a todo reminder if the agent hasn't used todo_write for 3+ turns.

        Design ported from learn-claude-code/s05_todo_write:
        After 3 consecutive turns without a todo_write call, a reminder message
        is injected into the conversation history before the next LLM call.
        The counter is reset when the reminder is injected, and also when the
        agent calls todo_write during a turn.
        """
        if self._todo_tool.rounds_since_todo >= 3:
            self._agent.history.append({
                "role": "user",
                "content": self._todo_tool.get_reminder_message(),
            })
            self._todo_tool.reset_rounds()
            Terminal.info("[Todo] Nag reminder injected (3+ rounds without todo_write)")

    def _shutdown(self):
        """Clean shutdown."""
        self._running = False
        self._scheduler.cancel()
        self._callback_server.stop()
        self._notifier.stop()
        self._reminder_tool.cancel_all()
        self._memory.end_session("User terminated session.")
        self._memory_store.close()
        if not self._tui_mode:
            print("\n[Shutdown] Goodbye.")

    def _print_banner(self):
        """Print startup banner (terminal mode only)."""
        if self._tui_mode:
            return
        print("=" * 60)
        print("Chanel Agent — Autonomous Agent Runtime")
        import platform
        print(f"Platform: {platform.system()} | Model: {self._config.model}")
        print(f"DB: {self._config.db_path}")
        memory_dir = self._config.db_path.parent / "memory"
        print(f"Memory Bank: {memory_dir}")
        print(f"Notifications: {'Enabled' if self._notifier.is_available() else 'Terminal only'}")
        print(f"Callback server: http://localhost:{CALLBACK_PORT}")
        print("=" * 60)
        print("Commands: type your request, or 'q' to quit.")
        print("The agent will wake itself up and observe you automatically.")
        print("Toast notifications include clickable quick-reply buttons.\n")