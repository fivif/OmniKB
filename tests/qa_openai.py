"""OmniKB × OpenAI QA 生产测试"""
import asyncio, json, time, httpx, os, sys

BASE = os.environ.get("OMNIKB_BASE_URL", "http://localhost:6886")
PASS, FAIL, PARTIAL = 0, 0, 0
RESULTS = []

QUESTIONS = [
    # Company (4 questions)
    {"q": "OpenAI的CEO是谁？公司总部在哪里？", "expected": ["Sam Altman", "旧金山", "San Francisco"], "cat": "公司背景", "weight": 1},
    {"q": "OpenAI成立于哪一年？ChatGPT是什么时候发布的？", "expected": ["2015", "2022", "2022年11月"], "cat": "公司背景", "weight": 1},
    {"q": "ChatGPT Plus和Pro的月费分别是多少？", "expected": ["20", "200"], "cat": "公司背景", "weight": 1},
    {"q": "GPTs和Canvas分别是什么时候推出的？", "expected": ["2023年11月", "GPTs", "Canvas"], "cat": "公司背景", "weight": 1},

    # GPT models (5 questions)
    {"q": "GPT-4o的上下文窗口是多少？定价是多少？", "expected": ["128000", "128K", "2.50", "10.00"], "cat": "GPT模型", "weight": 1},
    {"q": "GPT-4o-mini的输入和输出价格分别是多少？", "expected": ["0.15", "0.60"], "cat": "GPT模型", "weight": 1},
    {"q": "GPT-4.1系列的共同特点是什么？上下文窗口多大？", "expected": ["1M", "1047576", "2024-06-01"], "cat": "GPT模型", "weight": 1},
    {"q": "GPT-4.1-nano的特点是什么？定价多少？", "expected": ["最快", "最具成本效益", "0.10", "0.40"], "cat": "GPT模型", "weight": 1},
    {"q": "GPT-4.1-mini的输入价格和缓存价格分别是多少？", "expected": ["0.40", "0.10"], "cat": "GPT模型", "weight": 1},

    # Reasoning models (5 questions)
    {"q": "o1模型的上下文窗口和最大输出是多少？", "expected": ["200000", "200K", "100000", "100K"], "cat": "推理模型", "weight": 1},
    {"q": "o1-pro的输入和输出价格分别是多少？", "expected": ["150", "600"], "cat": "推理模型", "weight": 1},
    {"q": "o3-mini支持哪些功能？定价是多少？", "expected": ["Structured Outputs", "Function Calling", "Batch", "1.10", "4.40"], "cat": "推理模型", "weight": 1},
    {"q": "o4-mini的描述是什么？上下文窗口多大？", "expected": ["快速", "经济", "编码", "视觉", "200000"], "cat": "推理模型", "weight": 1},
    {"q": "o3-pro不支持哪些功能？", "expected": ["Streaming", "Fine-tuning"], "cat": "推理模型", "weight": 1},

    # GPT-5 (2 questions)
    {"q": "GPT-5-mini的输入和输出价格分别是多少？", "expected": ["0.25", "2.00"], "cat": "GPT-5", "weight": 1},
    {"q": "GPT-5-pro的定价是多少？", "expected": ["15.00", "120.00"], "cat": "GPT-5", "weight": 1},

    # Image & Video (3 questions)
    {"q": "DALL-E 3支持哪些尺寸？HD 1024x1024的价格是多少？", "expected": ["1024", "0.08"], "cat": "图像视频", "weight": 1},
    {"q": "Sora 2 Pro最高分辨率是多少？价格是多少？", "expected": ["1080", "1920", "0.70"], "cat": "图像视频", "weight": 1},
    {"q": "DALL-E 2最多支持一次生成多少张图？", "expected": ["10", "n=10"], "cat": "图像视频", "weight": 1},

    # Speech (3 questions)
    {"q": "Whisper的定价是多少？支持哪些音频格式？", "expected": ["0.006", "flac", "mp3", "wav", "ogg"], "cat": "语音模型", "weight": 1},
    {"q": "TTS有几种声音选项？推荐最佳音质的是哪两种？", "expected": ["13", "marin", "cedar", "13种"], "cat": "语音模型", "weight": 1},
    {"q": "gpt-4o-mini-tts的最大输入是多少tokens？", "expected": ["2000"], "cat": "语音模型", "weight": 1},

    # Embeddings & Moderation (2 questions)
    {"q": "text-embedding-3-large和small的维度分别是多少？", "expected": ["3072", "1536"], "cat": "嵌入审核", "weight": 1},
    {"q": "Moderation的omni-moderation-latest支持哪些输入模态？", "expected": ["文本", "图片", "text", "image"], "cat": "嵌入审核", "weight": 1},

    # API Services (3 questions)
    {"q": "Assistants API支持哪些工具类型？", "expected": ["function calling", "file search", "code interpreter"], "cat": "API服务", "weight": 1},
    {"q": "Realtime API的WebSocket端点是什么？", "expected": ["wss://api.openai.com/v1/realtime", "WebSocket"], "cat": "API服务", "weight": 1},
    {"q": "Batch API的折扣是多少？单批次上限是多少？", "expected": ["50%", "50000", "50000"], "cat": "API服务", "weight": 1},

    # Pricing & Rate Limits (3 questions)
    {"q": "o3-pro的输出价格是多少？o1的输入价格是多少？", "expected": ["80.00", "15.00"], "cat": "定价限制", "weight": 1},
    {"q": "Rate Limit Tier 5的RPM和TPM分别是多少？", "expected": ["30000", "150000000"], "cat": "定价限制", "weight": 1},
    {"q": "Prompt Caching的最高延迟和成本降低分别是多少？", "expected": ["80%", "90%"], "cat": "定价限制", "weight": 1},

    # Cross-category multi-hop (3 questions)
    {"q": "OpenAI有哪些GPT-4.1系列模型？它们有什么区别？", "expected": ["GPT-4.1", "GPT-4.1-mini", "GPT-4.1-nano"], "cat": "综合对比", "weight": 2},
    {"q": "o系列推理模型包含哪些型号？", "expected": ["o1", "o3", "o4-mini", "o1-pro", "o1-mini", "o3-mini", "o3-pro"], "cat": "综合对比", "weight": 2},
    {"q": "OpenAI的语音产品线包含哪些模型？", "expected": ["Whisper", "TTS", "Transcribe", "gpt-4o-mini-tts"], "cat": "综合对比", "weight": 2},
]


