# gemini-webapi-server

一个基于 [`gemini_webapi`](https://github.com/HanaokaYuzu/Gemini-API) 的 **OpenAI 兼容多账号 HTTP 服务 + Web 控制台**。
用 Google 网页端 cookie 把 Gemini 包成本地 API，可复用 AI Pro 会员档位模型，不另花钱。

> ⚠️ 逆向网页接口，违反 Google ToS，请仅用于个人学习/自用，风险自负。

## 功能

- **OpenAI 兼容**：`POST /v1/chat/completions`（支持 stream）、`POST /v1/images/generations`
- **多账号池**：`accounts.json` 配多个 cookie，**轮询负载均衡 + 自动故障转移**（某号报错或图像额度用尽自动切下一个）；请求体 `{"account":"<label>"}` 可指定账号
- **Web 控制台**（`/`）：账号状态面板、对话、图像生成、一键 9:16 科普动画生成
- **科普动画**：`POST /v1/lesson` 生成自带 `__SVG_RENDER_AT(seconds)` 纯函数逐帧契约的竖屏 HTML+SVG 动画
- **可选口令**：`.env` 里 `API_KEY` 非空时，所有数据接口需 `Authorization: Bearer <API_KEY>`
- **并发初始化**：多账号同时 init，启动更快
- Swagger 文档：`/docs`

## 快速开始

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # 填 API_KEY / 端口等
cp accounts.json.example accounts.json   # 填各账号 cookie（或在 .env 填单账号）

python server.py                    # 默认 http://0.0.0.0:18090
```

浏览器打开 `http://<host>:18090/` 即为控制台。

### 获取 cookie

登录 `gemini.google.com` → F12 → Application → Cookies → 复制 `__Secure-1PSID` 和 `__Secure-1PSIDTS`。
多个账号需用**独立浏览器配置 / 无痕窗口**分别登录，否则 cookie 相同。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 账号状态 + 模型列表 |
| GET | `/v1/models` | 模型列表 |
| POST | `/v1/chat/completions` | OpenAI 兼容对话 |
| POST | `/v1/images/generations` | 图像生成（返回 `/images/<f>` URL）|
| POST | `/v1/lesson` | 生成 9:16 科普动画 HTML `{topic, model?, account?}` |
| GET | `/` | Web 控制台 |

调用示例：

```bash
curl http://localhost:18090/v1/chat/completions \
  -H "Authorization: Bearer <API_KEY>" -H "Content-Type: application/json" \
  -d '{"model":"gemini-3-pro","messages":[{"role":"user","content":"你好"}]}'
```

## 工具脚本

- `add_account.py <label> <1psid> <1psidts> [proxy]` —— 往 `accounts.json` 增/改账号并重启服务
- `generate_lesson.py "<主题>" [--model ...] [--key <口令>] [--open]` —— 命令行一键生成科普动画 HTML

## systemd（开机自启）

见 `gemini-webapi.service`（`systemctl --user` 用户级单元）。

## 安全

`.env`、`accounts.json`、`generated/` 已在 `.gitignore` 中，**不要提交真实 cookie**。
