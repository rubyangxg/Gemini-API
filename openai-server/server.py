"""OpenAI-compatible multi-account wrapper around gemini_webapi.

Accounts: accounts.json ([{label, secure_1psid, secure_1psidts, proxy?}]).
Falls back to single account from .env if accounts.json is absent.
Routing: round-robin load-balance + automatic failover to next account on
error or exhausted image quota. Pin one via request body {"account":"label"}.

Optional access password: set API_KEY in .env -> all data endpoints require
Authorization: Bearer <API_KEY>. Empty = open (private LAN).

Web UI served at /  (index.html). Swagger at /docs.
"""
import os, re, time, json, uuid, asyncio, pathlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from gemini_webapi import GeminiClient

BASE = pathlib.Path(__file__).parent
GEN_DIR = BASE / "generated"; GEN_DIR.mkdir(exist_ok=True)

ENV = {}
_envf = BASE / ".env"
if _envf.exists():
    for line in _envf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            ENV[k.strip()] = v.strip().strip('"').strip("'")

def cfg(k, d=None):
    return os.environ.get(k) or ENV.get(k) or d

API_KEY       = cfg("API_KEY") or None
DEFAULT_MODEL = cfg("DEFAULT_MODEL") or "unspecified"

def load_accounts():
    f = BASE / "accounts.json"
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception as e:
            print("[accounts.json parse error]", repr(e))
    psid = cfg("SECURE_1PSID")
    if psid:
        return [{"label": "main", "secure_1psid": psid,
                 "secure_1psidts": cfg("SECURE_1PSIDTS"), "proxy": cfg("PROXY") or None}]
    return []

ACCOUNTS_CFG = load_accounts()

try:
    from gemini_webapi.constants import Model
    MODELS = [m.model_name for m in Model]
except Exception:
    Model = None
    MODELS = ["unspecified"]

def resolve_model(name):
    if not name or name in ("unspecified", "gemini", "default") or Model is None:
        return None
    for m in Model:
        if name == m.model_name or name == m.name:
            return m
    for m in Model:
        if name.replace("-", "").lower() in m.model_name.replace("-", "").lower():
            return m
    return None

CLIENTS = []   # [{label, client, error}]
_rr = -1

@asynccontextmanager
async def lifespan(app):
    async def init_one(a):
        label = a.get("label") or ("acct" + uuid.uuid4().hex[:4])
        entry = {"label": label, "client": None, "error": None}
        try:
            c = GeminiClient(a.get("secure_1psid"), a.get("secure_1psidts"), proxy=a.get("proxy"))
            await c.init(timeout=30, auto_refresh=True)
            entry["client"] = c
            print("[OK] account '%s' initialized." % label)
        except Exception as e:
            entry["error"] = repr(e)
            print("[FAIL] account '%s': %r" % (label, e))
        return entry
    # 并发初始化所有账号（启动从 ~40s 降到 ~10s）
    results = await asyncio.gather(*[init_one(a) for a in ACCOUNTS_CFG])
    CLIENTS.extend(results)
    yield

app = FastAPI(title="gemini-webapi-server", lifespan=lifespan)
app.mount("/images", StaticFiles(directory=str(GEN_DIR)), name="images")

@app.get("/", response_class=HTMLResponse)
async def index():
    f = BASE / "index.html"
    if f.exists():
        return FileResponse(str(f))
    return HTMLResponse("<h3>gemini-webapi-server</h3><p>API only. See <a href='/docs'>/docs</a></p>")

def check_auth(authorization):
    if API_KEY and (not authorization or authorization.removeprefix("Bearer ").strip() != API_KEY):
        raise HTTPException(401, "unauthorized")

def ordered_clients(preferred=None):
    global _rr
    healthy = [c for c in CLIENTS if c["client"]]
    if not healthy:
        return []
    if preferred:
        pref = [c for c in healthy if c["label"] == preferred]
        if pref:
            return pref + [c for c in healthy if c["label"] != preferred]
    _rr = (_rr + 1) % len(healthy)
    return healthy[_rr:] + healthy[:_rr]