async def search_kb(c, query, top_k=10):
    try:
        r = await c.get(f"{BASE}/search", params={"q": query, "top_k": top_k, "mode": "hybrid"}, timeout=120)
        return r.json() if r.status_code == 200 else {"results": [], "mode": "error", "query": query}
    except Exception as e:
        return {"results": [], "error": str(e), "query": query}


def evaluate(data, q):
    results = data.get("results", [])
    w = q["weight"]
    d = {"query": q["q"], "cat": q["cat"], "weight": w, "expected": q["expected"],
         "found": [], "missing": [], "scores": [], "has_hl": False, "top": "",
         "results_count": len(results), "mode": data.get("mode", "hybrid")}
    if not results:
        d["judgment"] = "无结果"
        return 0, w, d
    d["scores"] = [r.get("score", 0) for r in results[:5]]
    d["has_hl"] = any("highlight" in r for r in results)
    d["top"] = results[0].get("content", "")[:150] if results else ""
    text = " ".join(r.get("content", "") for r in results[:5]).lower()
    if d.get("mode", "").endswith("+expanded"):
        text += " " + " ".join(r.get("content", "") for r in results[5:]).lower()
    content_lower = text.lower()
    # Normalize: strip commas from numbers for matching
    content_normalized = content_lower.replace(",", "")
    for t in q["expected"]:
        term_lower = t.lower()
        # Direct match
        if term_lower in content_lower:
            d["found"].append(t)
        # Comma-agnostic number match
        elif term_lower in content_normalized:
            d["found"].append(t)
        # Format variants
        elif t == "San Francisco" and "旧金山" in content_lower:
            d["found"].append(t)
        elif t == "2022年11月" and "2022.11" in content_lower:
            d["found"].append(t)
        else:
            d["missing"].append(t)
    hit = len(d["found"]) / len(q["expected"]) if q["expected"] else 0
    if hit >= 0.8: score, d["judgment"] = w, "优秀"
    elif hit >= 0.5: score, d["judgment"] = w * 0.6, "部分覆盖"
    elif hit > 0: score, d["judgment"] = w * 0.3, "少量覆盖"
    else: score, d["judgment"] = 0, "未覆盖"
    return score, w, d


