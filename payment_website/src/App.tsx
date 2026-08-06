import { CheckCircle2, CreditCard, KeyRound, Laptop, Loader2, LogOut, Settings, ShieldCheck, Sparkles, UserRound } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, formatMoney, getStoredToken, loadRazorpay, setStoredToken } from "./api";
import type { ApiSetup, BillingPlan, Entitlement, User } from "./types";

type AuthMode = "login" | "signup";
type Page = "plans" | "settings" | "profile";

const keyProviders = [
  { provider: "gemini", label: "Google Gemini", model: "gemini-2.5-flash" },
  { provider: "groq", label: "Groq", model: "openai/gpt-oss-20b" },
  { provider: "openai", label: "OpenAI", model: "" },
  { provider: "anthropic", label: "Anthropic", model: "claude-3-5-sonnet-latest" },
  { provider: "pexels", label: "Pexels", model: "" },
  { provider: "pixabay", label: "Pixabay", model: "" },
  { provider: "unsplash", label: "Unsplash", model: "" },
  { provider: "google_tts", label: "Google TTS Credentials Path", model: "" }
];

const aiProviders = keyProviders.slice(0, 4);
const otherProviders = keyProviders.slice(4);
const modelOptions: Record<string, string[]> = {
  gemini: ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash"],
  groq: ["openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
  openai: ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
  anthropic: ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"]
};

export function App() {
  const [plans, setPlans] = useState<BillingPlan[]>([]);
  const [token, setToken] = useState(getStoredToken());
  const [user, setUser] = useState<User | null>(null);
  const [entitlement, setEntitlement] = useState<Entitlement | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [page, setPage] = useState<Page>("plans");
  const [apiSetup, setApiSetup] = useState<ApiSetup | null>(null);

  const activePlan = useMemo(() => plans.find((plan) => plan.code === entitlement?.plan_code), [entitlement, plans]);
  const showAuth = !user;
  const showPlans = !user || !entitlement?.active;

  useEffect(() => {
    api.plans().then(setPlans).catch((err) => setError(err instanceof Error ? err.message : "Could not load plans."));
  }, []);

  useEffect(() => {
    if (!token) return;
    refreshAccount(token).catch((err) => {
      setStoredToken("");
      setToken("");
      setUser(null);
      setEntitlement(null);
      setError(err instanceof Error ? err.message : "Session expired.");
    });
  }, [token]);

  async function refreshAccount(nextToken = token) {
    const [me, access, keys] = await Promise.all([api.me(nextToken), api.entitlement(nextToken), api.apiKeys(nextToken)]);
    setUser(me);
    setEntitlement(access);
    setApiSetup(keys);
    setEmail(me.email);
    setDisplayName(me.display_name || "");
  }

  async function submitAuth(event: FormEvent) {
    event.preventDefault();
    setBusy("auth");
    setError("");
    setMessage("");
    try {
      const result =
        authMode === "signup"
          ? await api.signup({ email, password, display_name: displayName })
          : await api.login({ email, password });
      setStoredToken(result.access_token);
      setToken(result.access_token);
      await refreshAccount(result.access_token);
      setMessage("Signed in. Choose a plan to unlock the desktop app.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setBusy("");
    }
  }

  async function pay(plan: BillingPlan) {
    if (!token) {
      setError("Create an account or log in before checkout.");
      return;
    }
    setBusy(plan.code);
    setError("");
    setMessage("");
    try {
      await loadRazorpay();
      const checkout = await api.checkout(token, plan.code);
      const options: Record<string, unknown> = {
        key: checkout.key_id,
        name: "Modular Shorts Studio",
        description: checkout.label,
        method: {
          upi: true,
          card: true,
          netbanking: true,
          wallet: true
        },
        config: {
          display: {
            blocks: {
              upi: {
                name: "Pay with UPI",
                instruments: [{ method: "upi" }]
              }
            },
            sequence: ["block.upi"],
            preferences: {
              show_default_blocks: true
            }
          }
        },
        prefill: checkout.prefill,
        notes: { checkout_id: checkout.checkout_id, plan_code: checkout.plan_code },
        theme: { color: "#1f6f68" },
        handler: async (response: Record<string, string>) => {
          setBusy("verify");
          try {
            const access = await api.verify(token, {
              checkout_id: checkout.checkout_id,
              razorpay_payment_id: response.razorpay_payment_id || "",
              razorpay_signature: response.razorpay_signature || "",
              razorpay_order_id: response.razorpay_order_id || checkout.order_id || "",
              razorpay_subscription_id: response.razorpay_subscription_id || checkout.subscription_id || ""
            });
            setEntitlement(access);
            setMessage("Payment verified. You can now log in from the desktop app with this account.");
          } catch (err) {
            setError(err instanceof Error ? err.message : "Payment verification failed.");
          } finally {
            setBusy("");
          }
        },
        modal: {
          ondismiss: () => setBusy("")
        }
      };
      if (checkout.kind === "subscription") {
        options.subscription_id = checkout.subscription_id;
      } else {
        options.order_id = checkout.order_id;
        options.amount = checkout.amount_paise;
        options.currency = checkout.currency;
      }
      new window.Razorpay!(options).open();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Checkout could not start.");
      setBusy("");
    }
  }

  function logout() {
    setStoredToken("");
    setToken("");
    setUser(null);
    setEntitlement(null);
    setPassword("");
    setMessage("Signed out.");
  }

  return (
    <main className="page">
      <section className="topbar">
        <div className="brand">
          <div className="brandMark"><Sparkles size={18} /></div>
          <div>
            <strong>Modular Shorts Studio</strong>
            <span>Paid desktop access</span>
          </div>
        </div>
        {user ? (
          <div className="navButtons">
            <button className={page === "plans" ? "ghostButton active" : "ghostButton"} onClick={() => setPage("plans")}><CreditCard size={16} /> Plans</button>
            <button className={page === "settings" ? "ghostButton active" : "ghostButton"} onClick={() => setPage("settings")}><Settings size={16} /> Settings</button>
            <button className={page === "profile" ? "ghostButton active" : "ghostButton"} onClick={() => setPage("profile")}><UserRound size={16} /> Profile</button>
            <button className="ghostButton" onClick={logout}><LogOut size={16} /> Sign out</button>
          </div>
        ) : null}
      </section>

      {page === "plans" ? <section className={showAuth ? "layout" : "layout noAuth"}>
        <div className="intro">
          <div className="previewPanel" aria-hidden="true">
            <div className="previewHeader">
              <span />
              <span />
              <span />
            </div>
            <div className="previewChat">
              <div className="bubble userBubble">school hallway chase</div>
              <div className="styleGrid">
                <div>Cinematic Slow Build</div>
                <div>Fast Conflict Cut</div>
                <div>Evidence Reveal</div>
              </div>
              <div className="bubble appBubble">Pick one style, then keep chatting.</div>
            </div>
          </div>
          <h1>Unlock the desktop video generation app</h1>
          <p>
            {entitlement?.active
              ? "Your desktop access is active. Manage your profile and API keys from the top navigation."
              : "Pay here, then log in with the same account inside the Electron app. Active users get the genre picker, 3 generated style samples, and the chat workflow for follow-up edits."}
          </p>
          <div className="statusStrip">
            <ShieldCheck size={18} />
            <span>{entitlement?.active ? `Active ${activePlan?.label || "access"}` : "Payment required before desktop access"}</span>
          </div>
        </div>

        {showAuth ? <aside className="authCard">
          <div className="tabs">
            <button className={authMode === "login" ? "active" : ""} onClick={() => setAuthMode("login")}>Login</button>
            <button className={authMode === "signup" ? "active" : ""} onClick={() => setAuthMode("signup")}>Sign up</button>
          </div>
          <form onSubmit={submitAuth}>
            {authMode === "signup" ? (
              <label>
                Name
                <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Gaurav" />
              </label>
            ) : null}
            <label>
              Email
              <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
            </label>
            <label>
              Password
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={authMode === "signup" ? 8 : 1} required />
            </label>
            <button className="primaryButton" disabled={busy === "auth"}>
              {busy === "auth" ? <Loader2 className="spin" size={16} /> : <KeyRound size={16} />}
              {authMode === "signup" ? "Create account" : "Log in"}
            </button>
          </form>
        </aside> : null}
      </section> : null}

      {(error || message) ? (
        <div className={error ? "notice error" : "notice success"}>{error || message}</div>
      ) : null}

      {page === "plans" && showPlans ? <section className="plans" aria-label="Pricing plans">
        {plans.map((plan) => (
          <article className={`planCard ${plan.code === "yearly" ? "featured" : ""}`} key={plan.code}>
            <div className="planIcon">{plan.kind === "subscription" ? <CreditCard size={22} /> : <Laptop size={22} />}</div>
            <h2>{plan.label}</h2>
            <p>{plan.kind === "subscription" ? `Recurring ${plan.interval} billing through Razorpay.` : "One payment for ongoing local access."}</p>
            <strong className="price">{formatMoney(plan.amount_paise, plan.currency)}</strong>
            <button className="primaryButton" disabled={!plan.configured || busy === plan.code || busy === "verify"} onClick={() => void pay(plan)}>
              {busy === plan.code || busy === "verify" ? <Loader2 className="spin" size={16} /> : <CreditCard size={16} />}
              {plan.configured ? "Pay with Razorpay" : "Configure plan env"}
            </button>
          </article>
        ))}
      </section> : null}

      {page === "plans" && user && entitlement?.active ? (
        <section className="paidHome">
          <div className="accountBox">
            <CheckCircle2 size={22} />
            <div>
              <strong>Payment complete</strong>
              <span>{activePlan?.label || entitlement.plan_code || "Active plan"} is active. Open the desktop app and log in with {user.email}.</span>
            </div>
          </div>
        </section>
      ) : null}

      {page === "settings" && user ? (
        <SettingsPage
          token={token}
          apiSetup={apiSetup}
          onSaved={(keys) => {
            setApiSetup(keys);
            setMessage("API key saved securely.");
            setError("");
          }}
          onError={(value) => {
            setError(value);
            setMessage("");
          }}
        />
      ) : null}

      {page === "profile" && user ? (
        <ProfilePage
          token={token}
          user={user}
          entitlement={entitlement}
          displayName={displayName}
          onDisplayName={setDisplayName}
          onSaved={(nextUser) => {
            setUser(nextUser);
            setMessage("Profile updated.");
            setError("");
          }}
          onError={(value) => {
            setError(value);
            setMessage("");
          }}
        />
      ) : null}
    </main>
  );
}

function SettingsPage(props: {
  token: string;
  apiSetup: ApiSetup | null;
  onSaved: (setup: ApiSetup) => void;
  onError: (message: string) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, { value: string; model: string }>>({});
  const [selectedAi, setSelectedAi] = useState("gemini");
  const [busy, setBusy] = useState("");
  const statuses = props.apiSetup?.statuses ?? [];
  const selectedAiMeta = aiProviders.find((item) => item.provider === selectedAi) || aiProviders[0];
  const selectedAiStatus = statuses.find((row) => row.provider === selectedAi);
  const selectedAiDraft = drafts[selectedAi] || { value: "", model: selectedAiStatus?.model || selectedAiMeta.model };

  async function save(provider: string) {
    setBusy(provider);
    try {
      const draft = drafts[provider] || { value: "", model: "" };
      const result = await api.saveApiKey(props.token, { provider, value: draft.value, model: draft.model });
      setDrafts((items) => ({ ...items, [provider]: { value: "", model: draft.model } }));
      props.onSaved(result);
    } catch (err) {
      props.onError(err instanceof Error ? err.message : "Could not save API key.");
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="settingsPage">
      <header><h1>Settings</h1><p>Save AI, asset, and voice keys once. Values are encrypted in the user database.</p></header>
      <div className="settingCard aiSetupCard">
        <div className="settingHead">
          <strong>AI Provider</strong>
          <span>{selectedAiStatus?.status || "missing"} · {selectedAiStatus?.source || "none"}</span>
        </div>
        <label>
          AI
          <select value={selectedAi} onChange={(event) => setSelectedAi(event.target.value)}>
            {aiProviders.map((item) => <option value={item.provider} key={item.provider}>{item.label}</option>)}
          </select>
        </label>
        <label>
          Model
          <select value={selectedAiDraft.model} onChange={(event) => setDrafts((items) => ({ ...items, [selectedAi]: { ...selectedAiDraft, model: event.target.value } }))}>
            {(modelOptions[selectedAi] || []).map((model) => <option value={model} key={model}>{model}</option>)}
            {selectedAiDraft.model && !(modelOptions[selectedAi] || []).includes(selectedAiDraft.model) ? <option value={selectedAiDraft.model}>{selectedAiDraft.model}</option> : null}
          </select>
        </label>
        <label>
          API key
          <input type="password" value={selectedAiDraft.value} placeholder={`Paste ${selectedAiMeta.label} key`} onChange={(event) => setDrafts((items) => ({ ...items, [selectedAi]: { ...selectedAiDraft, value: event.target.value } }))} />
        </label>
        <button className="primaryButton" disabled={busy === selectedAi || !selectedAiDraft.value.trim()} onClick={() => void save(selectedAi)}>
          {busy === selectedAi ? <Loader2 className="spin" size={16} /> : <Settings size={16} />} Save AI key
        </button>
      </div>
      <header className="minorHeader"><h2>Other services</h2><p>Asset search and voice credentials used by the video pipeline.</p></header>
      <div className="settingsGrid">
        {otherProviders.map((item) => {
          const status = statuses.find((row) => row.provider === item.provider);
          const draft = drafts[item.provider] || { value: "", model: status?.model || item.model };
          return (
            <article className="settingCard" key={item.provider}>
              <div className="settingHead"><strong>{item.label}</strong><span>{status?.status || "missing"} · {status?.source || "none"}</span></div>
              <input type="password" value={draft.value} placeholder="Paste API key or credentials path" onChange={(event) => setDrafts((items) => ({ ...items, [item.provider]: { ...draft, value: event.target.value } }))} />
              <button className="primaryButton" disabled={busy === item.provider || !draft.value.trim()} onClick={() => void save(item.provider)}>
                {busy === item.provider ? <Loader2 className="spin" size={16} /> : <Settings size={16} />} Save
              </button>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ProfilePage(props: {
  token: string;
  user: User;
  entitlement: Entitlement | null;
  displayName: string;
  onDisplayName: (value: string) => void;
  onSaved: (user: User) => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try {
      props.onSaved(await api.updateProfile(props.token, props.displayName));
    } catch (err) {
      props.onError(err instanceof Error ? err.message : "Could not update profile.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="settingsPage narrow">
      <header><h1>Profile</h1><p>Manage your account identity and desktop access status.</p></header>
      <div className="profileCard">
        <label>Name<input value={props.displayName} onChange={(event) => props.onDisplayName(event.target.value)} /></label>
        <label>Email<input value={props.user.email} disabled /></label>
        <div className="accountBox"><ShieldCheck size={18} /><div><strong>{props.entitlement?.active ? "Access active" : "Access inactive"}</strong><span>{props.entitlement?.plan_code || "No plan selected"}</span></div></div>
        <button className="primaryButton" disabled={busy} onClick={() => void save()}>{busy ? <Loader2 className="spin" size={16} /> : <UserRound size={16} />} Save profile</button>
      </div>
    </section>
  );
}
