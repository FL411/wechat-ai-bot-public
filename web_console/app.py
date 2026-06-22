"""Web 控制台 - 配置管理和实时控制"""

import os
import shutil
import yaml
import re
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from datetime import datetime
from typing import Dict, Any, Optional
from loguru import logger
import threading
import subprocess
import psutil
import sys

app = Flask(__name__)
CORS(app)

# 配置文件路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(PROJECT_ROOT, "bot_config.yaml")

# 全局变量存储当前机器人实例
bot_instance = None
bot_lock = threading.Lock()

# 监听器进程管理
monitor_process = None
monitor_lock = threading.Lock()
bot_process = None
bot_process_lock = threading.Lock()


BOT_LOG_FILE = os.path.join(PROJECT_ROOT, "logs", "bot_current.log")
LOG_LEVELS = {
    "TRACE": 5,
    "DEBUG": 10,
    "INFO": 20,
    "SUCCESS": 25,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}
LOG_LINE_RE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) \| (?P<level>[A-Z]+)\s+ \| (?P<source>.*?) - (?P<message>.*)$"
)


def _parse_log_line(line: str) -> Dict[str, Any]:
    match = LOG_LINE_RE.match(line.rstrip("\n"))
    if not match:
        return {
            "time": "",
            "level": "INFO",
            "source": "",
            "message": line.rstrip("\n"),
            "raw": line.rstrip("\n"),
        }
    data = match.groupdict()
    data["raw"] = line.rstrip("\n")
    return data


def _read_bot_log_entries(
    offset: int = 0, level: str = "TRACE", limit: int = 300
) -> Dict[str, Any]:
    level = str(level or "TRACE").upper()
    min_level = LOG_LEVELS.get(level, 5)
    limit = max(1, min(int(limit or 300), 1000))

    if not os.path.exists(BOT_LOG_FILE):
        return {"entries": [], "offset": 0, "size": 0, "exists": False}

    size = os.path.getsize(BOT_LOG_FILE)
    offset = max(0, int(offset or 0))
    if offset > size:
        offset = 0

    with open(BOT_LOG_FILE, "rb") as f:
        f.seek(offset)
        data = f.read()
        next_offset = f.tell()

    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    entries = []
    for line in lines:
        entry = _parse_log_line(line)
        if LOG_LEVELS.get(entry.get("level", "INFO"), 20) >= min_level:
            entries.append(entry)
    if len(entries) > limit:
        entries = entries[-limit:]
    return {"entries": entries, "offset": next_offset, "size": size, "exists": True}