def messages_to_prompt(messages):
    parts = []
    for m in messages:
        role = m.get("role", "user"); content = m.get("content", "")
        if isinstance(content, list):
            content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
        if role == "system":
            parts.append("[System instruction]\n" + str(content))
        elif role == "assistant":
            parts.append("[Assistant]\n" + str(content))
        else:
            parts.append(str(content))
    return "\n\n".join(parts).strip()

def clean_html(text):
    text = text or ""
    m = re.search(r"```(?:html)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    text = text.strip()
    i = text.lower().find("<!doctype")
    if i < 0:
        i = text.lower().find("<html")
    return text[i:].strip() if i >= 0 else text

async def save_images(client, resp, rid, base_url):
    out = []
    for i, img in enumerate(getattr(resp, "images", None) or []):
        dest = None
        for attempt in (
            lambda: img.save(path=str(GEN_DIR), filename=rid + "_" + str(i), verbose=False, cookies=getattr(client, "cookies", None)),
            lambda: img.save(path=str(GEN_DIR), filename=rid + "_" + str(i), verbose=False),
            lambda: img.save(str(GEN_DIR), rid + "_" + str(i)),
        ):
            try:
                dest = await attempt(); break
            except TypeError:
                continue
            except Exception as e:
                print("[img save error]", repr(e)); break
        if dest:
            out.append(base_url.rstrip("/") + "/images/" + os.path.basename(dest))
    return out

# ---- 科普动画提示词（9:16 + 纯函数渲染契约） ----
LESSON_SPEC = """你是资深科普动画工程师。请为儿童科普短视频生成一个【完整单文件 HTML】，主题：《{topic}》。

硬性要求（必须全部满足）：
1. 9:16 竖屏，SVG viewBox="0 0 1080 1920"，按窗口高度等比缩放完整可见。
2. 画面可爱明亮、有儿童科普感：可加拟人化太阳/角色、表情、发光滤镜、小星星、彩虹渐变、弹出式气泡、贴纸。
3. 像老师一步一步演示（5-6 步），每步有大标题 + 一句简短解释，文字少而大，适合抖音竖屏，6-12 岁能懂。
4. 必须提供 window.__SVG_TEMPLATE_DURATION（总秒数，数字）。
5. 必须提供 window.__SVG_RENDER_AT(seconds)：画面状态【完全由 seconds 决定】，是纯函数，不依赖 setTimeout/动画历史；逐帧/倒放/跳帧都一致。每次调用要把所有元素的 opacity/transform/dash 全量重写。
6. 必须提供 window.__SVG_CUEPOINTS 数组：每步含 {{time, step, title, subtitle, highlight}}。
7. 自动时间轴循环播放（requestAnimationFrame 驱动，仅用来喂 seconds），并保留可拖动进度条 + 播放/暂停按钮用于预览；控制条按 H 可隐藏。
8. 若用随机星星/装饰，必须用固定坐标或固定种子（如 mulberry32），保证每次渲染一致。
9. 关键节点要有重点闪烁/暂停讲解感。
10. 不依赖任何外部库/CDN/联网素材；全部内联在一个 HTML 文件里。

只输出完整 HTML 代码本身，从 <!DOCTYPE html> 开始，不要任何解释文字，不要用 markdown 代码块包裹。"""

@app.get("/health")
async def health(authorization: str = Header(None)):
    check_auth(authorization)
    return {"status": "ok",
            "accounts": [{"label": c["label"], "ready": c["client"] is not None, "error": c["error"]} for c in CLIENTS],
            "ready_count": sum(1 for c in CLIENTS if c["client"]),
            "models": MODELS}

@app.get("/accounts")
async def accounts(authorization: str = Header(None)):
    check_auth(authorization)
    return [{"label": c["label"], "ready": c["client"] is not None, "error": c["error"]} for c in CLIENTS]

@app.get("/v1/models")
async def list_models(authorization: str = Header(None)):
    check_auth(authorization)
    return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "google-gemini-web"} for m in MODELS]}

