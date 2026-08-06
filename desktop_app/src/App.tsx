import {
  CheckCircle2,
  CreditCard,
  Download,
  ExternalLink,
  Film,
  KeyRound,
  Loader2,
  LogOut,
  MessageSquareText,
  Play,
  Plus,
  RefreshCw,
  Send,
  Settings,
  ShieldAlert,
  Sparkles,
  UserRound,
  X
} from "lucide-react";
import { FormEvent, Fragment, useCallback, useEffect, useMemo, useState } from "react";
import type { ApiSetup, Chat, ChatReply, Entitlement, Genre, Job, Message, OnboardingState, Progress, StageLogs, User } from "./types";

type AuthMode = "login" | "signup";
type Gate = "booting" | "logged_out" | "unpaid" | "active" | "api_down";
type StudioView = "studio" | "settings" | "profile";

const terminal = new Set(["succeeded", "failed", "skipped"]);
const retryableStages = new Set([
  "topic_discovery_agent",
  "research_agent",
  "script_agent",
  "validation_agent",
  "asset_agent",
  "audio_agent",
  "caption_agent",
  "timed_visual_agent",
  "music_agent",
  "render_agent",
  "thumbnail_agent"
]);
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

const maxHumanLogLength = 1800;

async function api<T>(path: string, options?: { method?: string; json?: unknown }) {
  return window.desktopApi.request<T>(path, options);
}

function apiAssetUrl(apiBase: string, path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const base = apiBase.replace(/\/$/, "");
  if (path.startsWith("/api/") && base.endsWith("/api")) return `${base}${path.slice(4)}`;
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}

function errorStatus(error: unknown): number {
  return typeof error === "object" && error !== null && "status" in error ? Number((error as { status?: number }).status) : 0;
}

function historyTitle(chat: Chat): string {
  const title = (chat.title || "").trim();
  if (!title || title.toLowerCase() === "studio") return "New chat";
  return title;
}

function messageMetadata(message: Message): Record<string, unknown> {
  return message.message_metadata && typeof message.message_metadata === "object" ? message.message_metadata : {};
}

function isCalibrationStartMessage(message: Message): boolean {
  return messageMetadata(message).kind === "calibration_started";
}

function isCalibrationJobStatusMessage(message: Message, calibrationJobIds: Set<string>): boolean {
  const jobId = String(messageMetadata(message).job_id || "");
  return message.role === "assistant" && Boolean(jobId) && calibrationJobIds.has(jobId);
}

