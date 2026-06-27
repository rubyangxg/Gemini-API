#!/usr/bin/env python3
"""一键生成 9:16 竖屏 HTML+SVG 儿童科普原理动画。

调用部署在 10.10.20.89:18090 的 gemini-webapi 服务（走你的 AI Pro 会员账号）。
只用标准库，无需 pip 安装。

用法：
    python generate_lesson.py "为什么天空是蓝色的？"
    python generate_lesson.py "月亮为什么会有圆缺" --model gemini-3-pro-advanced --open
    python generate_lesson.py "彩虹是怎么形成的" -o E:/out/rainbow.html
"""
import argparse, json, os, re, sys, time, urllib.request, webbrowser, pathlib

# Windows 控制台常是 GBK，强制 UTF-8 输出，避免 emoji/中文打印崩溃
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

API = "http://10.10.20.89:18090/v1/chat/completions"

# ---- 生产规格提示词（与三棱镜示例同标准：纯函数渲染 + cuePoints） ----
SPEC = r"""你是资深科普动画工程师。请为儿童科普短视频生成一个【完整单文件 HTML】，主题：《{topic}》。

硬性要求（必须全部满足）：
1. 9:16 竖屏，SVG viewBox="0 0 1080 1920"，按窗口高度等比缩放完整可见。
2. 画面可爱明亮、有儿童科普感：可加拟人化太阳/角色、表情、发光滤镜、小星星、彩虹渐变、弹出式气泡、贴纸。
3. 像老师一步一步演示（5-6 步），每步有大标题 + 一句简短解释，文字少而大，适合抖音竖屏，6-12 岁能懂。
4. 必须提供 window.__SVG_TEMPLATE_DURATION（总秒数，数字）。
5. 必须提供 window.__SVG_RENDER_AT(seconds)：画面状态【完全由 seconds 决定】，是纯函数，不依赖 setTimeout/动画历史；逐帧/倒放/跳帧都一致。每次调用要把所有元素的 opacity/transform/dash 全量重写。
6. 必须提供 window.__SVG_CUEPOINTS 数组：每步含 {{time, step, title, subtitle, highlight}}。
7. 自动时间轴循环播放（requestAnimationFrame 驱动，仅用来喂 seconds），并保留可拖动进度条 + 播放/暂停按钮用于预览；控制条不属于画面本体，按 H 可隐藏。
8. 若用随机星星/装饰，必须用固定坐标或固定种子，保证每次渲染一致（可用 mulberry32 之类带固定种子）。
9. 关键节点要有重点闪烁/暂停讲解感（如核心现象出现、对比时刻）。
10. 不依赖任何外部库/CDN/联网素材；全部内联在一个 HTML 文件里。

只输出完整 HTML 代码本身，从 <!DOCTYPE html> 开始，不要任何解释文字，不要用 markdown 代码块包裹。"""


def call(topic, model, timeout, key=None):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": SPEC.format(topic=topic)}],
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode("utf-8"), headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"]


def clean_html(text):
    # 去掉可能的 ```html ... ``` 包裹
    m = re.search(r"```(?:html)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    text = text.strip()
    # 从 <!DOCTYPE 或 <html 起截取，去掉前置寒暄
    i = text.lower().find("<!doctype")
    if i < 0:
        i = text.lower().find("<html")
    return text[i:].strip() if i >= 0 else text


def safe_name(topic):
    s = re.sub(r"[\\/:*?\"<>|\s]+", "-", topic).strip("-")
    return (s[:40] or "lesson")


def main():
    ap = argparse.ArgumentParser(description="一键生成 9:16 HTML 科普动画")
    ap.add_argument("topic", help="科普主题，如 “为什么天空是蓝色的”")
    ap.add_argument("--model", default="gemini-3-pro", help="模型（默认 gemini-3-pro，会员可用 gemini-3-pro-advanced）")
    ap.add_argument("-o", "--out", default=None, help="输出文件路径")
    ap.add_argument("--timeout", type=int, default=180, help="超时秒数")
    ap.add_argument("--key", default=os.environ.get("GEMINI_UI_KEY"), help="访问口令（或设环境变量 GEMINI_UI_KEY）")
    ap.add_argument("--open", action="store_true", help="生成后用浏览器打开")
    args = ap.parse_args()

    out = pathlib.Path(args.out) if args.out else pathlib.Path(f"lesson-{safe_name(args.topic)}.html")

    print(f"→ 主题：{args.topic}")
    print(f"→ 模型：{args.model}  调用 {API} ...")
    t0 = time.time()
    try:
        text = call(args.topic, args.model, args.timeout, args.key)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        print(f"✗ 服务返回 {e.code}: {body[:300]}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"✗ 调用失败：{e}", file=sys.stderr)
        sys.exit(1)

    html = clean_html(text)
    if "<svg" not in html.lower():
        print("⚠ 返回内容里没检测到 <svg>，仍按原样保存，请人工检查。", file=sys.stderr)
    out.write_text(html, encoding="utf-8")
    print(f"✓ 已保存 {out}  （{len(html)} 字节，用时 {time.time()-t0:.1f}s）")
    if args.open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