def _find_bot_processes() -> list:
    """查找独立启动的机器人进程。"""
    processes = []
    try:
        current_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                if proc.info.get("pid") == current_pid:
                    continue
                name = (proc.info.get("name") or "").lower()
                if "python" not in name:
                    continue
                cmdline = proc.info.get("cmdline") or []
                cmd_text = " ".join(str(part) for part in cmdline)
                cmd_norm = cmd_text.replace("\\", "/").lower()
                if "run_bot.py" not in cmd_norm:
                    continue
                processes.append(
                    {
                        "pid": proc.info.get("pid"),
                        "cmdline": cmd_text,
                        "started_at": (
                            datetime.fromtimestamp(proc.info.get("create_time")).isoformat()
                            if proc.info.get("create_time")
                            else None
                        ),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        logger.warning(f"检查机器人进程失败: {e}")
    return processes


def _terminate_process_tree(pid: int) -> bool:
    """终止指定进程树。"""
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    try:
        proc = psutil.Process(pid)
        children = proc.children(recursive=True)
        for child in children:
            child.terminate()
        proc.terminate()
        gone, alive = psutil.wait_procs([proc, *children], timeout=5)
        for item in alive:
            item.kill()
        return bool(gone) or not psutil.pid_exists(pid)
    except psutil.NoSuchProcess:
        return True


def load_config() -> Dict[str, Any]:
    """加载配置文件"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
        return {}


def save_config(config: Dict[str, Any]) -> bool:
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        return True
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        return False


def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并 dict，页面只更新提交的字段。"""
    result = dict(base or {})
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _drop_blank_secret_updates(updates: Dict[str, Any]) -> Dict[str, Any]:
    """空密钥输入表示保留现有配置，避免 API 误把 secret 清空。"""
    cleaned = dict(updates or {})
    llm = cleaned.get("llm")
    if isinstance(llm, dict) and not str(llm.get("api_key", "")).strip():
        llm = dict(llm)
        llm.pop("api_key", None)
        cleaned["llm"] = llm

    search = cleaned.get("search")
    if isinstance(search, dict):
        tavily = search.get("tavily")
        if isinstance(tavily, dict) and not str(tavily.get("api_key", "")).strip():
            search = dict(search)
            tavily = dict(tavily)
            tavily.pop("api_key", None)
            search["tavily"] = tavily
            cleaned["search"] = search

    return cleaned


def _recent_problem_logs(limit: int = 5) -> list:
    try:
        result = _read_bot_log_entries(offset=0, level="WARNING", limit=limit)
        return result.get("entries", [])[-limit:]
    except Exception as e:
        logger.debug(f"读取健康日志摘要失败: {e}")
        return []


def _build_health_status(config: Dict[str, Any], bot_processes: list) -> Dict[str, Any]:
    llm = config.get("llm", {}) or {}
    persona = config.get("persona", {}) or {}
    active_persona = persona.get("active") or ""
    persona_exists = False
    if active_persona:
        try:
            persona_exists = os.path.isdir(_persona_path(active_persona, config))
        except ValueError:
            persona_exists = False

    log_exists = os.path.exists(BOT_LOG_FILE)
    return {
        "llm": {
            "base_url": llm.get("base_url") or "",
            "model": llm.get("model") or "",
            "has_api_key": bool(str(llm.get("api_key") or "").strip()),
            "timeout": llm.get("timeout"),
        },
        "persona": {
            "active": active_persona,
            "exists": persona_exists,
            "persona_dir": _get_persona_dir(config),
        },
        "process": {
            "count": len(bot_processes),
            "pids": [proc.get("pid") for proc in bot_processes if proc.get("pid")],
        },
        "logs": {
            "exists": log_exists,
            "size": os.path.getsize(BOT_LOG_FILE) if log_exists else 0,
            "recent_problems": _recent_problem_logs(),
        },
    }


def _get_persona_dir(config: Optional[Dict[str, Any]] = None) -> str:
    config = config or load_config()
    persona_dir = config.get("persona", {}).get("persona_dir", "data/personas")
    if not os.path.isabs(persona_dir):
        persona_dir = os.path.join(PROJECT_ROOT, persona_dir)
    return os.path.abspath(persona_dir)


def _validate_persona_name(persona_name: str) -> str:
    name = str(persona_name or "").strip()
    if not name:
        raise ValueError("角色名不能为空")
    if len(name) > 80:
        raise ValueError("角色名过长")
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("角色名不能包含路径分隔符")
    if os.path.basename(name) != name or ".." in name:
        raise ValueError("角色名不能包含路径穿越")
    return name


def _persona_path(persona_name: str, config: Optional[Dict[str, Any]] = None) -> str:
    name = _validate_persona_name(persona_name)
    persona_dir = _get_persona_dir(config)
    path = os.path.abspath(os.path.join(persona_dir, name))
    if os.path.commonpath([persona_dir, path]) != persona_dir:
        raise ValueError("角色路径非法")
    return path


def _persona_setting_file(persona_path: str) -> str:
    primary = os.path.join(persona_path, "persona.md")
    legacy = os.path.join(persona_path, "角色设定.md")
    return primary if os.path.exists(primary) or not os.path.exists(legacy) else legacy


def _read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content or "")


def list_personas() -> list:
    """列出所有角色"""
    personas = []
    config = load_config()
    persona_dir = _get_persona_dir(config)
    active = config.get("persona", {}).get("active")
    try:
        if not os.path.exists(persona_dir):
            return personas

        for persona_name in sorted(os.listdir(persona_dir)):
            try:
                persona_name = _validate_persona_name(persona_name)
            except ValueError:
                continue
            persona_path = _persona_path(persona_name, config)
            if not os.path.isdir(persona_path):
                continue

            # 读取角色设定
            setting_file = _persona_setting_file(persona_path)
            identity_file = os.path.join(persona_path, "identity.txt")

            persona_info = {
                "name": persona_name,
                "has_setting": os.path.exists(setting_file),
                "has_identity": os.path.exists(identity_file),
                "active": persona_name == active,
            }

            # 读取简介
            if os.path.exists(identity_file):
                try:
                    with open(identity_file, "r", encoding="utf-8") as f:
                        persona_info["identity"] = f.read().strip()
                except Exception:
                    pass

            personas.append(persona_info)

    except Exception as e:
        logger.error(f"列出角色失败: {e}")

    return personas


def get_persona_profile(persona_name: str) -> Optional[Dict[str, Any]]:
    """获取完整角色内容"""
    try:
        config = load_config()
        persona_path = _persona_path(persona_name, config)
        if not os.path.isdir(persona_path):
            return None
        name = os.path.basename(persona_path)
        return {
            "name": name,
            "identity": _read_text(os.path.join(persona_path, "identity.txt")),
            "setting": _read_text(_persona_setting_file(persona_path)),
            "active": config.get("persona", {}).get("active") == name,
        }
    except Exception as e:
        logger.error(f"读取角色失败: {e}")
    return None


def save_persona_profile(persona_name: str, identity: str, setting: str) -> bool:
    """保存完整角色内容"""
    try:
        persona_path = _persona_path(persona_name)
        if not os.path.isdir(persona_path):
            return False
        _write_text(os.path.join(persona_path, "identity.txt"), identity)
        _write_text(os.path.join(persona_path, "persona.md"), setting)
        return True
    except Exception as e:
        logger.error(f"保存角色失败: {e}")
        return False


@app.route("/")
def index():
    """主页"""
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    """获取当前配置"""
    config = load_config()
    return jsonify({"success": True, "config": config})


@app.route("/api/config", methods=["POST"])
def update_config():
    """更新配置"""
    try:
        data = _drop_blank_secret_updates(request.json or {})
        config = load_config()

        allowed_sections = {"llm", "bot", "search", "reminder", "prompt", "wechat", "persona"}
        for section in allowed_sections:
            if section not in data:
                continue
            incoming = data.get(section)
            if isinstance(incoming, dict) and isinstance(config.get(section), dict):
                config[section] = _deep_merge(config.get(section, {}), incoming)
            else:
                config[section] = incoming

        # 保存配置
        if save_config(config):
            return jsonify(
                {"success": True, "message": "配置已更新，需要重启机器人生效", "config": config}
            )
        else:
            return jsonify({"success": False, "message": "保存配置失败"}), 500

    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/personas", methods=["GET"])
def get_personas():
    """获取所有角色列表"""
    personas = list_personas()
    return jsonify({"success": True, "personas": personas})


@app.route("/api/personas", methods=["POST"])
def create_persona():
    """新增角色"""
    try:
        data = request.json or {}
        name = _validate_persona_name(data.get("name", ""))
        persona_path = _persona_path(name)
        if os.path.exists(persona_path):
            return jsonify({"success": False, "message": "角色已存在"}), 400

        os.makedirs(persona_path, exist_ok=False)
        _write_text(os.path.join(persona_path, "identity.txt"), data.get("identity", ""))
        _write_text(os.path.join(persona_path, "persona.md"), data.get("setting", ""))

        config = load_config()
        if not config.get("persona", {}).get("active"):
            config["persona"] = _deep_merge(config.get("persona", {}), {"active": name})
            save_config(config)

        return jsonify({"success": True, "message": "角色已创建", "name": name})
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.error(f"创建角色失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/persona/<persona_name>", methods=["GET"])
def get_persona(persona_name: str):
    """获取完整角色"""
    try:
        profile = get_persona_profile(persona_name)
        if profile is not None:
            return jsonify({"success": True, **profile})
        return jsonify({"success": False, "message": "角色不存在或读取失败"}), 404
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400


@app.route("/api/persona/<persona_name>", methods=["POST"])
def update_persona(persona_name: str):
    """更新完整角色"""
    try:
        data = request.json or {}
        current = get_persona_profile(persona_name)
        if current is None:
            return jsonify({"success": False, "message": "角色不存在"}), 404
        identity = data.get("identity", current.get("identity", ""))
        setting = data.get("setting", current.get("setting", ""))

        if save_persona_profile(persona_name, identity, setting):
            return jsonify({"success": True, "message": "角色已更新"})
        else:
            return jsonify({"success": False, "message": "保存失败"}), 500

    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.error(f"更新角色失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/persona/<persona_name>/copy", methods=["POST"])
def copy_persona(persona_name: str):
    """复制角色"""
    try:
        data = request.json or {}
        target_name = _validate_persona_name(data.get("name", ""))
        source_path = _persona_path(persona_name)
        target_path = _persona_path(target_name)
        if not os.path.isdir(source_path):
            return jsonify({"success": False, "message": "源角色不存在"}), 404
        if os.path.exists(target_path):
            return jsonify({"success": False, "message": "目标角色已存在"}), 400
        shutil.copytree(source_path, target_path)
        return jsonify({"success": True, "message": "角色已复制", "name": target_name})
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.error(f"复制角色失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/persona/<persona_name>", methods=["DELETE"])
def delete_persona(persona_name: str):
    """删除角色"""
    try:
        config = load_config()
        persona_path = _persona_path(persona_name, config)
        if not os.path.isdir(persona_path):
            return jsonify({"success": False, "message": "角色不存在"}), 404

        personas = list_personas()
        if len(personas) <= 1:
            return jsonify({"success": False, "message": "不能删除唯一角色"}), 400

        deleted_name = os.path.basename(persona_path)
        shutil.rmtree(persona_path)
        remaining = [item["name"] for item in list_personas() if item["name"] != deleted_name]

        if config.get("persona", {}).get("active") == deleted_name and remaining:
            config["persona"] = _deep_merge(config.get("persona", {}), {"active": remaining[0]})
            save_config(config)

        return jsonify({"success": True, "message": "角色已删除"})
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.error(f"删除角色失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/persona/<persona_name>/activate", methods=["POST"])
def activate_persona(persona_name: str):
    """设置默认角色"""
    try:
        name = _validate_persona_name(persona_name)
        persona_path = _persona_path(name)
        if not os.path.isdir(persona_path):
            return jsonify({"success": False, "message": "角色不存在"}), 404

        config = load_config()
        config["persona"] = _deep_merge(config.get("persona", {}), {"active": name})
        if save_config(config):
            return jsonify({"success": True, "message": "默认角色已更新", "active": name})
        return jsonify({"success": False, "message": "保存配置失败"}), 500
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.error(f"设置默认角色失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/logs/bot", methods=["GET"])
def get_bot_logs():
    """读取 bot 实时日志。"""
    try:
        offset = int(request.args.get("offset", 0) or 0)
        level = request.args.get("level", "TRACE")
        limit = int(request.args.get("limit", 300) or 300)
        result = _read_bot_log_entries(offset=offset, level=level, limit=limit)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"读取 bot 日志失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/logs/bot/clear", methods=["POST"])
