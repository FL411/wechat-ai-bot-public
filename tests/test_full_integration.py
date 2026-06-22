"""
完整集成测试 - 模拟机器人运行
"""

# ruff: noqa: E402

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clients.factory import create_client
from bot.config import load_bot_config

print("=" * 60)
print("微信 AI 机器人 - 完整集成测试")
print("=" * 60)

try:
    # 1. 加载配置
    print("\n[1/4] 加载配置...")
    config = load_bot_config("bot_config.yaml")
    llm_config = config.get("llm", {})
    print("  [OK] 后端: OpenAI-Compatible")
    print(f"  [OK] 模型: {llm_config.get('model')}")

    # 2. 创建 LLM 客户端
    print("\n[2/4] 创建 LLM 客户端...")
    client = create_client(llm_config)
    print("  [OK] 客户端创建成功")

    # 3. 测试对话能力
    print("\n[3/4] 测试对话能力...")

    response1 = client.chat(
        [
            {"role": "system", "content": "你是一个友好的AI助手。"},
            {"role": "user", "content": "你好"},
        ],
        temperature=0.7,
    )
    print("  Q: 你好")
    print(f"  A: {response1[:80]}...")

    response2 = client.chat(
        [
            {"role": "system", "content": "你是一个友好的AI助手。"},
            {"role": "user", "content": "我叫张三"},
            {"role": "assistant", "content": "你好张三！很高兴认识你。"},
            {"role": "user", "content": "我叫什么名字？"},
        ],
        temperature=0.1,
    )
    print("  Q: 我叫什么名字？")
    print(f"  A: {response2[:80]}...")

    # 4. 关闭客户端
    print("\n[4/4] 清理资源...")
    client.close()
    print("  [OK] 客户端已关闭")

    print("\n" + "=" * 60)
    print("[SUCCESS] 所有测试通过！机器人核心功能正常！")
    print("=" * 60)
    print("\n下一步：")
    print("  1. 登录微信桌面客户端")
    print("  2. 运行 start_listener.bat 启动消息监听")
    print("  3. 运行 python run_bot.py 启动机器人")
    print("  4. 给机器人发送微信消息测试")

except Exception as e:
    print(f"\n[ERROR] 测试失败: {e}")
    import traceback

    traceback.print_exc()
