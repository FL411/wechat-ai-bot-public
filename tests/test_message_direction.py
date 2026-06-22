"""检查消息方向过滤所需字段。"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DECRYPTED_DB = ROOT / "wechat-decrypt-new" / "decrypted" / "_monitor_cache" / "message_message_0.db"


def test_message_direction():
    print("=" * 60)
    print("测试消息方向字段")
    print("=" * 60)

    if not DECRYPTED_DB.exists():
        print(f"[X] 解密数据库不存在: {DECRYPTED_DB}")
        print("请先启动监听器，让它解密数据库")
        return

    try:
        conn = sqlite3.connect(f"file:{DECRYPTED_DB}?mode=ro", uri=True)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
        ).fetchall()

        if not tables:
            print("[X] 没有找到消息表")
            return

        table_name = tables[0][0]
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info([{table_name}])").fetchall()]
        print(f"\n检查表: {table_name}")
        print(f"字段: {', '.join(columns)}")

        required = {"real_sender_id", "origin_source", "status"}
        missing = required - set(columns)
        if missing:
            print(f"[X] 缺少方向过滤字段: {', '.join(sorted(missing))}")
            return

        rows = conn.execute(f"""
            SELECT local_id, create_time, real_sender_id, origin_source, status, message_content
            FROM [{table_name}]
            ORDER BY create_time DESC, local_id DESC
            LIMIT 5
        """).fetchall()

        print(f"\n[OK] 最近 {len(rows)} 条消息:\n")
        for local_id, create_time, sender_id, origin_source, status, content in rows:
            direction = "发送候选(out)" if origin_source == 1 or status == 2 else "接收候选(in)"
            content_preview = content[:50] if content else "(无内容)"
            if isinstance(content_preview, bytes):
                content_preview = content_preview.decode("utf-8", errors="replace")[:50]
            print(
                f"[{direction}] local_id={local_id}, time={create_time}, sender_id={sender_id}, origin_source={origin_source}, status={status}"
            )
            print(f"  内容: {content_preview}\n")

        conn.close()
        print("=" * 60)
        print("[OK] 方向过滤字段可用")
        print("=" * 60)

    except Exception as e:
        print(f"[X] 测试失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_message_direction()