def clear_bot_logs():
    """清空 bot 当前日志文件。"""
    try:
        os.makedirs(os.path.dirname(BOT_LOG_FILE), exist_ok=True)
        with open(BOT_LOG_FILE, "w", encoding="utf-8") as f:
            f.write("")
        return jsonify({"success": True, "offset": 0})
    except Exception as e:
        logger.error(f"清空 bot 日志失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/status", methods=["GET"])
def get_status():
    """获取机器人状态"""
    with bot_lock:
        is_running = bot_instance is not None

    config = load_config()
    bot_processes = _find_bot_processes()
    is_running = is_running or bool(bot_processes)

    return jsonify(
        {
            "success": True,
            "status": {
                "running": is_running,
                "timestamp": datetime.now().isoformat(),
                "mode": (
                    "embedded"
                    if bot_instance is not None
                    else ("process" if bot_processes else "stopped")
                ),
                "processes": bot_processes,
                "health": _build_health_status(config, bot_processes),
            },
        }
    )


@app.route("/api/bot/start", methods=["POST"])
def start_bot():
    """启动机器人进程。"""
    global bot_process

    with bot_process_lock:
        existing = _find_bot_processes()
        if existing:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": f"Bot 已在运行中 (PID: {existing[0]['pid']})",
                        "processes": existing,
                    }
                ),
                400,
            )

        script = os.path.join(PROJECT_ROOT, "run_bot.py")
        if not os.path.exists(script):
            return jsonify({"success": False, "message": f"启动脚本不存在: {script}"}), 404

        try:
            os.makedirs(os.path.join(PROJECT_ROOT, "logs"), exist_ok=True)
            stdout_path = os.path.join(PROJECT_ROOT, "logs", "bot_process.out.log")
            stderr_path = os.path.join(PROJECT_ROOT, "logs", "bot_process.err.log")
            stdout = open(stdout_path, "a", encoding="utf-8")
            stderr = open(stderr_path, "a", encoding="utf-8")
            bot_process = subprocess.Popen(
                [sys.executable, "run_bot.py"],
                cwd=PROJECT_ROOT,
                stdout=stdout,
                stderr=stderr,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            logger.info(f"Bot 进程已启动，PID: {bot_process.pid}")
            return jsonify({"success": True, "message": "Bot 启动成功", "pid": bot_process.pid})
        except Exception as e:
            bot_process = None
            logger.error(f"启动 Bot 失败: {e}")
            return jsonify({"success": False, "message": f"启动失败: {str(e)}"}), 500


@app.route("/api/bot/stop", methods=["POST"])
def stop_bot():
    """停止机器人进程。"""
    global bot_process

    with bot_process_lock:
        try:
            processes = _find_bot_processes()
            if not processes:
                bot_process = None
                return jsonify({"success": False, "message": "Bot 未运行"}), 400

            stopped = []
            failed = []
            for proc in processes:
                pid = proc.get("pid")
                if not pid:
                    continue
                if _terminate_process_tree(int(pid)):
                    stopped.append(pid)
                else:
                    failed.append(pid)

            bot_process = None
            if failed:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"部分 Bot 进程停止失败: {failed}",
                            "stopped": stopped,
                            "failed": failed,
                        }
                    ),
                    500,
                )

            logger.info(f"Bot 进程已停止: {stopped}")
            return jsonify({"success": True, "message": "Bot 已停止", "stopped": stopped})
        except Exception as e:
            logger.error(f"停止 Bot 失败: {e}")
            return jsonify({"success": False, "message": f"停止失败: {str(e)}"}), 500


