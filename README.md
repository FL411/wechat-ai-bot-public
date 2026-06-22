# 微信 AI 机器人

一个运行在本地电脑上的微信桌面 AI 助手。它从本地消息监听服务接收微信消息，调用 OpenAI-compatible 大模型生成回复，并通过 Web 控制台管理模型、角色人设、提醒、记忆、消息监听和机器人进程。

> 使用前请了解风险：本项目依赖微信桌面客户端、本地消息监听和自动化操作，可能触发微信风控。建议只用于个人学习、研究和本地实验，不要用于商业用途、大规模自动化或未经授权的场景。

## 主要功能

- 自动处理私聊消息，可选择是否忽略群聊
- 支持 LM Studio、OpenAI、DeepSeek、Ollama、vLLM、LocalAI 等 OpenAI-compatible 服务
- 本地 Web 控制台，可配置模型、机器人行为、角色人设、提醒和运行状态
- 可在 Web 控制台启动和查看机器人进程、消息监听器
- 支持对话记忆、角色设定、定时提醒
- 可选联网搜索：Tavily / MCP
- 过滤自己刚发送的消息，减少机器人回复自己的情况

## 适合谁使用

适合想在自己电脑上运行一个微信 AI 助手，并且愿意手动准备本地模型服务或在线 API 的用户。项目默认面向 Windows 桌面环境，不适合作为服务器端群发工具或商业自动化工具。

## 环境要求

- Windows 10/11
- Python 3.10 或更高版本
- 微信桌面客户端
- 一个可用的大模型服务，例如 LM Studio 本地服务或在线 OpenAI-compatible API
- 本地消息监听依赖目录 `wechat-decrypt-new/`

## 外部消息监听依赖

本项目的微信消息监听能力依赖第三方项目 [ylytdeng/wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt)。出于版权、授权边界和本地数据安全考虑，本仓库不分发该项目源码、解密数据或运行缓存。

使用监听功能前，请自行下载或克隆 `ylytdeng/wechat-decrypt`，并把它放到项目根目录下的 `wechat-decrypt-new/`：

```text
wechat-ai-bot/
├─ wechat-decrypt-new/
├─ web_console/
└─ bot/
```

正常使用时不需要手动进入 `wechat-decrypt-new/` 启动监听器，可以在 Web 控制台里启动。请遵守 `ylytdeng/wechat-decrypt` 的原项目许可和使用说明。

## 安装

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy bot_config.example.yaml bot_config.yaml
```

然后先启动 Web 控制台：

```bash
start_web_console.bat
```

或者：

```bash
python run_web_console.py
```

打开：`http://localhost:5000`。

## 配置模型

编辑 `bot_config.yaml`，或在 Web 控制台里修改。最小配置如下：

```yaml
llm:
  base_url: "http://localhost:1234/v1"
  api_key: ""
  model: "your-model-name"
  timeout: 60
```

使用 LM Studio 时，先在 LM Studio 中加载模型并启动本地服务，再把模型名填入 `model`。本地服务通常可以把 `api_key` 留空；在线 API 按服务商要求填写。

消息监听默认配置如下，通常不用改：

```yaml
wechat:
  webui_url: "http://localhost:5678"
  ws_url: "http://localhost:5678/stream"
```

`bot_config.yaml` 是你的真实本地配置，里面可能包含 API Key，不要上传到公开仓库。

## 启动顺序

推荐把 Web 控制台作为主入口：

1. 登录微信桌面客户端。
2. 启动你的 LLM 服务，例如 LM Studio。
3. 启动 Web 控制台：`start_web_console.bat` 或 `python run_web_console.py`。
4. 打开 `http://localhost:5000`，在控制台确认模型配置和健康状态。
5. 在 Web 控制台启动消息监听器。
6. 在 Web 控制台启动机器人。

项目里的启动脚本仍然保留，主要作为备用入口或排查问题时使用：

| 命令 | 用途 |
| --- | --- |
| `start_web_console.bat` | 主入口：启动 Web 控制台 |
| `python run_web_console.py` | 主入口：启动 Web 控制台 |
| `tools\start_bot.bat` | 备用：直接从命令行启动机器人 |
| `tools\start_listener.bat` | 备用：直接从命令行启动本地消息监听器 |
| `tools\stop_listener.bat` | 备用：停止本地监听器 |
| `tools\stop_wechat.bat` | 备用：停止 Python 进程 |

## Web 控制台

控制台默认地址是 `http://localhost:5000`，主要用于：

- 启动和查看机器人进程
- 启动和查看本地消息监听器
- 查看模型配置、日志异常摘要和 Prompt 预算
- 修改 LLM Base URL、API Key、模型名和生成参数
- 配置是否忽略群聊、回复延迟、记忆和搜索能力
- 编辑角色人设
- 配置提醒关键词、安静时间和提醒行为

API Key 输入框默认以圆点隐藏，可以手动显示明文，方便本地检查配置。

## 常见问题

### 控制台能打开，但机器人不回复

先在 Web 控制台检查消息监听器和机器人是否都已启动；再确认 `http://localhost:5678` 能看到监听器页面或消息流；最后检查 LLM 服务是否可访问，例如 LM Studio 的 `/v1/models` 接口。

### 提示模型名错误

项目不会自动替你选择模型。请在 LM Studio 或服务商控制台复制准确模型名，然后填入 `llm.model`。

### 自己发出的消息被机器人处理

确认 `wechat.outgoing_echo_filter.enabled` 为 `true`。如果仍然出现误判，可以在 Web 控制台里查看最近问题和日志摘要。

### 联网搜索不可用

搜索是可选能力。未配置 Tavily API Key 或 MCP 搜索服务时，可以把 `search.enabled` 设为 `false`。

## 本地数据和隐私

项目会在本地生成配置、日志、记忆、会话和角色数据。默认 `.gitignore` 已排除真实配置和运行时数据，包括：

- `bot_config.yaml`
- `logs/`
- `wechat-decrypt-new/`
- `data/memory/`
- `data/sessions/`
- `data/schedules/`
- `data/semantic_memory/`
- 真实角色人设和个人运行数据

如果你 fork 或二次发布项目，提交前请确认没有上传 API Key、聊天记录、本机路径、微信 ID 或个人角色数据。

## 项目结构

```text
bot/                    机器人核心逻辑
clients/                OpenAI-compatible LLM 客户端
memory/                 对话记忆
proactive/              主动消息相关逻辑
schedule/               日程和状态分析
tests/                  测试
web_console/            本地 Web 控制台
data/personas/          示例角色和角色人设（默认 default）
bot_config.example.yaml 配置模板
run_bot.py              备用机器人启动入口
run_web_console.py      Web 控制台启动入口
start_web_console.bat    主入口：启动 Web 控制台
tools/                  备用启停脚本
```

## 开发者检查

修改代码后建议运行：

```bash
ruff check .
pytest -q
```

如果本地安装了 Black，也可以运行：

```bash
black --check --line-length 100 .
```

## 许可证

MIT License，详见 [LICENSE](LICENSE)。

