import { AlertTriangle, FileSearch, Loader2, LogIn } from "lucide-react";
import { loginUrl } from "../../shared/api/client";
import type { AuthStatus } from "../../shared/types/api";

interface LoginRequiredProps {
  auth: AuthStatus;
  oauthConfigured: boolean;
  missingOauthConfig: string[];
  oauthWarnings: string[];
}

export function AuthLoading() {
  return (
    <main className="login-shell">
      <section className="login-panel">
        <div className="brand-mark"><Loader2 size={22} className="spin" /></div>
        <h1>ChartLens</h1>
        <p>正在检查本地服务和登录状态。</p>
      </section>
    </main>
  );
}

export function LoginRequired({ auth, oauthConfigured, missingOauthConfig, oauthWarnings }: LoginRequiredProps) {
  return (
    <main className="login-shell">
      <section className="login-panel">
        <div className="brand-mark"><FileSearch size={22} /></div>
        <h1>ChartLens</h1>
        <p>
          {oauthConfigured
            ? auth.auth_provider === "chatgpt"
              ? "病例结构化抽取系统已启用 ChatGPT 登录，请在浏览器中完成验证。"
              : "病例结构化抽取系统已启用 OAuth 验证，请登录后继续。"
            : "OAuth 已启用，但后端登录参数尚未配置完整。"}
        </p>
        {!oauthConfigured && (
          <div className="config-alert">
            <strong>缺少配置</strong>
            {missingOauthConfig.map((item) => <code key={item}>{item}</code>)}
            <small>补齐 `.env` 后运行 `stop.cmd` 和 `start.cmd`，或将 `CHARTLENS_OAUTH_ENABLED=false` 切回本地模式。</small>
          </div>
        )}
        {oauthWarnings.length > 0 && (
          <div className="config-alert warning">
            <strong>配置提醒</strong>
            {oauthWarnings.map((item) => <small key={item}>{item}</small>)}
          </div>
        )}
        {oauthConfigured ? (
          <a className="icon-button primary full" href={loginUrl("/")}>
            <LogIn size={16} /> {auth.auth_provider === "chatgpt" ? "使用 ChatGPT 登录" : "使用 OAuth 登录"}
          </a>
        ) : (
          <button className="icon-button primary full" disabled type="button">
            <AlertTriangle size={16} /> OAuth 配置不完整
          </button>
        )}
      </section>
    </main>
  );
}