@app.route("/api/test_connection", methods=["POST"])
def test_connection():
    """测试 LLM 连接"""
    try:
        data = request.json
        config = data.get("config", {})

        from clients.factory import create_client

        # 创建客户端
        client = create_client(config)

        # 测试连接
        response = client.chat([{"role": "user", "content": "Hello"}])

        client.close()

        return jsonify(
            {"success": True, "message": "连接成功", "response": response[:100] if response else ""}
        )

    except Exception as e:
        logger.error(f"测试连接失败: {e}")
        return jsonify({"success": False, "message": f"连接失败: {str(e)}"}), 500


@app.route("/api/prompt/preview", methods=["POST"])
def preview_prompt():
    """预览实际发给模型的 prompt messages。"""
    try:
        data = request.json or {}
        message = str(data.get("message") or "测试消息").strip()
        session_name = str(data.get("session_name") or "preview_session").strip()
        persona = data.get("persona") or None

        config = load_config()
        persona_dir = config.get("persona", {}).get("persona_dir", "data/personas")
        if not os.path.isabs(persona_dir):
            persona_dir = os.path.join(PROJECT_ROOT, persona_dir)

        from bot.prompt import PromptBuilder, PromptContext, PersonaLoader
        from memory.session_manager import SessionManager

        session_manager = SessionManager(async_enabled=False)
        history = session_manager.get_messages(session_name)
        builder = PromptBuilder(config, PersonaLoader(persona_dir))
        result = builder.build_chat_messages(
            PromptContext(
                user_message=message,
                session_name=session_name,
                persona=persona,
                history=history,
                schedule_context="",
                metadata={"preview": True},
            )
        )

        return jsonify(
            {
                "success": True,
                "messages": result.messages,
                "stats": result.stats,
            }
        )
    except Exception as e:
        logger.error(f"Prompt 预览失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/monitor/status", methods=["GET"])
