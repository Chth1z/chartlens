# EYEX

病例图片/PDF/文本结构化录入 MVP。

核心路线固定为：本地 OCR/版面解析 -> 脱敏 DocumentIR -> 字段组证据召回 -> 在线 LLM 结构化抽取 -> 规则护栏 -> 人工复核 -> 可追溯导出。

## 运行

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
cd frontend
npm install
cd ..
```

启动后端：

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

启动前端：

```powershell
cd frontend
npm run dev
```

访问 `http://localhost:5173`。

## 配置

配置目录固定在项目根目录 `config/`，运行态文件固定在 `var/`：

- `document_profiles`: 医院、文档类型、章节别名、脱敏标签。
- `extraction_schemas`: 字段组、字段、枚举、来源优先级、抽取模式。
- `export_templates`: 表头、列顺序、unknown 导出映射。
- `evaluation_profiles`: 可配置 gold cases、字段标签、质量阈值和 token 预算，用于不同领域的通用评测。
- `model_profiles`: OpenAI Responses API、DeepSeek、OpenAI-compatible Chat Completions 参数。
- `validation_rules`: 核心护栏说明。

默认 SQLite、上传文件、OCR 缓存、provider 设置和本机密钥缓存都写入 `var/storage/`。本机 `.env` 也应使用 `EYEX_DATABASE_URL=sqlite:///./var/storage/eyex.sqlite3`；旧 `storage/` 位置不再作为运行态入口保留。

`EYEX_DOCUMENT_PROFILE` 可切换文档领域 profile。profile 除了章节别名，也可以声明文档类型映射、脱敏正则、在线模型外发门禁、OCR 视觉解析提示词和抽取规则提示词；新增领域应优先扩展 `config/document_profiles/*.yaml` 和 schema/export 配置，而不是在 pipeline/provider/OCR 代码中写死场景逻辑。

配置发现接口：

- `GET /api/config/catalog`：列出当前激活配置和所有可用 profile/schema/template/model/OCR/eval 配置。
- `GET /api/config/{kind}/{config_id}`：读取单个 YAML 配置及解析后的 JSON；`kind` 支持 `document_profiles`、`extraction_schemas`、`export_templates`、`model_profiles`、`ocr_profiles`、`evaluation_profiles`、`validation_rules`。

领域差异通过 `config/document_profiles/*.yaml` + `config/extraction_schemas/*.yaml` 收敛，由 `backend/app/services/domain_profile.py` 和 `backend/app/services/layout_normalizer.py` 读取执行：文档类型映射、抽取系统提示词、抽取规则、脱敏正则、layout 规范化、字段证据政策都在 YAML 里写。新增领域（医疗、发票、合同等）应优先扩展这些 YAML 文件；公共 pipeline 不接受场景分支。曾经设想过的运行时 `domain_plugins` 注册机制已废弃（见 `docs/DECISIONS.md`），governance scan 会拦截相关命名。

`unknown` 是内部唯一“不详/未提及”表示；导出模板决定映射为空值或 `9`。复杂字段不得把未提及推断为 `0`。

核心业务契约：

- 非 `unknown` 字段必须有真实 `evidence_span` 和 `evidence_block_id`，且 span 必须逐字存在于脱敏 DocumentIR block。
- 在线模型链路失败时，复杂字段保持 `unknown + review_required`，不会用本地规则硬猜。
- 人工复核确认非 `unknown` 时同样校验证据；导出主表只输出自动接受或复核确认的最终值，Evidence Audit 保留候选、证据、风险和来源。
- 字段组抽取默认发送字段级 EvidencePack，不再发送重复的大段 group context；无证据且字段配置允许时会跳过 LLM 并返回 `unknown`。
- LLM 结果按 schema/prompt/model/evidence hash 缓存，重复证据包不会重复消耗在线模型 token。
- OCR 会记录引擎候选质量摘要和有限候选 block；低质量普通 OCR 会按 profile 追加疑难页路由，便于复核和后续质量分析。
- 批量评测接口 `/api/evals/batch` 和 profile 评测接口 `/api/evals/profiles/{profile_id}/run` 用于跟踪自动接受 precision、unknown 误填率、证据覆盖率和 token 成本。

