# LLM Provider 对标与改造方案

> Status: 历史背景文档。本文写于 2026-04-30，记录 EYEX 当时如何对照 OpenClaw / Cline / Continue / LiteLLM 等开源项目梳理 provider 层。其中"建议架构"和"已落地的第一批改动"两节，部分已被 2026-05-18 的 `docs/LLM_PROVIDER_REFACTOR.md`（E1-011 三个 phase）取代——例如建议中的 `services/llm_gateway/`、`services/credential_store/`、`services/model_router.py` 目录命名最终落到了 `services/llm_provider/`，并通过 `services/llm_provider/registry.py` 完成多 provider dispatch。今天读 EYEX 的 LLM provider 行为时，应以 `docs/LLM_PROVIDER_REFACTOR.md`、`docs/DECISIONS.md` 2026-05-18 条目和 `AGENTS.md` "Architecture Boundaries" 为准；本文保留下来用于回顾选型动机。

调研日期：2026-04-30。

## 目标

EYEX 的在线大模型接入应向成熟开源 agent 的通用 provider 层对齐，避免在 API key、OAuth、模型列表、fallback、限流、成本和日志上重复造轮子。

本轮结论：provider 层按 OpenClaw 的三层思路收敛：Provider catalog 描述协议/端点/能力，Auth profile/环境变量只描述凭据来源，Model binding 只描述 `provider/model`、参数和 fallback。业务抽取管线不再新增 provider 特例。

## 可借鉴项目