def get_monitor_status():
    """获取监听器状态"""
    try:
        # 检查端口 5678 是否被占用
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("localhost", 5678))
        sock.close()

        is_running = result == 0

        # 如果进程存在，检查进程是否还活着
        global monitor_process
        with monitor_lock:
            if monitor_process:
                poll = monitor_process.poll()
                if poll is not None:
                    # 进程已结束
                    monitor_process = None
                    is_running = False

        return jsonify({"success": True, "running": is_running, "port": 5678})
    except Exception as e:
        logger.error(f"检查监听器状态失败: {e}")
        return jsonify({"success": False, "running": False, "message": str(e)}), 500


@app.route("/api/monitor/start", methods=["POST"])
def start_monitor():
    """启动监听器服务"""
    global monitor_process

    with monitor_lock:
        # 检查是否已经运行
        if monitor_process and monitor_process.poll() is None:
            return jsonify({"success": False, "message": "监听器已在运行中"}), 400

        try:
            # 启动监听器进程
            monitor_script = os.path.join(PROJECT_ROOT, "wechat-decrypt-new", "main.py")
            if not os.path.exists(monitor_script):
                return (
                    jsonify({"success": False, "message": f"监听器脚本不存在: {monitor_script}"}),
                    404,
                )

            # 使用 subprocess.Popen 启动后台进程
            # 使用绝对路径和工作目录，确保在任何环境下都能正确启动
            monitor_dir = os.path.join(PROJECT_ROOT, "wechat-decrypt-new")
            monitor_process = subprocess.Popen(
                [sys.executable, "main.py"],
                cwd=monitor_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )

            logger.info(f"监听器进程已启动，PID: {monitor_process.pid}")

            return jsonify(
                {"success": True, "message": "监听器启动成功", "pid": monitor_process.pid}
            )

        except Exception as e:
            logger.error(f"启动监听器失败: {e}")
            monitor_process = None
            return jsonify({"success": False, "message": f"启动失败: {str(e)}"}), 500