默认启动脚本只把前端和后端绑定到 `127.0.0.1`。如果确实需要局域网访问，需要同时设置 `EYEX_ALLOW_REMOTE_ACCESS=true` 和 `EYEX_LOCAL_API_TOKEN`，并在请求中携带 `Authorization: Bearer <token>`；否则远程 Origin/客户端会被拒绝。

## OCR / 智能文档解析

OCR 层默认采用 AMD GPU 保护的固定混合路线：

```text
原生 PDF 文本 -> 本地 OCR sidecar -> PP-OCRv5 server ONNX + DirectML -> 可选远端 PaddleOCR-VL AMD/ROCm -> DocumentIR 合并
```

相关环境变量：

- `EYEX_OCR_STRATEGY=intelligent`
- `EYEX_OCR_PROFILE=windows_radeon_balanced`：OCR 引擎顺序由 `config/ocr_profiles/*.yaml` 控制。
- `EYEX_OCR_DOCUMENT_AI_URL=http://127.0.0.1:8765/extract`：本地 OCR sidecar。
- `EYEX_OCR_PADDLEOCR_VL_URL=`：可选的远端 AMD/ROCm PaddleOCR-VL sidecar；支持 EYEX `/extract` 或官方 PaddleOCR-VL `/layout-parsing`；未配置时不会在本机 CPU 上运行 PaddleOCR-VL。
- `EYEX_OCR_ACCELERATOR=directml` 和 `EYEX_OCR_DIRECTML_MODEL_DIR=var\models\ppocrv5-directml-server`：本机 PP-OCRv5 DirectML 路线。
- `EYEX_OPENAI_API_KEY=` 和 `EYEX_OCR_OPENAI_MODEL=`：可选，使用 OpenAI Responses 视觉文件输入作为高难度兜底。

旧 CPU RapidOCR 兜底已移除。DirectML 不可用或运行时被 AMD 驱动超时禁用时，病例会进入 `failed`，前端处理摘要会显示缺失原因；不会静默退回本机 CPU 重模型。

重型 OCR 依赖不放进主后端依赖。OCR sidecar 使用独立 `.venv-ocr`，安装脚本无参执行即可自动检测显卡、准备项目内模型目录并启动 sidecar：

```powershell
.\install-ocr.cmd
```

安装脚本会创建 `.venv-ocr`，在 AMD Radeon Windows 上准备 PP-OCRv5 server ONNX DirectML 模型，并自动探测/尝试准备官方 AMD/ROCm PaddleOCR-VL Docker sidecar。若 Docker/ROCm sidecar 可用，会写入 `EYEX_OCR_PADDLEOCR_VL_URL=http://127.0.0.1:8080/layout-parsing`；否则继续使用本机 DirectML PP-OCRv5，不会退回本机 CPU VL。基础写入项：

```text
EYEX_OCR_DOCUMENT_AI_URL=http://127.0.0.1:8765/extract
EYEX_OCR_PROFILE=windows_radeon_balanced
EYEX_OCR_ACCELERATOR=directml
```

如果 `.env` 已有 `EYEX_OCR_PADDLEOCR_VL_URL=http://host:8080/layout-parsing` 或 `http://host:8765/extract`，无参安装会自动接入远端 ROCm PaddleOCR-VL。`scripts\probe-amd-ocr.ps1` 会显示 `paddleocr_vl_rocm_sidecar` 状态。所有模型、缓存、compose 文件和临时目录都固定在项目内 `var/`。

本机 DirectML 合成 OCR 评测如果要绕过当前运行中的 sidecar，只在当前
PowerShell 会话清空 URL 后运行：

```powershell
$env:EYEX_OCR_DOCUMENT_AI_URL=''
.\scripts\run-ocr-eval.ps1 -ProfileId synthetic_medical_directml
```

