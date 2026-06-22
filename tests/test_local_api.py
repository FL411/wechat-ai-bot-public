"""测试本地 API 连接"""

# ruff: noqa: E402

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clients.factory import create_client

config = {
    "api_key": os.getenv("LOCAL_API_KEY", "sk-your-local-api-key"),
    "base_url": os.getenv("LOCAL_API_BASE_URL", "http://localhost:5001/v1"),
    "model": os.getenv("LOCAL_API_MODEL", "deepseek-v4-flash"),
    "timeout": 30,
}

print("=" * 50)
print(f"测试本地 API ({config['base_url']})")
print(f"模型: {config['model']}")
print("=" * 50)

try:
    print("\n1. 创建客户端...")
    client = create_client(config)
    print("   [OK] 客户端创建成功")

    print("\n2. 测试对话...")
    response = client.chat([{"role": "user", "content": "你好，请用一句话介绍你自己"}])
    print("   [OK] API 响应成功")
    print(f"\n   回复: {response}")

    client.close()
    print("\n[SUCCESS] 测试完成！本地 API 工作正常。")

except Exception as e:
    print(f"\n[ERROR] 测试失败: {e}")
    import traceback

    traceback.print_exc()