@app.route("/api/monitor/stop", methods=["POST"])
def stop_monitor():
    """停止监听器服务"""
    global monitor_process

    with monitor_lock:
        try:
            # 方法1: 如果有进程对象，直接终止
            if monitor_process and monitor_process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(monitor_process.pid)],
                        capture_output=True,
                    )
                else:
                    monitor_process.terminate()
                    monitor_process.wait(timeout=5)
                logger.info(f"监听器进程已停止，PID: {monitor_process.pid}")
                monitor_process = None
                return jsonify({"success": True, "message": "监听器已停止"})

            # 方法2: 查找占用 5678 端口的进程并终止
            if os.name == "nt":
                # Windows: 使用 netstat 查找端口占用
                result = subprocess.run(
                    ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True
                )

                for line in result.stdout.split("\n"):
                    if ":5678" in line and "LISTENING" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            try:
                                subprocess.run(
                                    ["taskkill", "/F", "/T", "/PID", pid], capture_output=True
                                )
                                logger.info(f"已终止占用 5678 端口的进程，PID: {pid}")
                                monitor_process = None
                                return jsonify(
                                    {"success": True, "message": f"监听器已停止 (PID: {pid})"}
                                )
                            except Exception as e:
                                logger.error(f"终止进程失败: {e}")

            # 如果没有找到进程
            monitor_process = None
            return jsonify({"success": False, "message": "监听器未运行"}), 400

        except Exception as e:
            logger.error(f"停止监听器失败: {e}")
            return jsonify({"success": False, "message": f"停止失败: {str(e)}"}), 500


def set_bot_instance(bot):
    """设置机器人实例"""
    global bot_instance
    with bot_lock:
        bot_instance = bot


def run_web_console(host: str = "0.0.0.0", port: int = 5000):
    """启动 Web 控制台"""
    logger.info(f"启动 Web 控制台: http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run_web_console()