async def main():
    global PASS, FAIL, PARTIAL
    print("=" * 60)
    print("  OmniKB × OpenAI QA 生产测试")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    total_score, total_max = 0, 0
    cases = []

    async with httpx.AsyncClient(timeout=120) as c:
        s = (await c.get(f"{BASE}/kb/stats")).json()
        print(f"\n  KB: {s['total_sources']} sources, {s['total_chunks']} chunks\n")

        for i, q in enumerate(QUESTIONS, 1):
            print(f"[{i}/{len(QUESTIONS)}] [{q['cat']}] {q['q']}")
            data = await search_kb(c, q["q"])
            score, m, d = evaluate(data, q)
            total_score += score; total_max += m
            v = "PASS" if score >= m else ("PARTIAL" if score > 0 else "FAIL")
            g = {"PASS": True, "PARTIAL": None, "FAIL": False}[v]
            if v == "PASS": PASS += 1
            elif v == "PARTIAL": PARTIAL += 1
            else: FAIL += 1
            found = ", ".join(d["found"][:5]) or "(none)"
            missing = ", ".join(d["missing"][:5]) or "(none)"
            print(f"  -> {v} | {score}/{m} | Found: {found}")
            if missing != "(none)":
                print(f"     Missing: {missing}")
            cases.append({"id": i, **d, "verdict": v, "score": score, "max_score": m})

    pct = total_score / total_max * 100 if total_max else 0
    print(f"\n{'='*60}")
    print(f"  总分: {total_score:.1f}/{total_max} ({pct:.1f}%)")
    print(f"  PASS: {PASS} | PARTIAL: {PARTIAL} | FAIL: {FAIL}")
    print(f"{'='*60}")

    html = build_html(cases, total_score, total_max, pct)
    path = os.path.join("tests/qa_results", "openai_qa_report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nReport: {path}")
    return 0 if FAIL == 0 else 1