export function App() {
  const [gate, setGate] = useState<Gate>("booting");
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [user, setUser] = useState<User | null>(null);
  const [entitlement, setEntitlement] = useState<Entitlement | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refreshSession = useCallback(async () => {
    const token = window.desktopApi.token.get();
    if (!token) {
      setGate("logged_out");
      return;
    }
    try {
      const [me, access] = await Promise.all([api<User>("/auth/me"), api<Entitlement>("/billing/entitlement")]);
      setUser(me);
      setEmail(me.email);
      setEntitlement(access);
      setGate(access.active ? "active" : "unpaid");
    } catch (err) {
      if (errorStatus(err) === 401) {
        window.desktopApi.token.clear();
        setUser(null);
        setEntitlement(null);
        setGate("logged_out");
      } else {
        setError(errorMessage(err));
        setGate("api_down");
      }
    }
  }, []);

  useEffect(() => {
    void refreshSession();
  }, [refreshSession]);

  async function submitAuth(event: FormEvent) {
    event.preventDefault();
    setBusy("auth");
    setError("");
    setNotice("");
    try {
      const result = await api<{ access_token: string }>(authMode === "signup" ? "/auth/signup" : "/auth/login", {
        method: "POST",
        json:
          authMode === "signup"
            ? { email, password, display_name: displayName }
            : { email, password }
      });
      window.desktopApi.token.set(result.access_token);
      await refreshSession();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  function logout() {
    window.desktopApi.token.clear();
    setUser(null);
    setEntitlement(null);
    setPassword("");
    setNotice("Signed out.");
    setGate("logged_out");
  }

  async function openPaymentSite() {
    const suffix = email ? `?email=${encodeURIComponent(email)}` : "";
    await window.desktopApi.openPaymentSite(suffix);
  }

  if (gate === "booting") return <FullScreenLoader />;

  if (gate !== "active") {
    return (
      <LockedScreen
        gate={gate}
        authMode={authMode}
        email={email}
        displayName={displayName}
        password={password}
        busy={busy}
        error={error}
        notice={notice}
        user={user}
        entitlement={entitlement}
        onAuthMode={setAuthMode}
        onEmail={setEmail}
        onDisplayName={setDisplayName}
        onPassword={setPassword}
        onSubmitAuth={submitAuth}
        onOpenPaymentSite={() => void openPaymentSite()}
        onRefresh={() => void refreshSession()}
        onLogout={logout}
      />
    );
  }

  return (
    <StudioShell
      user={user}
      entitlement={entitlement}
      onLogout={logout}
      onPaymentRequired={() => setGate("unpaid")}
      onSessionError={(message) => {
        setError(message);
        setGate("api_down");
      }}
    />
  );
}

function FullScreenLoader() {
  return (
    <main className="centerScreen">
      <Loader2 className="spin" size={34} />
      <strong>Checking desktop access</strong>
    </main>
  );
}

function LockedScreen(props: {
  gate: Gate;
  authMode: AuthMode;
  email: string;
  displayName: string;
  password: string;
  busy: string;
  error: string;
  notice: string;
  user: User | null;
  entitlement: Entitlement | null;
  onAuthMode: (mode: AuthMode) => void;
  onEmail: (value: string) => void;
  onDisplayName: (value: string) => void;
  onPassword: (value: string) => void;
  onSubmitAuth: (event: FormEvent) => void;
  onOpenPaymentSite: () => void;
  onRefresh: () => void;
  onLogout: () => void;
}) {
  const subtitle =
    props.gate === "api_down"
      ? "The local backend is not reachable. Start Docker Compose and try again."
      : props.gate === "unpaid"
        ? "This account is valid, but payment access is not active yet."
        : "Log in with the same account you use on the payment website.";

  return (
    <main className="lockedPage">
      <section className="lockedHero">
        <div className="brandRow">
          <div className="brandMark"><Sparkles size={20} /></div>
          <div>
            <strong>Modular Shorts Studio</strong>
            <span>Paid desktop app</span>
          </div>
        </div>
        <div className="desktopPreview" aria-hidden="true">
          <div className="previewTop"><span /><span /><span /></div>
          <div className="previewBody">
            <div className="previewSide" />
            <div className="previewMain">
              <div className="chatLine self">select scary stories</div>
              <div className="previewStyles">
                <div>Cinematic</div>
                <div>Fast Cut</div>
                <div>Evidence</div>
              </div>
              <div className="chatLine">3 generated styles ready</div>
            </div>
          </div>
        </div>
        <h1>Payment unlocks the full desktop studio</h1>
        <p>{subtitle}</p>
        <div className="heroActions">
          <button className="primaryButton" onClick={props.onOpenPaymentSite}>
            <CreditCard size={16} /> Open payment website
          </button>
          <button className="secondaryButton" onClick={props.onRefresh}>
            <RefreshCw size={16} /> Check access
          </button>
        </div>
        {props.user ? (
          <div className="entitlementBox">
            <ShieldAlert size={18} />
            <span>{props.entitlement?.active ? "Access active" : `Access ${props.entitlement?.status || "inactive"}`}</span>
          </div>
        ) : null}
      </section>

      <aside className="authPanel">
        <div className="tabs">
          <button className={props.authMode === "login" ? "active" : ""} onClick={() => props.onAuthMode("login")}>Login</button>
          <button className={props.authMode === "signup" ? "active" : ""} onClick={() => props.onAuthMode("signup")}>Sign up</button>
        </div>
        <form onSubmit={props.onSubmitAuth}>
          {props.authMode === "signup" ? (
            <label>Name<input value={props.displayName} onChange={(event) => props.onDisplayName(event.target.value)} /></label>
          ) : null}
          <label>Email<input type="email" value={props.email} onChange={(event) => props.onEmail(event.target.value)} required /></label>
          <label>Password<input type="password" value={props.password} onChange={(event) => props.onPassword(event.target.value)} minLength={props.authMode === "signup" ? 8 : 1} required /></label>
          <button className="primaryButton" disabled={props.busy === "auth"}>
            {props.busy === "auth" ? <Loader2 className="spin" size={16} /> : <KeyRound size={16} />}
            {props.authMode === "signup" ? "Create account" : "Log in"}
          </button>
        </form>
        {props.user ? (
          <div className="signedInBox">
            <CheckCircle2 size={18} />
            <div><strong>{props.user.email}</strong><span>Signed in locally</span></div>
            <button className="iconButton" title="Sign out" onClick={props.onLogout}><LogOut size={16} /></button>
          </div>
        ) : null}
        {props.error || props.notice ? <div className={props.error ? "alert error" : "alert success"}>{props.error || props.notice}</div> : null}
      </aside>
    </main>
  );
}

function StudioShell(props: {
  user: User | null;
  entitlement: Entitlement | null;
  onLogout: () => void;
  onPaymentRequired: () => void;
  onSessionError: (message: string) => void;
}) {
  const [genres, setGenres] = useState<Genre[]>([]);
  const [state, setState] = useState<OnboardingState | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [chats, setChats] = useState<Chat[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedGenre, setSelectedGenre] = useState("");
  const [prompt, setPrompt] = useState("");
  const [chatDraft, setChatDraft] = useState("");
  const [activeChatId, setActiveChatId] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [view, setView] = useState<StudioView>("studio");
  const [apiSetup, setApiSetup] = useState<ApiSetup | null>(null);
  const [profile, setProfile] = useState<User | null>(props.user);
  const [progressByJob, setProgressByJob] = useState<Record<string, Progress>>({});

  const calibrationJobs = useMemo(
    () => jobs.filter((job) => job.chat_id === activeChatId && job.job_type === "calibration_sample" && (!state?.genre_id || job.genre === state.genre_id)).slice(0, 3),
    [activeChatId, jobs, state?.genre_id]
  );
  const regularJobs = useMemo(() => jobs.filter((job) => job.job_type !== "calibration_sample"), [jobs]);
  const activeJobs = useMemo(() => jobs.filter((job) => job.chat_id === activeChatId && job.job_type !== "calibration_sample"), [activeChatId, jobs]);
  const calibrationPercent = useMemo(() => {
    if (!calibrationJobs.length) return 0;
    const total = calibrationJobs.reduce((sum, job) => {
      const progress = progressByJob[job.id];
      const fallback = job.status === "succeeded" ? 100 : job.status === "failed" ? 100 : 2;
      return sum + (progress?.percent ?? fallback);
    }, 0);
    return Math.round(total / calibrationJobs.length);
  }, [calibrationJobs, progressByJob]);
  const onboardingComplete = Boolean(state?.completed);
  const calibrationPrompt = state?.user_intent || (calibrationJobs.length ? prompt : "");
  const calibrationJobIds = useMemo(() => new Set(calibrationJobs.map((job) => job.id)), [calibrationJobs]);
  const visibleMessages = useMemo(
    () => messages.filter((message) => !isCalibrationJobStatusMessage(message, calibrationJobIds)),
    [calibrationJobIds, messages]
  );
  const hasCalibrationStartMessage = useMemo(() => visibleMessages.some(isCalibrationStartMessage), [visibleMessages]);
  const hasCalibrationUserMessage = useMemo(() => {
    const expected = calibrationPrompt.trim();
    return Boolean(expected) && visibleMessages.some((message) => message.role === "user" && message.content.trim() === expected);
  }, [calibrationPrompt, visibleMessages]);

  const guarded = useCallback(
    async <T,>(work: () => Promise<T>): Promise<T | null> => {
      try {
        return await work();
      } catch (err) {
        if (errorStatus(err) === 402) props.onPaymentRequired();
        else if (errorStatus(err) === 401) props.onSessionError("Session expired. Log in again.");
        else setError(errorMessage(err));
        return null;
      }
    },
    [props]
  );

  const loadStudio = useCallback(async () => {
    await guarded(async () => {
      const [nextGenres, nextState, nextJobs, chats] = await Promise.all([
        api<Genre[]>("/onboarding/genres"),
        api<OnboardingState>("/onboarding"),
        api<Job[]>("/jobs"),
        api<Chat[]>("/chats")
      ]);
      setGenres(nextGenres);
      setState(nextState);
      setJobs(nextJobs);
      setChats(chats);
      setSelectedGenre(nextState.genre_id || nextGenres[0]?.genre_id || "scary_stories");
      setPrompt(nextState.user_intent || "");
      let chatId = nextState.active_chat_id || chats[0]?.id || "";
      if (!chatId) {
        const chat = await api<Chat>("/chats", { method: "POST", json: { title: "Studio" } });
        chatId = chat.id;
      }
      setActiveChatId(chatId);
      setMessages(chatId ? await api<Message[]>(`/chats/${chatId}/messages`) : []);
    });
  }, [guarded]);

  const loadSettings = useCallback(async () => {
    await guarded(async () => {
      const [keys, nextProfile] = await Promise.all([api<ApiSetup>("/account/api-keys"), api<User>("/account/profile")]);
      setApiSetup(keys);
      setProfile(nextProfile);
    });
  }, [guarded]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  useEffect(() => {
    void loadStudio();
  }, [loadStudio]);

  useEffect(() => {
    const hasRunning = jobs.some((job) => !terminal.has(job.status));
    if (!hasRunning) return;
    const id = window.setInterval(() => {
      guarded(async () => {
        setJobs(await api<Job[]>("/jobs"));
        if (activeChatId) setMessages(await api<Message[]>(`/chats/${activeChatId}/messages`));
      });
    }, 3000);
    return () => window.clearInterval(id);
  }, [activeChatId, guarded, jobs]);

  async function startCalibration(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim()) return;
    setBusy("calibration");
    setError("");
    await guarded(async () => {
      const genreId = selectedGenre || genres[0]?.genre_id || "scary_stories";
      await api<OnboardingState>("/onboarding/genre-intent", { method: "POST", json: { genre_id: genreId, user_intent: prompt.trim() } });
      await api<Job[]>("/onboarding/calibration/start", {
        method: "POST",
        json: {
          genre_id: genreId,
          user_intent: prompt.trim(),
          settings: { duration: 45, voice_speed: 1, caption_words: 4, image_count: 8, music_volume: 0.12, schedule: "" }
        }
      });
      await loadStudio();
      setChats(await api<Chat[]>("/chats"));
    });
    setBusy("");
  }

  async function chooseStyle(job: Job) {
    setBusy(job.id);
    setError("");
    await guarded(async () => {
      await api("/onboarding/calibration/complete", {
        method: "POST",
        json: { preferred_video_id: job.id, why_chosen: "Selected in the desktop app.", improvement_notes: "" }
      });
      await loadStudio();
    });
    setBusy("");
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    if (!chatDraft.trim() || !activeChatId) return;
    const content = chatDraft.trim();
    setChatDraft("");
    setBusy("chat");
    await guarded(async () => {
      const reply = await api<ChatReply>(`/chats/${activeChatId}/messages`, { method: "POST", json: { content } });
      setMessages((items) => [...items, reply.message]);
      setJobs(await api<Job[]>("/jobs"));
      setMessages(await api<Message[]>(`/chats/${activeChatId}/messages`));
      setChats(await api<Chat[]>("/chats"));
    });
    setBusy("");
  }

  async function newChat() {
    setBusy("new-chat");
    setError("");
    await guarded(async () => {
      const chat = await api<Chat>("/chats", { method: "POST", json: { title: "New chat" } });
      setActiveChatId(chat.id);
      setMessages([]);
      setPrompt("");
      setChatDraft("");
      setChats([chat, ...chats.filter((item) => item.id !== chat.id)]);
      setView("studio");
    });
    setBusy("");
  }

  async function openChat(chat: Chat) {
    setBusy(chat.id);
    setError("");
    await guarded(async () => {
      await api<Chat>(`/chats/${chat.id}/activate`, { method: "POST" });
      setActiveChatId(chat.id);
      setPrompt("");
      setChatDraft("");
      setMessages(await api<Message[]>(`/chats/${chat.id}/messages`));
      setView("studio");
    });
    setBusy("");
  }

  async function retryJob(job: Job, stageName = "") {
    setBusy(`${job.id}:${stageName || "all"}`);
    setError("");
    await guarded(async () => {
      const next = await api<Job>(`/jobs/${job.id}/retry`, { method: "POST", json: { stage_name: stageName } });
      setJobs((items) => [next, ...items]);
      setJobs(await api<Job[]>("/jobs"));
      if (activeChatId) setMessages(await api<Message[]>(`/chats/${activeChatId}/messages`));
    });
    setBusy("");
  }

  return (
    <main className="studio">
      <aside className="studioSidebar">
        <div className="brandRow compact">
          <div className="brandMark"><Sparkles size={18} /></div>
          <div><strong>Studio</strong><span>{props.user?.email}</span></div>
        </div>
        <div className="accessPill">
          <CheckCircle2 size={16} /> {props.entitlement?.source === "lifetime" ? "Lifetime access" : "Subscription active"}
        </div>
        <nav className="sideNav">
          <button className={view === "studio" ? "active" : ""} onClick={() => setView("studio")}><Film size={16} /> Studio</button>
          <button className={view === "settings" ? "active" : ""} onClick={() => setView("settings")}><Settings size={16} /> Settings</button>
          <button className={view === "profile" ? "active" : ""} onClick={() => setView("profile")}><UserRound size={16} /> Profile</button>
        </nav>
        <button className="primaryButton" disabled={busy === "new-chat"} onClick={() => void newChat()}>
          {busy === "new-chat" ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}
          New chat
        </button>
        <button className="secondaryButton" onClick={() => void loadStudio()}><RefreshCw size={16} /> Refresh</button>
        <button className="ghostDanger" onClick={props.onLogout}><LogOut size={16} /> Sign out</button>

        <section className="historyList">
          <h2>History</h2>
          {chats.map((chat) => (
            <button className={chat.id === activeChatId ? "active" : ""} key={chat.id} onClick={() => void openChat(chat)}>
              <MessageSquareText size={14} />
              <span>{historyTitle(chat)}</span>
            </button>
          ))}
          {!chats.length ? <p className="muted">No chats yet.</p> : null}
        </section>

        <section className="jobList">
          <h2>Recent jobs</h2>
          {regularJobs.slice(0, 6).map((job) => <JobRow key={job.id} job={job} onRetry={(stage) => void retryJob(job, stage)} busy={busy} />)}
          {!regularJobs.length ? <p className="muted">Generated videos appear here.</p> : null}
        </section>
      </aside>

      <section className="studioMain">
        {view === "settings" ? (
          <DesktopSettingsPage apiSetup={apiSetup} onSaved={setApiSetup} onError={setError} />
        ) : null}

        {view === "profile" ? (
          <DesktopProfilePage
            user={profile || props.user}
            entitlement={props.entitlement}
            onSaved={(nextUser) => {
              setProfile(nextUser);
              setError("");
            }}
            onError={setError}
          />
        ) : null}

        {view === "studio" ? (
        <>
        <header className="studioHeader">
          <div>
            <span className="eyebrow">{onboardingComplete ? "Chat studio" : "First run calibration"}</span>
            <h1>{onboardingComplete ? "Ask for a new video or refine the latest one" : "Pick a genre and generate 3 styles"}</h1>
          </div>
          <Film size={28} />
        </header>

        {!onboardingComplete && calibrationJobs.length ? (
          <div className="topProgressCard">
            <div className="progressHeader">
              <span>3 styles running in parallel</span>
              <span>{calibrationPercent}% done</span>
            </div>
            <div className="progressTrack"><span style={{ width: `${calibrationPercent}%` }} /></div>
          </div>
        ) : null}

        {error ? <div className="alert error">{error}</div> : null}

        {!onboardingComplete ? (
          <section className="chatAgentView">
            <div className="messages agentScroll calibrationChat">
              {!calibrationPrompt.trim() && !calibrationJobs.length ? (
                <div className="emptyChat">
                  <MessageSquareText size={30} />
                  <strong>Tell me the video idea first.</strong>
                  <span>Choose the genre below, then send the prompt to generate three style options.</span>
                </div>
              ) : null}
              {calibrationPrompt.trim() ? (
                <div className="message user">
                  <span>user</span>
                  <p>{calibrationPrompt}</p>
                </div>
              ) : null}
              {calibrationJobs.length ? (
                <CalibrationSamplesMessage
                  jobs={calibrationJobs}
                  busy={busy}
                  onProgress={(jobId, progress) => setProgressByJob((items) => ({ ...items, [jobId]: progress }))}
                  onRetry={(job, stage) => void retryJob(job, stage)}
                  onChoose={(job) => void chooseStyle(job)}
                  onError={setError}
                />
              ) : prompt.trim() ? (
                <div className="message assistant">
                  <span>assistant</span>
                  <p>Ready when you are. Press generate and I will create three style directions from this prompt.</p>
                </div>
              ) : null}
            </div>
            <form className="bottomComposer calibrationComposer" onSubmit={startCalibration}>
              <label className="composerSelect" title="Genre">
                <span>Genre</span>
                <select value={selectedGenre} onChange={(event) => setSelectedGenre(event.target.value)}>
                  {genres.map((genre) => <option key={genre.genre_id} value={genre.genre_id}>{genre.display_name}</option>)}
                </select>
              </label>
              <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Describe the video you want to make..." rows={2} />
              <button className="primaryButton" disabled={busy === "calibration" || !prompt.trim()}>
                {busy === "calibration" ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                Generate 3 styles
              </button>
            </form>
          </section>
        ) : (
          <section className="chatAgentView">
            <div className="messages agentScroll">
              {!visibleMessages.length && !calibrationJobs.length ? (
                <div className="emptyChat">
                  <MessageSquareText size={30} />
                  <strong>Ready for your first paid chat run.</strong>
                  <span>Type a video idea, or ask to edit the latest generated video.</span>
                </div>
              ) : null}
              {calibrationJobs.length && !hasCalibrationStartMessage && !hasCalibrationUserMessage && calibrationPrompt.trim() ? (
                <div className="message user">
                  <span>user</span>
                  <p>{calibrationPrompt}</p>
                </div>
              ) : null}
              {calibrationJobs.length && !hasCalibrationStartMessage ? (
                <CalibrationSamplesMessage
                  jobs={calibrationJobs}
                  busy={busy}
                  onProgress={(jobId, progress) => setProgressByJob((items) => ({ ...items, [jobId]: progress }))}
                  onRetry={(job, stage) => void retryJob(job, stage)}
                  onChoose={(job) => void chooseStyle(job)}
                  onError={setError}
                />
              ) : null}
              {visibleMessages.map((message) => (
                <Fragment key={message.id}>
                  <div className={`message ${message.role}`}>
                    <span>{message.role}</span>
                    <p>{message.content}</p>
                  </div>
                  {calibrationJobs.length && isCalibrationStartMessage(message) ? (
                    <CalibrationSamplesMessage
                      jobs={calibrationJobs}
                      busy={busy}
                      onProgress={(jobId, progress) => setProgressByJob((items) => ({ ...items, [jobId]: progress }))}
                      onRetry={(job, stage) => void retryJob(job, stage)}
                      onChoose={(job) => void chooseStyle(job)}
                      onError={setError}
                    />
                  ) : null}
                </Fragment>
              ))}
              {activeJobs.map((job) => <JobRow key={job.id} job={job} onRetry={(stage) => void retryJob(job, stage)} busy={busy} />)}
            </div>
            <form className="bottomComposer" onSubmit={sendMessage}>
              <textarea value={chatDraft} onChange={(event) => setChatDraft(event.target.value)} placeholder="Make a video about... or say: audio is too fast" rows={3} />
              <button className="primaryButton" disabled={busy === "chat" || !chatDraft.trim()}>
                {busy === "chat" ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
                Send
              </button>
            </form>
          </section>
        )}
        </>
        ) : null}
      </section>
    </main>
  );
}

function CalibrationSamplesMessage({
  jobs,
  busy,
  onProgress,
  onRetry,
  onChoose,
  onError
}: {
  jobs: Job[];
  busy: string;
  onProgress: (jobId: string, progress: Progress) => void;
  onRetry: (job: Job, stageName?: string) => void;
  onChoose: (job: Job) => void;
  onError: (message: string) => void;
}) {
  return (
    <div className="message assistant calibrationAssistant">
      <span>assistant</span>
      <p>I am making three style videos for you. Each one has its own pipeline, so you can inspect any node and then pick the finished style you like best.</p>
      <div className="sampleGrid">
        {jobs.map((job) => (
          <article className="sampleCard pipelineSampleCard" key={job.id}>
            <div className="sampleMeta">
              <strong>{String((job.settings?.style_profile as Record<string, unknown> | undefined)?.label || `Style ${job.settings?.sample_index || ""}`)}</strong>
              <span>{job.status}</span>
            </div>
            <JobProgress
              job={job}
              detailed
              compact
              onProgress={(progress) => onProgress(job.id, progress)}
              onRetryStage={(stage) => onRetry(job, stage)}
              busy={busy}
              onError={onError}
            />
            <div className="sampleActions">
              <button className="secondaryButton" disabled={!terminal.has(job.status) || busy === `${job.id}:all`} onClick={() => onRetry(job)}>
                {busy === `${job.id}:all` ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                Retry
              </button>
              <VideoPreviewButton job={job} variant="text" />
              <button className="secondaryButton" disabled={job.status !== "succeeded" || busy === job.id} onClick={() => onChoose(job)}>
                {busy === job.id ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
                Pick
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function JobRow({ job, onRetry, busy = "" }: { job: Job; onRetry?: (stageName: string) => void; busy?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <article className="jobRow expanded">
      <div className="jobRowTop">
        <div><strong>{job.topic}</strong><span>{job.status} · {job.genre}</span></div>
        <div className="jobActions">
          {job.status === "succeeded" ? <VideoPreviewButton job={job} /> : null}
          {job.status === "succeeded" ? <DownloadButton job={job} /> : null}
          <button className="iconButton" title="Retry full flow" disabled={!terminal.has(job.status) || busy === `${job.id}:all`} onClick={() => onRetry?.("")}>
            {busy === `${job.id}:all` ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          </button>
          <button className="iconButton" title="Pipeline stages" onClick={() => setOpen(!open)}><ExternalLink size={16} /></button>
        </div>
      </div>
      <JobProgress job={job} detailed={open} onRetryStage={(stage) => onRetry?.(stage)} busy={busy} />
    </article>
  );
}

function DesktopSettingsPage(props: {
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
    const draft = drafts[provider] || { value: "", model: "" };
    if (!draft.value.trim()) return;
    setBusy(provider);
    try {
      const result = await api<ApiSetup>("/account/api-keys", { method: "POST", json: { provider, value: draft.value, model: draft.model } });
      setDrafts((items) => ({ ...items, [provider]: { value: "", model: draft.model } }));
      props.onSaved(result);
    } catch (err) {
      props.onError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="settingsSurface">
      <header className="studioHeader">
        <div><span className="eyebrow">Encrypted key vault</span><h1>Settings</h1></div>
        <Settings size={28} />
      </header>
      <div className="settingCard aiSetupCard">
        <div className="settingHead"><strong>AI Provider</strong><span>{selectedAiStatus?.status || "missing"} · {selectedAiStatus?.source || "none"}</span></div>
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
          <input type="password" placeholder={`Paste ${selectedAiMeta.label} key`} value={selectedAiDraft.value} onChange={(event) => setDrafts((items) => ({ ...items, [selectedAi]: { ...selectedAiDraft, value: event.target.value } }))} />
        </label>
        <button className="primaryButton" disabled={busy === selectedAi || !selectedAiDraft.value.trim()} onClick={() => void save(selectedAi)}>
          {busy === selectedAi ? <Loader2 className="spin" size={16} /> : <Settings size={16} />}
          Save AI key
        </button>
      </div>
      <header className="minorHeader"><h2>Other services</h2><p>Asset search and voice credentials used by the pipeline.</p></header>
      <div className="settingsGrid">
        {otherProviders.map((item) => {
          const status = statuses.find((row) => row.provider === item.provider);
          const draft = drafts[item.provider] || { value: "", model: status?.model || item.model };
          return (
            <article className="settingCard" key={item.provider}>
              <div className="settingHead"><strong>{item.label}</strong><span>{status?.status || "missing"} · {status?.source || "none"}</span></div>
              <input type="password" placeholder="Paste API key or credentials path" value={draft.value} onChange={(event) => setDrafts((items) => ({ ...items, [item.provider]: { ...draft, value: event.target.value } }))} />
              <button className="primaryButton" disabled={busy === item.provider || !draft.value.trim()} onClick={() => void save(item.provider)}>
                {busy === item.provider ? <Loader2 className="spin" size={16} /> : <Settings size={16} />}
                Save key
              </button>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function DesktopProfilePage(props: {
  user: User | null;
  entitlement: Entitlement | null;
  onSaved: (user: User) => void;
  onError: (message: string) => void;
}) {
  const [name, setName] = useState(props.user?.display_name || "");
  const [busy, setBusy] = useState(false);

  useEffect(() => setName(props.user?.display_name || ""), [props.user?.display_name]);

  async function save() {
    setBusy(true);
    try {
      props.onSaved(await api<User>("/account/profile", { method: "PUT", json: { display_name: name } }));
    } catch (err) {
      props.onError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settingsSurface narrow">
      <header className="studioHeader">
        <div><span className="eyebrow">Account</span><h1>Profile</h1></div>
        <UserRound size={28} />
      </header>
      <div className="profileCard">
        <label>Name<input value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label>Email<input value={props.user?.email || ""} disabled /></label>
        <div className="accessPill"><CheckCircle2 size={16} /> {props.entitlement?.active ? `Active ${props.entitlement.plan_code}` : "Access inactive"}</div>
        <button className="primaryButton" disabled={busy} onClick={() => void save()}>{busy ? <Loader2 className="spin" size={16} /> : <UserRound size={16} />} Save profile</button>
      </div>
    </section>
  );
}

function JobProgress({
  job,
  detailed = false,
  compact = false,
  onProgress,
  onRetryStage,
  busy = "",
  onError
}: {
  job: Job;
  detailed?: boolean;
  compact?: boolean;
  onProgress?: (progress: Progress) => void;
  onRetryStage?: (stageName: string) => void;
  busy?: string;
  onError?: (message: string) => void;
}) {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [stageLogs, setStageLogs] = useState<StageLogs | null>(null);
  const [logsBusy, setLogsBusy] = useState("");
  useEffect(() => {
    let alive = true;
    api<Progress>(`/jobs/${job.id}/progress`).then((data) => {
      if (!alive) return;
      setProgress(data);
      onProgress?.(data);
    }).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [job.id, job.status, job.updated_at]);
  useEffect(() => {
    setStageLogs(null);
  }, [job.id]);
  const percent = progress?.percent ?? (job.status === "succeeded" ? 100 : job.status === "failed" ? 100 : 4);
  const visibleAgents = progress?.agents || [];
  async function openStage(agent: { name: string; label: string }) {
    setLogsBusy(agent.name);
    try {
      setStageLogs(await api<StageLogs>(`/jobs/${job.id}/stages/${agent.name}/logs`));
    } catch (err) {
      onError?.(errorMessage(err));
    } finally {
      setLogsBusy("");
    }
  }
  return (
    <div className="pipelineBox">
      <div className="progressHeader"><span>{percent}% complete</span><span>{progress?.current_agent || job.status}</span></div>
      <div className="progressTrack"><span style={{ width: `${percent}%` }} /></div>
      {!compact && progress?.error_message ? <div className="pipelineError">{progress.error_message}</div> : null}
      {detailed ? (
        <div className="stageGrid">
          {visibleAgents.map((agent) => (
            <button className={`stagePill ${agent.status}`} key={agent.name} title={agent.message || agent.label} onClick={() => void openStage(agent)}>
              {logsBusy === agent.name ? <Loader2 className="spin" size={12} /> : null}
              {agent.label}
              {agent.status === "failed" ? <span className="stageErrorDot" title={agent.message || "Stage failed"} /> : null}
            </button>
          ))}
        </div>
      ) : null}
      {stageLogs ? (
        <StageLogModal
          job={job}
          logs={stageLogs}
          busy={busy}
          onClose={() => setStageLogs(null)}
          onRetryStage={onRetryStage}
        />
      ) : null}
    </div>
  );
}

function StageLogModal({
  job,
  logs,
  busy,
  onClose,
  onRetryStage
}: {
  job: Job;
  logs: StageLogs;
  busy: string;
  onClose: () => void;
  onRetryStage?: (stageName: string) => void;
}) {
  const conversation = humanizeStageLogs(logs);
  const canRetry = Boolean(onRetryStage && retryableStages.has(logs.stage_name));

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div
      className="modalOverlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose();
      }}
    >
      <section className="stageModal" role="dialog" aria-modal="true" aria-label={`${logs.label} logs`}>
        <header className="stageModalHead">
          <div>
            <span className="eyebrow">Pipeline node</span>
            <h2>{logs.label}</h2>
            <p>{job.topic}</p>
          </div>
          <div className="stageModalActions">
            <span className={`statusBadge ${logs.status}`}>{logs.status}</span>
            {canRetry ? (
              <button className="secondaryButton compactButton" disabled={busy === `${job.id}:${logs.stage_name}`} onClick={() => onRetryStage?.(logs.stage_name)}>
                {busy === `${job.id}:${logs.stage_name}` ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />}
                Retry agent
              </button>
            ) : null}
            <button className="iconButton" title="Close" onClick={onClose}><X size={16} /></button>
          </div>
        </header>

        <div className="stageModalBody">
          {logs.error_message ? <div className="alert error">{logs.error_message}</div> : null}
          {logs.message && logs.message !== logs.error_message ? <p className="muted">{logs.message}</p> : null}

          <div className="humanLogGrid">
            <section className="humanLogBlock">
              <strong>User prompt</strong>
              <p>{conversation.prompt}</p>
            </section>
            <section className="humanLogBlock">
              <strong>AI answer</strong>
              <p>{conversation.answer}</p>
            </section>
          </div>

          <div className="stageLogGrid">
            <LogBlock title="Events" value={logs.events.length ? logs.events : logs.stdout_lines} />
            <LogBlock title="Input" value={logs.input_json} />
            <LogBlock title="Output" value={logs.output_json} />
            <LogBlock title="Error" value={logs.error_json || logs.error_message} />
          </div>
        </div>
      </section>
    </div>
  );
}

function humanizeStageLogs(logs: StageLogs): { prompt: string; answer: string } {
  return {
    prompt: summarizeStageInput(logs),
    answer: summarizeStageOutput(logs)
  };
}

function summarizeStageInput(logs: StageLogs): string {
  const input = asRecord(logs.input_json);
  if (!input) return "No input prompt was logged for this node yet.";

  const lines: string[] = [];
  const topic = firstString(input, ["topic", "source_prompt", "original_topic"]);
  const genre = firstString(input, ["genre_id", "genre"]);
  const angle = firstString(input, ["selected_angle", "angle"]);
  const userNotes = firstString(input, ["user_notes", "notes"]);
  const duration = input.duration;

  if (topic) lines.push(`Topic: ${topic}`);
  if (genre) lines.push(`Genre: ${genre}`);
  if (typeof duration === "number" || typeof duration === "string") lines.push(`Duration: ${duration} seconds`);
  if (angle) lines.push(`Angle: ${angle}`);
  if (userNotes) lines.push(`Direction: ${userNotes}`);

  const groundingPlan = asRecord(input.grounding_plan);
  const groundingIntent = firstString(groundingPlan, ["search_intent", "intent", "summary"]);
  if (groundingIntent) lines.push(`Research direction: ${groundingIntent}`);

  const imageCues = summarizeCueList(input.image_cues, "keyword");
  if (imageCues) lines.push(`Visual cues: ${imageCues}`);

  const timedCues = summarizeCueList(input.timed_visual_cues, "search_query");
  if (timedCues) lines.push(`Timed visuals: ${timedCues}`);

  const sfxCues = summarizeCueList(input.sfx_cues, "sfx_type");
  if (sfxCues) lines.push(`Sound cues: ${sfxCues}`);

  if (lines.length) return clampHumanText(lines.join("\n"));
  return clampHumanText(formatLogValue(logs.input_json));
}

function summarizeStageOutput(logs: StageLogs): string {
  const output = asRecord(logs.output_json);
  if (!output) {
    if (logs.error_message) return `This node failed before it produced an answer: ${logs.error_message}`;
    return "No AI answer or stage output has been logged for this node yet.";
  }

  const lines: string[] = [];
  const title = firstString(output, ["title"]);
  const hook = firstString(output, ["hook_line", "hook"]);
  const narration = firstString(output, ["narration"]);
  const brief = firstString(output, ["brief", "description", "status", "skipped_reason"]);

  switch (logs.stage_name) {
    case "topic_discovery_agent": {
      const selectedTopic = firstString(output, ["selected_topic"]);
      const selectedAngle = firstString(output, ["selected_angle"]);
      if (selectedTopic) lines.push(`Selected topic: ${selectedTopic}`);
      if (selectedAngle) lines.push(`Angle: ${selectedAngle}`);
      const candidates = summarizeCandidateList(output.candidates);
      if (candidates) lines.push(`Other angles considered: ${candidates}`);
      break;
    }
    case "research_agent": {
      if (brief) lines.push(brief);
      const facts = summarizeStringList(output.facts);
      if (facts) lines.push(`Key facts: ${facts}`);
      break;
    }
    case "script_agent": {
      if (title) lines.push(`Title: ${title}`);
      if (hook) lines.push(`Hook: ${hook}`);
      if (narration) lines.push(`Narration: ${narration}`);
      break;
    }
    case "validation_agent": {
      lines.push(Boolean(output.passed) ? "Validation passed." : "Validation found issues.");
      const issues = summarizeStringList(output.issues);
      const repairNotes = summarizeStringList(output.repair_notes);
      if (issues) lines.push(`Issues: ${issues}`);
      if (repairNotes) lines.push(`Fix notes: ${repairNotes}`);
      break;
    }
    case "asset_agent": {
      const mediaCount = arrayLength(output.media_paths) || arrayLength(output.image_paths) || arrayLength(output.video_paths);
      if (mediaCount) lines.push(`Selected ${mediaCount} visual asset${mediaCount === 1 ? "" : "s"}.`);
      const terms = summarizeStringList(output.stock_video_search_terms || output.sources);
      if (terms) lines.push(`Search/source summary: ${terms}`);
      const subjectIssues = summarizeStringList(output.subject_lock_issues);
      if (subjectIssues) lines.push(`Asset warnings: ${subjectIssues}`);
      break;
    }
    case "audio_agent":
      lines.push(`Generated narration audio${firstString(output, ["provider"]) ? ` with ${firstString(output, ["provider"])}` : ""}.`);
      if (typeof output.duration_ms === "number") lines.push(`Audio duration: ${Math.round(output.duration_ms / 1000)} seconds.`);
      break;
    case "caption_agent":
      if (typeof output.phrase_count === "number" || typeof output.word_count === "number") {
        lines.push(`Built captions with ${output.phrase_count || 0} phrases and ${output.word_count || 0} words.`);
      }
      break;
    case "timed_visual_agent": {
      const cueCount = Array.isArray(logs.output_json) ? logs.output_json.length : arrayLength(output.timed_visual_cues);
      if (cueCount) lines.push(`Created ${cueCount} timed visual cue${cueCount === 1 ? "" : "s"}.`);
      break;
    }
    case "music_agent":
      if (brief) lines.push(brief);
      if (typeof output.duration_ms === "number") lines.push(`Final audio duration: ${Math.round(output.duration_ms / 1000)} seconds.`);
      if (firstString(output, ["music_path"])) lines.push(`Music: ${fileName(firstString(output, ["music_path"]))}`);
      break;
    case "render_agent":
      if (firstString(output, ["video_path"])) lines.push(`Rendered video: ${fileName(firstString(output, ["video_path"]))}`);
      if (typeof output.duration_seconds === "number") lines.push(`Duration: ${Math.round(output.duration_seconds)} seconds.`);
      break;
    case "thumbnail_agent": {
      const textLines = summarizeStringList(output.text_lines);
      if (textLines) lines.push(`Thumbnail text: ${textLines}`);
      break;
    }
    default:
      if (title) lines.push(`Title: ${title}`);
      if (hook) lines.push(`Hook: ${hook}`);
      if (brief) lines.push(brief);
      if (narration) lines.push(narration);
      break;
  }

  if (logs.error_message) lines.push(`Error: ${logs.error_message}`);
  if (lines.length) return clampHumanText(lines.join("\n"));
  return clampHumanText(formatLogValue(logs.output_json));
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function firstString(record: Record<string, unknown> | null, keys: string[]): string {
  if (!record) return "";
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return "";
}

function summarizeCueList(value: unknown, key: string): string {
  if (!Array.isArray(value)) return "";
  return summarizeStringList(
    value
      .map((item) => {
        const record = asRecord(item);
        return firstString(record, [key, "keyword", "search_query", "trigger_word", "text"]);
      })
      .filter(Boolean)
  );
}

function summarizeCandidateList(value: unknown): string {
  if (!Array.isArray(value)) return "";
  return summarizeStringList(
    value
      .map((item) => {
        const record = asRecord(item);
        const topic = firstString(record, ["topic"]);
        const angle = firstString(record, ["angle"]);
        return [topic, angle].filter(Boolean).join(" - ");
      })
      .filter(Boolean)
  );
}

function summarizeStringList(value: unknown): string {
  if (!Array.isArray(value)) return "";
  return value
    .map((item) => {
      if (typeof item === "string") return item.trim();
      const record = asRecord(item);
      return firstString(record, ["title", "snippet", "url", "source", "text", "query"]);
    })
    .filter(Boolean)
    .slice(0, 5)
    .join("; ");
}

function arrayLength(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

function fileName(value: string): string {
  return value.split(/[\\/]/).filter(Boolean).pop() || value;
}

function clampHumanText(value: string): string {
  const clean = value.replace(/\n{3,}/g, "\n\n").trim();
  return clean.length > maxHumanLogLength ? `${clean.slice(0, maxHumanLogLength).trim()}...` : clean;
}

function formatLogValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "No logs yet.";
  if (Array.isArray(value) && value.length === 0) return "No logs yet.";
  if (typeof value === "string") return value.trim() || "No logs yet.";
  return JSON.stringify(value, null, 2) || "No logs yet.";
}

function LogBlock({ title, value }: { title: string; value: unknown }) {
  const text = formatLogValue(value);
  return (
    <details className="logBlock">
      <summary>{title}</summary>
      <pre>{text}</pre>
    </details>
  );
}

function JobPreview({ job }: { job: Job }) {
  const [url, setUrl] = useState("");
  const [previewError, setPreviewError] = useState("");
  useEffect(() => {
    setUrl("");
    setPreviewError("");
    if (job.status !== "succeeded" || !job.preview_url) {
      if (job.status === "succeeded") setPreviewError("No preview URL is available for this video yet.");
      return;
    }
    let objectUrl = "";
    let cancelled = false;
    window.desktopApi.config()
      .then(async (config) => {
        const response = await fetch(apiAssetUrl(config.apiBase, job.preview_url || ""), {
          headers: { Authorization: `Bearer ${window.desktopApi.token.get()}` }
        });
        if (!response.ok) throw new Error(`Preview request failed with ${response.status}`);
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        if (!cancelled) setUrl(objectUrl);
      })
      .catch((err) => {
        if (!cancelled) setPreviewError(errorMessage(err));
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [job.preview_url, job.status]);

  if (url) return <video className="sampleVideo" src={url} controls autoPlay playsInline />;
  return (
    <div className="samplePlaceholder">
      {previewError ? <Film size={28} /> : <Loader2 className="spin" size={28} />}
      <span>{previewError || "Loading video..."}</span>
    </div>
  );
}

function VideoPreviewButton({ job, variant = "icon" }: { job: Job; variant?: "icon" | "text" }) {
  const [open, setOpen] = useState(false);
  const disabled = job.status !== "succeeded" || !job.preview_url;

  return (
    <>
      <button
        className={variant === "text" ? "secondaryButton" : "iconButton"}
        title={disabled ? "Video is available after render succeeds" : "Play video"}
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        <Play size={16} />
        {variant === "text" ? "Play" : null}
      </button>
      {open ? <VideoPreviewModal job={job} onClose={() => setOpen(false)} /> : null}
    </>
  );
}

function VideoPreviewModal({ job, onClose }: { job: Job; onClose: () => void }) {
  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div
      className="modalOverlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose();
      }}
    >
      <section className="stageModal videoModal" role="dialog" aria-modal="true" aria-label="Video preview">
        <header className="stageModalHead">
          <div>
            <span className="eyebrow">Video preview</span>
            <h2>{job.topic}</h2>
            <p>{job.status} · {job.genre}</p>
          </div>
          <div className="stageModalActions">
            <DownloadButton job={job} />
            <button className="iconButton" title="Close" onClick={onClose}><X size={16} /></button>
          </div>
        </header>
        <div className="videoModalBody">
          <JobPreview job={job} />
        </div>
      </section>
    </div>
  );
}

function DownloadButton({ job, variant = "icon" }: { job: Job; variant?: "icon" | "text" }) {
  const disabled = job.status !== "succeeded" || !job.download_url;

  async function download() {
    if (disabled || !job.download_url) return;
    const config = await window.desktopApi.config();
    const response = await fetch(apiAssetUrl(config.apiBase, job.download_url), {
      headers: { Authorization: `Bearer ${window.desktopApi.token.get()}` }
    });
    if (!response.ok) return;
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${job.topic.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").slice(0, 80) || "video"}.mp4`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <button className={variant === "text" ? "secondaryButton" : "iconButton"} title="Download video" disabled={disabled} onClick={() => void download()}>
      <Download size={16} />
      {variant === "text" ? "Download" : null}
    </button>
  );
}
