# EYES Clinical Extractor

病例 OCR 结构化抽取系统

EYES 是一个面向临床科研数据录入的 MVP：上传病例 PDF/图片/文本，本地 OCR 和脱敏后抽取结构化字段，按置信度自动填入或进入人工复核，并导出带证据审计表的 Excel。

## 当前能力

- FastAPI 后端：上传、OCR 抽象、脱敏、字段证据召回、结构化结果、复核审计、Excel 导出。
- React 前端：病例队列、脱敏证据视图、字段置信度、低置信复核、导出入口。
- Windows 单机后台任务：上传和重新处理默认立即返回 `queued`，后端用本机线程池继续 OCR/抽取，前端自动轮询 `queued / OCR中 / 抽取中 / 已完成 / 已降级 / 失败` 状态。
- 模型层：`ModelProvider` 抽象，优先使用 OpenAI API key；没有 API key 但已完成 ChatGPT/Codex 登录时，使用本地缓存的 Codex token；都不可用时使用本地启发式 fallback，便于离线开发。
- OCR 层：默认把无文本层 PDF 渲染为页图后走 OCR；图片和扫描 PDF 必须安装 RapidOCR 或 PaddleOCR。
- OCR 优化层：`backend/app/data/system_config.yaml` 定义 `fast`、`accurate`、`fallback` 三档 OCR profile；默认 `accurate`，启用 300 DPI 渲染、基础图像预处理、页级并发、OCR 质量分层和低质量页兜底记录。
- 缓存层：按 `file_hash + OCR profile + layout profile + DPI/预处理配置` 缓存 OCR blocks 和 paragraph fragments，重复上传或重跑优先复用缓存。
- 版面与片段层：OCR 文本会转为带 `page / reading_order / section_name / block_type / source_kind / confidence` 的文档片段；默认 `chinese_inpatient_v1`，针对中国住院病历章节、编号标题和断行段落合并优化。
- 字段字典：`backend/app/data/field_dictionary.yaml` 定义全表头、规则策略、LLM 触发条件和证据预算，MVP 只自动处理 `phase: 1` 核心字段。
- 医学词典：`system_config.yaml` 内置首批病史术语、否定词和不详词，证据召回会把字段词典与医学词典合并评分。
- 抽取策略：先按 YAML 规则做关键词/正则/映射抽取；既往史/个人史章节存在且未提及相关病史时，可按配置执行科研录入用的隐式阴性 `0`，并保留 `implicit_negative` 审计说明。
- 复杂文本：规则无法解决的缺失、冲突、复杂上下文才进入 LLM。LLM prompt 使用紧凑字段规格、一份共享病例上下文和 unresolved 字段列表，减少重复 token。
- 质量闭环：后端记录每次处理运行、OCR 质量、步骤耗时、LLM 调用日志、人工批准的视觉兜底请求和轻量评测运行。

## 本地开发

Windows 一键安装：

```powershell
.\install.cmd
```

启动服务：

```powershell
.\start.cmd
```

停止服务：

```powershell
.\stop.cmd
```

`start.cmd` 会后台启动后端和前端，日志写入 `logs/backend.log` 和 `logs/frontend.log`。
脚本会使用 `.runtime/start.lock` 防止重复双击造成多个实例，并会在发现 `8000/5173` 已有本项目服务时复用现有进程。
如果双击后窗口关闭或服务无法访问，运行：

```powershell
.\diagnose.cmd
```

脚本窗口会保留，便于复制错误信息；也可以直接查看 `logs/backend.log` 和 `logs/frontend.log`。
`diagnose.cmd` 也会检查 `pypdfium2` 和 `rapidocr_onnxruntime` 是否安装，这两项决定扫描 PDF/图片能否 OCR。
`stop.cmd` 会先按 `.runtime/*.pid` 停止，再按本项目命令行和端口兜底查找后端/前端进程；因此即使看到 `no pid file`，它仍会继续查找并停止 EYES 进程。

手动启动：

```powershell
python -m pip install -r backend/requirements-dev.txt
python -m uvicorn app.main:app --app-dir backend --reload
```

另开终端：

```powershell
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`。后端默认使用 `storage/eyes.sqlite3`，适合单机试用。

可通过 `.env` 切换 OCR/版面 profile：

```env
EYES_OCR_PROFILE=accurate
EYES_LAYOUT_PROFILE=chinese_inpatient_v1
EYES_SYNC_PIPELINE=false
EYES_CASE_WORKERS=1
EYES_OCR_PAGE_WORKERS=2
EYES_LLM_WORKERS=1
EYES_LLM_CASE_CONTEXT_BUDGET=3200
```

`EYES_SYNC_PIPELINE=false` 是 Windows 单机推荐默认值：上传接口只入队，后台处理，前端自动刷新。调试单元测试或需要同步返回完整结果时，可临时设为 `true`。

## Docker Compose

```powershell
Copy-Item .env.example .env
# 在 .env 中填写 EYES_OPENAI_API_KEY
docker compose up --build
```

服务端口：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`
- OpenAPI：`http://localhost:8000/docs`

## 数据边界

默认流程不会把原始病例文件发送给在线模型。后端仅把本地 OCR 后的脱敏证据片段、字段定义和必要上下文交给模型。真实 PHI/PII 数据接入前仍需完成机构伦理、隐私、供应商和数据出境审批。

视觉兜底是单独的人工批准流程：前端“批准视觉兜底”只会记录已人工确认脱敏的页/裁剪区域请求，不会默认上传完整原始病例。

## OAuth 验证与模型登录