@app.post("/v1/chat/completions")
async def chat_completions(request: Request, authorization: str = Header(None)):
    check_auth(authorization)
    body = await request.json()
    messages = body.get("messages", []); stream = bool(body.get("stream", False))
    model = resolve_model(body.get("model"))
    prompt = messages_to_prompt(messages)
    if not prompt:
        raise HTTPException(400, "empty prompt")
    cands = ordered_clients(body.get("account"))
    if not cands:
        raise HTTPException(503, "no ready account.")
    kwargs = {"model": model} if model is not None else {}
    last_err = None
    for c in cands:
        try:
            resp = await c["client"].generate_content(prompt, **kwargs)
        except Exception as e:
            last_err = e; print("[chat fail acct %s] %r" % (c["label"], e)); continue
        text = resp.text or ""
        rid = uuid.uuid4().hex[:16]
        urls = await save_images(c["client"], resp, rid, str(request.base_url))
        if urls:
            text += "\n\n" + "\n".join("![image](" + u + ")" for u in urls)
        cid = "chatcmpl-" + rid; created = int(time.time()); mid = body.get("model") or DEFAULT_MODEL
        if stream:
            async def gen():
                chunk = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": mid,
                         "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]}
                yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
                done = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": mid,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                yield "data: " + json.dumps(done, ensure_ascii=False) + "\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")
        return JSONResponse({
            "id": cid, "object": "chat.completion", "created": created, "model": mid,
            "account": c["label"], "images": urls,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
    raise HTTPException(502, "all accounts failed. last: " + repr(last_err))

@app.post("/v1/images/generations")
async def images_generations(request: Request, authorization: str = Header(None)):
    check_auth(authorization)
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "empty prompt")
    model = resolve_model(body.get("model"))
    kwargs = {"model": model} if model is not None else {}
    cands = ordered_clients(body.get("account"))
    if not cands:
        raise HTTPException(503, "no ready account.")
    last_msg = ""
    for c in cands:
        try:
            resp = await c["client"].generate_content(prompt, **kwargs)
            rid = uuid.uuid4().hex[:16]
            urls = await save_images(c["client"], resp, rid, str(request.base_url))
            if urls:
                return JSONResponse({"created": int(time.time()), "account": c["label"],
                                     "data": [{"url": u} for u in urls], "text": resp.text or ""})
            last_msg = "[%s] %s" % (c["label"], (resp.text or "")[:200])
            print("[no image, try next] " + last_msg)
        except Exception as e:
            last_msg = "[%s] %r" % (c["label"], e)
    raise HTTPException(422, "no image from any account. last: " + last_msg)

@app.post("/v1/lesson")
async def lesson(request: Request, authorization: str = Header(None)):
    """生成一个 9:16 科普动画 HTML（带 __SVG_RENDER_AT 纯函数契约）。"""
    check_auth(authorization)
    body = await request.json()
    topic = (body.get("topic") or "").strip()
    if not topic:
        raise HTTPException(400, "empty topic")
    model = resolve_model(body.get("model"))
    kwargs = {"model": model} if model is not None else {}
    prompt = LESSON_SPEC.format(topic=topic)
    cands = ordered_clients(body.get("account"))
    if not cands:
        raise HTTPException(503, "no ready account.")
    last = ""
    for c in cands:
        try:
            resp = await c["client"].generate_content(prompt, **kwargs)
            html = clean_html(resp.text or "")
            if "<svg" in html.lower() or "<!doctype" in html.lower():
                return JSONResponse({"account": c["label"], "topic": topic, "html": html})
            last = "[%s] %s" % (c["label"], (resp.text or "")[:200])
        except Exception as e:
            last = "[%s] %r" % (c["label"], e)
    raise HTTPException(502, "lesson generation failed. last: " + last)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=cfg("HOST", "0.0.0.0"), port=int(cfg("PORT", "18090")))