| 项目 | 许可证/复制策略 | 可借鉴部分 | 不建议直接复制部分 |
| --- | --- | --- | --- |
| [OpenClaw](https://docs.openclaw.ai/models) | 开源 agent，可借鉴交互和配置概念；复制源码前需逐项核对仓库 LICENSE | `/model`/models CLI 将 provider、model、auth profile 分离；支持 OAuth/API key、SecretRef 和 provider-scoped selections | 其 agent/gateway 运行时与 EYEX 医疗抽取链路不同，不应整体照搬权限模型 |
| [Cline](https://github.com/cline/cline) | Apache-2.0，可复制但需保留 NOTICE/License | Provider-agnostic 体验：OAuth/BYOK/local 三种入口；密钥放系统 credential store；provider 类型、模型能力、设置 UI 分层 | IDE/VS Code SecretStorage 代码无法直接搬到 FastAPI，需要改写为 OS keychain/DPAPI/企业密钥服务 |
| [Continue](https://github.com/continuedev/continue) | Apache-2.0，可复制但需保留 NOTICE/License | `config.yaml` 形式的模型、能力、角色、header/requestOptions 配置；适合把 EYEX 的 hardcoded catalog 下沉为 YAML | 面向代码 agent 的 roles/tools 语义，不能照搬为医疗抽取策略 |
| [Dify](https://github.com/langgenius/dify) | 修改版 Apache-2.0，有多租户/前端品牌限制；建议只借鉴架构概念 | Provider plugin：provider YAML + credential schema + `validate_provider_credentials`；预置模型和自定义模型并存 | 不建议复制源码到 EYEX，许可和多租户限制会增加合规成本 |
| [LiteLLM](https://github.com/BerriAI/litellm) | MIT；enterprise 目录另算 | Router、fallback、retry policy、cost tracking、load balancing、统一 OpenAI-compatible gateway | 2026-03-24 官方 issue 记录 PyPI 供应链事故；医疗主链路不建议直接无锁版本引入，若使用应作为 sidecar、锁版本/镜像 digest、隔离密钥 |
| [Open WebUI](https://github.com/open-webui/open-webui) | Open WebUI License 带品牌限制；只借概念 | Protocol-oriented design：优先标准协议，非标准 provider 走 proxy/pipe；模型列表失败时允许手动 allowlist | 不建议复制源码或 UI；许可证限制不适合作为 EYEX 基础代码来源 |

## 对 EYEX 的差距判断

当前实现已经做对的部分：

- `ModelProfile` 已包含 provider、model、base_url、auth_env_vars、fallbacks、context/cost/compat 等关键字段。
- 前端已有 provider 设置面板，支持 API key、Base URL、Fetch models、手动添加模型。
- API key 默认不明文落盘，Windows 下使用 DPAPI 存储。
- 抽取层已经有 OpenAI Responses、OpenAI-compatible、Anthropic、Gemini、本地 conservative fallback 的统一入口。

仍需对齐成熟项目的部分：

- Provider catalog 已迁移到 `config/model_providers/*.yaml`，接近 OpenClaw/Dify/Continue 的配置化模式；Python 只保留 schema 和 fallback 内置清单。
- `enabled` 目前主要是 UI 状态，没有进入 fallback/routing 选择；应有显式 fallback chain 编辑和启用状态过滤。
- Save provider 时不做 live credential validation；应提供 Dify 风格的 `validate_provider_credentials`，同时保留 Open WebUI 风格的“模型列表失败但可手动模型 ID”路径。
- 错误处理必须默认脱敏，尤其是 Gemini 这类 query 参数 key、Bearer token、OpenAI `sk-...`。
- 多 key 轮换应有短期 cooldown，避免同一个限流 key 在每个字段组反复先失败。
- OAuth 要拆成两类：应用登录 OAuth/OIDC 和模型供应商 OAuth。医疗场景优先做企业 OIDC/SSO；模型调用优先 API key 或企业网关，不建议把个人 ChatGPT/Cline 类 OAuth 当生产模型认证。
- 需要 provider 合同测试：模型列表、最小 JSON 输出、超时/429 fallback、401/403 错误文案、无 `/models` provider 的手动模型路径。

## 建议架构

1. `model_providers/*.yaml`
   - 只放 provider 元数据：label、api 协议、default_base_url、auth schema、model discovery、已知模型、能力、默认 fallback。
   - 从 Cline/Continue 借 `capabilities` 概念：`json_schema`、`json_object`、`vision`、`prompt_cache`、`reasoning_effort`。

2. `services/llm_gateway/`
   - 每种协议一个 adapter：OpenAI Responses、OpenAI Chat Completions-compatible、Anthropic Messages、Gemini generateContent。
   - 不在业务 pipeline 中出现 provider 特例；业务只调用 `extract_group()`.

3. `services/credential_store/`
   - 本地单机：Windows DPAPI、macOS Keychain、Linux Secret Service/libsecret；不可用时仅内存或显式 plaintext opt-in。
   - 企业部署：改接 Vault/KMS/云 Secret Manager。

4. `services/model_router.py`
   - 输入：目标能力、字段组、隐私等级、预算、fallback policy。
   - 输出：有序 model attempts。
   - 支持 key cooldown、provider cooldown、最大重试、不可重试错误分类。

5. `diagnostics/model_calls`
   - 每次调用记录 provider/model、route、attempt、latency、tokens、fallback reason、redacted error。
   - 不记录 prompt 明文和密钥；病例证据仍按现有脱敏 DocumentIR 记录。

## 已落地的第一批改动

- 新增统一错误脱敏工具，覆盖 `sk-...`、Bearer token、query 参数中的 `key/token/access_token/refresh_token`。
- `fetch_provider_models()` 不再把原始异常写入 `provider_settings.json` 或前端响应。
- 在线模型调用新增短期 API key cooldown：同一 key 出现 rate limit/timeout 后，后续字段组会优先尝试同 provider 的其他 key。
- Provider 设置页改为 OpenClaw/Open WebUI 风格的统一入口：先选供应商，再保存凭据/Base URL/API 协议，再测试拉取模型；未拉取前只显示“推荐模型”，不再把预置模型当成已验证可启用模型。
- OpenAI provider 支持 `OpenAI Responses` 与 `OpenAI-compatible Chat` 两种协议，便于官方 API 和中转 API 在同一入口切换；Responses 支持 `reasoning.effort`，Chat/其他主流 provider 暴露温度和输出长度等通用参数。
- 默认 catalog 收敛到主流国内外供应商：OpenAI、DeepSeek、Anthropic、Google Gemini、OpenRouter、Moonshot、Qwen/DashScope、Z.AI/GLM、Azure OpenAI、Ollama、Custom Provider。
- `/models` 发现会保留所有 provider 返回的模型，并兼容字符串数组、`id`、`model`、`model_id` 等常见返回格式；对中转 API 会尝试根地址 `/models` 和 `/v1/models` 两种常见路径。
- OpenAI-compatible 推理调用也补了路径兜底：根地址 `/chat/completions` 返回 404/405 时，会自动再试 `base/v1`，减少“能拉模型但不能调用”的中转路径错配。

## 后续优先级

P0：

- 把 provider 错误脱敏、key cooldown 和安全测试保留为回归基线。
- 增加 provider contract tests：无效 key、429、timeout、无 `/models`、JSON 非法输出。
- 不再扩大硬编码 provider 列表；新增供应商必须先进入 YAML catalog，并补充 provider contract tests。

P1：

- 为 provider 设置增加“验证连接”和“手动模型 ID 可用性说明”，区分 credential invalid 和 model discovery unsupported。
- 将 `enabled` 纳入 routing，支持显式 fallback chain。

P2：

- 增加企业 OIDC/SSO 登录；模型供应商 OAuth 只作为可插拔实验 adapter，不进入默认医疗链路。
- 如果需要统一网关，引入 LiteLLM 只作为 sidecar，固定镜像 digest，并给 sidecar 单独的最小权限密钥。

## 参考源

- Cline 授权与模型选择文档：https://docs.cline.bot/getting-started/authorizing-with-cline
- Cline 仓库与许可证：https://github.com/cline/cline
- Continue config reference：https://docs.continue.dev/reference
- Continue 仓库与许可证：https://github.com/continuedev/continue
- Dify model provider plugin 文档：https://docs.dify.ai/en/develop-plugin/dev-guides-and-walkthroughs/creating-new-model-provider
- Dify 许可证：https://github.com/langgenius/dify/blob/main/LICENSE
- LiteLLM routing 文档：https://docs.litellm.ai/docs/routing
- LiteLLM 许可证：https://github.com/BerriAI/litellm/blob/main/LICENSE
- LiteLLM 2026-03 PyPI compromise issue：https://github.com/BerriAI/litellm/issues/24518
- Open WebUI OpenAI-compatible provider 文档：https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/
- Open WebUI 许可证：https://github.com/open-webui/open-webui/blob/main/LICENSE
- OpenClaw models 文档：https://docs.openclaw.ai/models
- OpenClaw OAuth 文档：https://docs.openclaw.ai/concepts/oauth
- OpenAI reasoning effort 文档：https://platform.openai.com/docs/guides/reasoning#reasoning-effort
