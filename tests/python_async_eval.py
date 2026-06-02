"""Python Async 生态知识库 — 检索召回评测

场景：Python 异步编程文档（asyncio 标准库 + FastAPI 并发）
数据：9 个官方文档页面，通过 URL 摄入入库
"""

import json
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"

# ── 评测题目 ────────────────────────────────────────────────
# 每题：{question, expected_keywords: [必须出现的关键词]}
QUESTIONS = [
    # ── asyncio 基础 ──
    {
        "q": "asyncio.run() 函数的作用是什么？",
        "keys": ["run", "coroutine", "event loop", "entry point"]
    },
    {
        "q": "Python 中 async def 定义的函数返回什么类型的对象？",
        "keys": ["coroutine", "await"]
    },
    {
        "q": "asyncio 中如何等待多个协程并发完成？",
        "keys": ["gather", "wait", "create_task"]
    },

    # ── Task 管理 ──
    {
        "q": "asyncio.create_task() 的作用是什么？在什么时候使用？",
        "keys": ["create_task", "concurrent", "coroutine"]
    },
    {
        "q": "Python 3.11 引入了什么新的 Task 管理方式？",
        "keys": ["TaskGroup", "task", "context manager"]
    },
    {
        "q": "如何取消一个正在运行的 asyncio Task？",
        "keys": ["cancel", "CancelledError", "task"]
    },

    # ── 同步原语 ──
    {
        "q": "asyncio 提供了哪些同步原语？",
        "keys": ["Lock", "Semaphore", "Event", "Condition"]
    },
    {
        "q": "asyncio.Semaphore 的典型使用场景是什么？",
        "keys": ["Semaphore", "limit", "concurrent", "acquire"]
    },
    {
        "q": "asyncio.Event 和 threading.Event 有什么区别？",
        "keys": ["Event", "await", "set", "wait"]
    },

    # ── 队列 ──
    {
        "q": "asyncio.Queue 和 queue.Queue 的关键区别是什么？",
        "keys": ["Queue", "await", "get", "put", "async"]
    },
    {
        "q": "asyncio 提供了哪几种队列类型？",
        "keys": ["Queue", "LifoQueue", "PriorityQueue", "FIFO"]
    },
    {
        "q": "asyncio.Queue 的 maxsize 参数默认值是多少？如果队列满了会怎样？",
        "keys": ["maxsize", "queue", "put", "wait"]
    },

    # ── 流 ──
    {
        "q": "asyncio 中如何建立 TCP 客户端连接？",
        "keys": ["open_connection", "reader", "writer", "stream"]
    },
    {
        "q": "asyncio.start_server() 的回调函数接收什么参数？",
        "keys": ["start_server", "StreamReader", "StreamWriter", "client"]
    },

    # ── 子进程 ──
    {
        "q": "asyncio 中如何创建并等待一个子进程完成？",
        "keys": ["create_subprocess", "communicate", "wait", "PIPE"]
    },
    {
        "q": "asyncio.create_subprocess_exec 和 create_subprocess_shell 有什么区别？",
        "keys": ["exec", "shell", "command", "args", "subprocess"]
    },

    # ── 异常 ──
    {
        "q": "asyncio.TimeoutError 在什么情况下会被触发？",
        "keys": ["TimeoutError", "timeout", "wait_for", "CancelledError"]
    },
    {
        "q": "asyncio.CancelledError 应该被捕获吗？为什么？",
        "keys": ["CancelledError", "cancel", "task", "re-raise"]
    },

    # ── FastAPI 并发 ──
    {
        "q": "FastAPI 中 async def 和 def 路由函数的并发模型有什么区别？",
        "keys": ["async", "thread", "await", "blocking", "async def"]
    },
    {
        "q": "FastAPI 如何处理 CPU 密集型任务？",
        "keys": ["thread", "threadpool", "run_in_executor", "background"]
    },
]


