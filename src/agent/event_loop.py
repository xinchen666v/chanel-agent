"""Event-driven main loop - orchestrates user input and autonomous wake events."""

import queue
import threading

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
from memory.store import MemoryStore
from memory.chain import ThoughtChain
from memory.profile import UserProfile
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
        profile_md_path = config.db_path.parent / "user_profile.md"
        self._profile = UserProfile(profile_md_path)
        self._memory = ThoughtChain(self._memory_store, self._profile)

        # Initialize tools
        self._tools = self._build_tools()

        # Initialize Anthropic client
        self._client = Anthropic(
            base_url=config.api_base_url,
            api_key=config.api_key,
        )

        # Build system prompt with profile
        profile_context = self._memory.get_profile_context()
        self._system_prompt = PromptBuilder.build(config.workdir, profile_context)

        # Initialize agent core
        self._agent = AgentCore(
            client=self._client,
            model=config.model,
            system_prompt=self._system_prompt,
            tools=self._tools,
            memory=self._memory,
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

    def _build_tools(self) -> ToolRegistry:
        """Build and register all tools."""
        registry = ToolRegistry()
        file_ops = FileOps(self._config.workdir)
        shell = Shell(self._config.workdir)
        wake_tool = WakeTool(self._scheduler)
        message_tool = MessageTool(self._notifier)
        memory_query_tool = MemoryQueryTool(self._memory_store, profile=self._profile)

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
                "查询 Agent 自己的记忆库（SQLite）。这是查询记忆的唯一正确方式，禁止用 bash 跑 sqlite3 命令。"
                "query_type 选项：\n"
                "  - recent_chains: 最近的思维链条（含窗口标题、应用名、空闲时间等观察详情）\n"
                "  - search_observations: 按关键词搜索观察记录（如 keyword='Trae' 查找所有包含 Trae 的记录）\n"
                "  - timeline: 可读的观察时间线\n"
                "  - session_stats: 当前会话统计\n"
                "  - profile_get: 查用户画像section。key='about_me'|'projects'|'preferences'\n"
                "  - profile_all: 查完整用户画像（markdown格式，含自动追踪数据和LLM写入的语义信息）\n"
                "  - chain_detail: 查指定思维链条详情（需传 key 参数为 chain_id）"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "description": "查询类型: recent_chains, search_observations, timeline, session_stats, profile_get, profile_all, chain_detail",
                    },
                    "key": {
                        "type": "string",
                        "description": "profile_get 时传 section 名(about_me/projects/preferences)；chain_detail 时传 chain_id。",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "search_observations 时传搜索关键词（如 'Trae', 'VSCode', 'Chrome'）。",
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
        self._agent.run_turn(is_proactive=False)
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
        self._agent.run_turn(is_proactive=True)
        if not self._tui_mode:
            print()

    def _shutdown(self):
        """Clean shutdown."""
        self._running = False
        self._scheduler.cancel()
        self._callback_server.stop()
        self._notifier.stop()
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
        profile_md = self._config.db_path.parent / "user_profile.md"
        print(f"Profile: {profile_md}")
        print(f"Notifications: {'Enabled' if self._notifier.is_available() else 'Terminal only'}")
        print(f"Callback server: http://localhost:{CALLBACK_PORT}")
        print("=" * 60)
        print("Commands: type your request, or 'q' to quit.")
        print("The agent will wake itself up and observe you automatically.")
        print("Toast notifications include clickable quick-reply buttons.\n")