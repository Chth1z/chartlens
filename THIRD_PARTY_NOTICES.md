# Third-Party Notices

This project currently does not vendor source files from mature agent frameworks. LLM access is implemented through local provider adapters and package-manager dependencies.

The model routing design is adapted from OpenClaw's documented model pattern and MIT-licensed source structure: `provider/model` refs, provider catalogs, auth profiles/order, cooldown-aware credential rotation, primary model plus fallbacks, and generated `models.json` style catalog separation. The provider settings UI also follows the general provider-management pattern shown in the user's Alma screenshot. No OpenClaw or Alma source files are copied into this repository.

Reference:

- OpenClaw: https://github.com/openclaw/openclaw
- OpenClaw license observed in upstream `LICENSE`: MIT
- Upstream copyright notice: Copyright (c) 2025 Peter Steinberger

Additional provider-layer research references are documented in
`docs/LLM_PROVIDER_ALIGNMENT.md`. The current implementation borrows patterns
from Cline, Continue, Dify, LiteLLM, and Open WebUI, but does not copy source
files from those projects.

If future work copies or adapts source code from an open-source agent project, keep it in a clearly named adapter directory and add:

- the upstream project name and repository URL;
- the exact license text;
- upstream copyright notices;
- a short note describing local modifications.

Do not merge third-party source into the core extraction pipeline without preserving these notices.