def build_html(cases, ts, tm, pct):
    gl = "S" if pct >= 95 else ("A" if pct >= 90 else "B")
    gc = "#22c55e" if pct >= 90 else ("#06b6d4" if pct >= 80 else "#eab308")

    cats = {}
    for c in cases:
        cats.setdefault(c["cat"], []).append(c)
    cat_rows = "".join(
        f"<tr><td>{cn}</td><td>{len(cc)}</td>"
        f"<td><span class='bar'><span class='fill' style='width:{sum(x['score'] for x in cc)/max(sum(x['max_score'] for x in cc),1)*100:.0f}%;background:{gc}'></span></span>{sum(x['score'] for x in cc):.1f}/{sum(x['max_score'] for x in cc)}</td>"
        f"<td style='color:#22c55e'>{sum(1 for x in cc if x['verdict']=='PASS')}</td>"
        f"<td style='color:#eab308'>{sum(1 for x in cc if x['verdict']=='PARTIAL')}</td>"
        f"<td style='color:#ef4444'>{sum(1 for x in cc if x['verdict']=='FAIL')}</td>"
        f"<td style='color:{gc};font-weight:700'>{sum(x['score'] for x in cc)/max(sum(x['max_score'] for x in cc),1)*100:.0f}%</td></tr>"
        for cn, cc in sorted(cats.items())
    )

    rows = "".join(
        f"<tr><td>{c['id']}</td><td><span class='tag tag-{c.get('cat','other')}'>{c['cat']}</span></td>"
        f"<td class='qc'>{c['query']}</td>"
        f"<td class='tc'>{''.join(f'<code>{t}</code> ' for t in c['found'][:5]) or '<span class=dim>-</span>'}</td>"
        f"<td class='tc'>{''.join(f'<code>{t}</code> ' for t in c['missing'][:5]) or '<span class=dim>-</span>'}</td>"
        f"<td><span class='bar'><span class='fill' style='width:{c['score']/max(c['max_score'],1)*100:.0f}%;background:{'#22c55e' if c['verdict']=='PASS' else ('#eab308' if c['verdict']=='PARTIAL' else '#ef4444')}'></span></span>{c['score']}/{c['max_score']}</td>"
        f"<td class='v' style='color:{'#22c55e' if c['verdict']=='PASS' else ('#eab308' if c['verdict']=='PARTIAL' else '#ef4444')}'>{c['verdict']}</td></tr>"
        for c in cases
    )

    return f"""<!DOCTYPE html>
<html lang=zh-CN>
<head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1.0'>
<title>OmniKB × OpenAI QA 测试报告</title>
<style>
body {{ background:#0f172a;color:#e2e8f0;font-family:-apple-system,sans-serif;padding:24px }}
h1 {{ font-size:28px;font-weight:700;margin-bottom:4px }}
h2 {{ font-size:16px;color:#94a3b8;font-weight:400;margin-bottom:24px }}
.meta {{ display:flex;gap:20px;margin-bottom:28px;flex-wrap:wrap }}
.meta-item {{ background:#1e293b;border-radius:12px;padding:16px 24px;flex:1;min-width:120px;text-align:center }}
.meta-item .val {{ font-size:30px;font-weight:700 }}
.meta-item .label {{ font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-top:4px }}
.grade {{ width:100px;height:100px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:42px;font-weight:800;margin:0 auto }}
.card {{ background:#1e293b;border-radius:12px;padding:20px;margin-bottom:24px }}
.card h3 {{ font-size:13px;color:#64748b;margin-bottom:12px;text-transform:uppercase;letter-spacing:1px }}
table {{ width:100%;border-collapse:collapse;font-size:13px }}
th {{ text-align:left;padding:8px 6px;border-bottom:1px solid #334155;color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:1px }}
td {{ padding:8px 6px;border-bottom:1px solid #1e293b;vertical-align:top }}
.qc {{ max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap }}
.tc {{ font-size:12px }}
.tc code {{ background:#1e293b;padding:1px 5px;border-radius:3px;color:#22c55e }}
.dim {{ color:#475569 }}
.tag {{ display:inline-block;padding:1px 8px;border-radius:4px;font-size:11px;font-weight:600 }}
.v {{ font-size:13px;font-weight:700 }}
.bar {{ display:inline-block;width:55px;height:6px;background:#334155;border-radius:3px;vertical-align:middle;margin-right:6px;overflow:hidden }}
.fill {{ display:block;height:100%;border-radius:3px }}
.section {{ font-size:20px;font-weight:600;margin:28px 0 12px;padding-bottom:8px;border-bottom:1px solid #334155 }}
.tag-公司背景 {{ background:#312e81;color:#a5b4fc }}
.tag-GPT模型 {{ background:#155e75;color:#67e8f9 }}
.tag-推理模型 {{ background:#78350f;color:#fcd34d }}
.tag-GPT-5 {{ background:#3b0764;color:#c4b5fd }}
.tag-图像视频 {{ background:#831843;color:#f9a8d4 }}
.tag-语音模型 {{ background:#064e3b;color:#6ee7b7 }}
.tag-嵌入审核 {{ background:#115e59;color:#5eead4 }}
.tag-API服务 {{ background:#1e3a5f;color:#93c5fd }}
.tag-定价限制 {{ background:#7c2d12;color:#fdba74 }}
.tag-综合对比 {{ background:#4c1d95;color:#d8b4fe }}
</style></head><body>
<h1>🧪 OmniKB × OpenAI QA 测试报告</h1>
<h2>验证 OmniKB 对 OpenAI 产品资料的检索和问答能力</h2>
<div class=meta>
<div class=meta-item><div class=grade style='background:{gc}22;color:{gc}'>{gl}</div><div class=label>评级</div></div>
<div class=meta-item><div class=val style=color:#22c55e>{ts:.1f}</div><div class=label>得分/{tm}</div></div>
<div class=meta-item><div class=val style=color:{gc}>{pct:.1f}%</div><div class=label>准确率</div></div>
<div class=meta-item><div class=val style=color:#22c55e>{sum(1 for c in cases if c['verdict']=='PASS')}</div><div class=label>PASS</div></div>
<div class=meta-item><div class=val style=color:#eab308>{sum(1 for c in cases if c['verdict']=='PARTIAL')}</div><div class=label>PARTIAL</div></div>
<div class=meta-item><div class=val style=color:#ef4444>{sum(1 for c in cases if c['verdict']=='FAIL')}</div><div class=label>FAIL</div></div>
</div>
<div class=card><h3>📊 分类统计</h3>
<table><thead><tr><th>类别</th><th>用例</th><th>得分</th><th>PASS</th><th>PARTIAL</th><th>FAIL</th><th>%</th></tr></thead>
<tbody>{cat_rows}</tbody></table></div>
<div class=section>📋 全部测试用例</div>
<table><thead><tr><th>#</th><th>类别</th><th>问题</th><th>命中关键词</th><th>缺失关键词</th><th>得分</th><th>判定</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class=section>🔍 系统信息</div>
<table>
<tr><td style=color:#64748b;width:200px>Chunk size</td><td>800 chars</td></tr>
<tr><td style=color:#64748b>搜索模式</td><td>Hybrid + Cross-encoder rerank + Source diversification + Query expansion</td></tr>
<tr><td style=color:#64748b>嵌入模型</td><td>BAAI/bge-m3 (1024d) via SiliconFlow</td></tr>
<tr><td style=color:#64748b>OpenAI素材文件</td><td>9 份 (公司/GPT/推理/GPT5/图像/语音/嵌入/API/定价)</td></tr>
<tr><td style=color:#64748b>测试时间</td><td>{time.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
</table>
<p style=text-align:center;color:#475569;margin-top:48px;font-size:12px>OmniKB × OpenAI QA Test</p>
</body></html>"""

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