如果评测或诊断提示 sidecar 过期，使用现有根脚本安全重启，不要手动杀进程：

```powershell
.\stop.cmd
.\start.cmd
```

如果已经接入 DeepSeek API，可以在 `.env` 设置：

```text
EYEX_MODEL_PROFILE=deepseek_v4_flash
EYEX_DEEPSEEK_API_KEY=sk-...
```

DeepSeek 用于 OCR 后的结构化字段抽取；当前官方 DeepSeek API 是 Chat Completions 文本接口，不能替代 PDF/图片视觉 OCR。

详细选型和评测切片见 `docs/OCR_UPGRADE.md`。

## 模型供应商

前端直接复用旧项目 `D:\Github\EYES\frontend` 的成熟病例队列、证据面板、复核和导出体验。设置页提供类似 Alma/OpenClaw 的供应商管理界面：

- 左侧选择供应商，右侧填写 API key、Base URL 和 API 协议。Base URL、协议、模型列表等非密钥配置保存到本机 `var/storage/provider_settings.json`；API key 默认只进入当前后端进程内存，不再明文落盘，重启后请使用 `.env` 或重新输入。
- 点击 `Fetch` 拉取 provider 模型列表；后端会保留接口返回的全部模型。预置模型只作为推荐提示，不会在未验证前伪装成可用模型。如果 provider 不支持模型列表接口，可以手动添加 Model ID。
- 中转 API 使用 OpenAI provider 的 `OpenAI-compatible Chat` 模式，或使用 `API 中转 / Custom`；模型拉取会尝试 `base/models` 和 `base/v1/models`，推理调用若根地址返回 404/405 会自动再试 `base/v1`。
- 点击模型行即可将该模型设为当前抽取模型。
- 不同供应商会暴露对应参数：OpenAI Responses 支持 reasoning effort，OpenAI-compatible/Anthropic/Gemini 支持温度和输出长度。
- API 响应只返回 key 掩码，不回传明文 key。

已适配的供应商包括：

- 原生：OpenAI Responses、Anthropic Messages、Google Gemini。
- OpenAI-compatible：DeepSeek、OpenRouter、Moonshot、Qwen/DashScope、Z.AI/GLM、Azure OpenAI、Custom Provider。
- 本地/自托管：Ollama。

模型接入方式参考 OpenClaw/Alma：使用 `provider/model` 引用，例如 `openai/gpt-5.4`、`deepseek/deepseek-v4-flash`、`openrouter/auto`；每个 provider 在 `config/model_providers/*.yaml` 定义 base URL、API 模式、auth env vars、context 元数据和 fallback chain。默认 profile 链路是：

```text
openai/gpt-5.4 -> deepseek/deepseek-v4-pro -> deepseek/deepseek-v4-flash -> local/conservative-local
```

API key 读取也按 OpenClaw 思路支持多个来源：当前进程内存、`OPENCLAW_LIVE_<PROVIDER>_KEY`、profile 中声明的 env vars、`<PROVIDER>_API_KEYS`、`<PROVIDER>_API_KEY`、`<PROVIDER>_API_KEY_1..9`。多个 key 可用逗号或分号分隔；发生 rate limit/timeout 时会在同一 provider 内轮换 key，再进入下一个 fallback 模型。若必须恢复旧的明文落盘行为，需要显式设置 `EYEX_ALLOW_PLAINTEXT_PROVIDER_KEYS=true`，不建议在含真实病例或真实密钥的环境使用。

在线模型不可用时，系统不会用规则硬猜复杂字段；复杂字段返回 `unknown + review_required`。如果后续引入成熟开源 agent/provider 代码，应放在独立 adapter 目录并保留原始 LICENSE、NOTICE 和版权声明。开源 agent/provider 对标与改造优先级见 `docs/LLM_PROVIDER_ALIGNMENT.md`。

## 验证

```powershell
.\.venv\Scripts\python -m pytest backend\tests
cd frontend
npm test
npm run build
cd ..
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1
```