def search(query: str, top_k: int = 10, mode: str = "hybrid") -> list[dict]:
    """Call /search API."""
    params = f"q={urllib.parse.quote(query)}&top_k={top_k}&mode={mode}"
    req = urllib.request.Request(f"{BASE}/search?{params}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data.get("results", [])


def evaluate_one(q: dict) -> dict:
    """Score one question by keyword hit rate in top-10 results."""
    results = search(q["q"], top_k=10, mode="hybrid")
    all_text = " ".join(
        r.get("content", "") + " " + r.get("metadata", {}).get("source_name", "")
        for r in results
    ).lower()

    expected = q["keys"]
    found = [k for k in expected if k.lower() in all_text]
    hit_rate = len(found) / len(expected) if expected else 1.0

    if hit_rate >= 0.8:
        verdict = "优秀"
    elif hit_rate >= 0.5:
        verdict = "部分覆盖"
    elif hit_rate > 0:
        verdict = "少量覆盖"
    else:
        verdict = "未覆盖"

    return {
        "question": q["q"],
        "expected": expected,
        "found": found,
        "hit_rate": round(hit_rate, 2),
        "verdict": verdict,
        "top_chunks": [
            {
                "source": r.get("metadata", {}).get("source_name", "")[:100],
                "score": r.get("score", 0),
                "text": r.get("content", "")[:150],
            }
            for r in results[:3]
        ],
    }


def main():
    print("=" * 70)
    print("Python Async 生态 — RAG 检索评测")
    print(f"评测题目: {len(QUESTIONS)} 道")
    print(f"检索模式: hybrid (Dense + Sparse + RRF)")
    print("=" * 70)

    all_results = []
    verdicts = {"优秀": 0, "部分覆盖": 0, "少量覆盖": 0, "未覆盖": 0}

    for i, q in enumerate(QUESTIONS, 1):
        try:
            result = evaluate_one(q)
        except Exception as e:
            result = {
                "question": q["q"],
                "expected": q["keys"],
                "found": [],
                "hit_rate": 0,
                "verdict": "检索失败",
                "top_chunks": [],
                "error": str(e),
            }
            if "检索失败" not in verdicts:
                verdicts["检索失败"] = 0
            verdicts["检索失败"] += 1
            all_results.append(result)
            print(f"\n[{i}/{len(QUESTIONS)}] ❌ 检索失败: {e}")
            continue

        verdicts[result["verdict"]] += 1
        all_results.append(result)

        icon = {"优秀": "✅", "部分覆盖": "⚠️", "少量覆盖": "🔶", "未覆盖": "❌"}[result["verdict"]]
        missing = [k for k in result["expected"] if k not in result["found"]]
        print(f"\n[{i}/{len(QUESTIONS)}] {icon} {result['verdict']} "
              f"({result['hit_rate']:.0%} | 命中 {len(result['found'])}/{len(result['expected'])})")
        print(f"  Q: {result['question']}")
        if missing:
            print(f"  缺失: {', '.join(missing)}")
        if result["top_chunks"]:
            top = result["top_chunks"][0]
            print(f"  Top1: [{top['score']:.2f}] {top['source']}")
            print(f"        {top['text'][:120]}")

        time.sleep(0.3)  # 避免压测 API

    # ── 汇总 ──
    print("\n" + "=" * 70)
    print("评测汇总")
    print("=" * 70)
    total = len(QUESTIONS)
    for v, count in sorted(verdicts.items()):
        pct = count / total * 100 if total else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"  {v:8s}: {count:2d}/{total} ({pct:5.1f}%) {bar}")

    avg_hit = sum(r["hit_rate"] for r in all_results) / total if total else 0
    print(f"\n  平均命中率: {avg_hit:.1%}")
    print(f"  优秀率: {verdicts.get('优秀', 0)/total:.1%}")

    # 保存结果
    out_path = __file__.replace(".py", f"_{int(time.time())}.json")
    with open(out_path, "w") as f:
        json.dump({
            "scenario": "Python Async 生态",
            "total_questions": total,
            "verdicts": verdicts,
            "avg_hit_rate": avg_hit,
            "results": all_results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存: {out_path}")


if __name__ == "__main__":
    main()