默认 `EYES_OAUTH_ENABLED=false`，适合单机本地试用。需要登录保护且不想手动申请 OAuth 应用时，可以启用内置 ChatGPT/Codex 登录：

```env
EYES_OAUTH_ENABLED=true
EYES_OAUTH_PROVIDER=chatgpt
EYES_OAUTH_SESSION_SECRET=replace-with-a-long-random-secret
```

该模式参考 OpenAI Codex CLI 的本地 PKCE 登录流程，会打开 ChatGPT/OpenAI 登录页，并通过 `http://localhost:1455/auth/callback` 完成本机回调。登录成功后既用于 EYES 本地会话，也可在 `EYES_OPENAI_AUTH_MODE=auto` 或 `chatgpt` 时作为在线模型通道。

EYES 也可以把同一次 ChatGPT/Codex 登录作为在线模型通道。默认模型认证策略是：

```env
EYES_OPENAI_AUTH_MODE=auto
EYES_CHATGPT_TOKEN_CACHE_PATH=./storage/auth/chatgpt_tokens.json
```

`auto` 会按顺序选择：

1. `EYES_OPENAI_API_KEY`：官方 API key 通道，最稳定、最容易轮换。
2. ChatGPT/Codex 登录 token：登录成功后写入 `storage/auth/chatgpt_tokens.json`，后续模型调用会自动刷新 token。
3. 本地规则 fallback：没有在线凭据时仍可 OCR、脱敏、规则抽取和人工复核。

`storage/auth/chatgpt_tokens.json` 含 access/refresh token，按密码处理：不要提交到 Git、不要发给他人、不要贴到 issue 或聊天记录。OpenAI Codex 文档也说明 Codex 会把登录信息缓存在本地文件或系统凭据库，并在使用中刷新 ChatGPT 会话 token；同时 API key 仍是自动化场景的推荐默认方式。

可手动固定模型认证模式：

```env
EYES_OPENAI_AUTH_MODE=api_key   # 只用 EYES_OPENAI_API_KEY
EYES_OPENAI_AUTH_MODE=chatgpt   # 只用 ChatGPT/Codex 登录 token
EYES_OPENAI_AUTH_MODE=disabled  # 禁用在线模型，只用本地规则 fallback
```

如果要接入医院或机构统一身份认证，把 provider 改为 `oidc` 并配置 OAuth2/OIDC Provider：

```env
EYES_OAUTH_ENABLED=true
EYES_OAUTH_PROVIDER=oidc
EYES_OAUTH_CLIENT_ID=your-client-id
EYES_OAUTH_CLIENT_SECRET=your-client-secret
EYES_OAUTH_AUTHORIZATION_URL=https://provider.example.com/oauth2/v2.0/authorize
EYES_OAUTH_TOKEN_URL=https://provider.example.com/oauth2/v2.0/token
EYES_OAUTH_USERINFO_URL=https://provider.example.com/oidc/userinfo
EYES_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/api/auth/callback
EYES_OAUTH_SCOPES=openid email profile
EYES_OAUTH_ALLOWED_EMAIL_DOMAINS=example.com
EYES_OAUTH_SESSION_SECRET=replace-with-a-long-random-secret
```

启用后，病例列表、上传、复核和导出接口会要求登录；`/api/health` 和 `/api/auth/*` 保持公开。
前端会在登录页、顶部栏和左侧状态区显示 OAuth 登录状态；未启用 OAuth 时显示本地模式。
如果 `EYES_OAUTH_PROVIDER=oidc` 但缺少 `EYES_OAUTH_CLIENT_ID`、授权地址、token 地址或 userinfo 地址，登录页会显示缺失项并禁用登录按钮；`diagnose.cmd` 也会列出缺失配置。

## 字段与规则配置

字段不写死在代码中，配置入口是 `backend/app/data/field_dictionary.yaml`。常用项：

- `phase`: `1` 会进入 MVP 自动抽取，`2` 暂留字段位。
- `rule_strategy.kind`: 支持 `regex`、`history`、`mapping` 和基础 `keyword`。
- `llm.enabled`: 是否允许该字段在规则失败时进入在线模型。
- `llm.trigger_statuses`: 触发模型的状态，如 `missing`、`conflict`、`low_confidence`、`needs_review`。
- `llm.evidence_budget`: 该字段最多发送给模型的脱敏证据字符预算。
- `max_evidence_items` / `evidence_window_chars`: 控制候选证据条数和单条窗口，避免整页 OCR 文本直接进模型。
- OCR 后处理会把同一行里的多个键值字段切开，例如 `性别：男 年龄：66岁 出院情况：好转出院。` 会拆成独立证据块，提高规则召回和 LLM 上下文质量。
- 病史类隐式阴性只在 `既往史` 或明确病史章节存在、OCR 质量非 poor、且没有“不详/记不清/否认不清”等表达时触发；吸烟/饮酒只在 `个人史/生活史` 存在时触发。

## 诊断与评测接口

- `GET /api/cases/{case_id}/diagnostics`: 查看 OCR 质量、章节片段、处理运行、缓存命中、LLM 调用和视觉兜底请求。
- `POST /api/cases/{case_id}/reprocess`: 按当前配置重新处理病例，并新增一次处理运行记录；默认进入后台队列。
- `POST /api/cases/{case_id}/vision-fallback-requests`: 记录人工确认脱敏后的视觉兜底请求。
- `POST /api/evals/runs`: 按传入金标准字段运行轻量评测，返回准确率和 unknown 率。

## 测试

```powershell
python -m pytest backend/tests
cd frontend
npm run build
```
