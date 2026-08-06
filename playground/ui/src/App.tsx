import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Database, Moon, RotateCcw, Send, Sparkles, Sun, X } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, isTerminal } from "./api/client";
import { MusicLibrary } from "./components/MusicLibrary";
import { RunComposer } from "./components/RunComposer";
import { RunHistory } from "./components/RunHistory";
import { StageDetail } from "./components/StageDetail";
import { StageGraph } from "./components/StageGraph";
import { StatusBadge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Textarea } from "./components/ui/input";
import { usePlaygroundStore } from "./store/playgroundStore";
import type { ChatMessage, MusicAsset, PlaygroundRun, PlaygroundSettings, Stage } from "./types";
import { formatDate } from "./utils/format";

export function App() {
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const [musicOpen, setMusicOpen] = useState(false);
  const [runsOpen, setRunsOpen] = useState(false);
  const [stageOpen, setStageOpen] = useState(false);
  const [selectedStageRunId, setSelectedStageRunId] = useState("");
  const [isComposingNewChat, setIsComposingNewChat] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [genreId, setGenreId] = useState("scary_stories");
  const [provider, setProvider] = useState("env");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const {
    activeRunId,
    selectedStageId,
    selectedMusicId,
    musicSource,
    uploadedMusic,
    messageDraft,
    settings,
    setActiveRunId,
    setSelectedStageId,
    setSelectedMusicId,
    setMusicSource,
    setUploadedMusic,
    setMessageDraft,
    updateSettings,
    resetSettings
  } = usePlaygroundStore();

  const genresQuery = useQuery({ queryKey: ["genres"], queryFn: api.genres, staleTime: 60_000 });
  const llmQuery = useQuery({ queryKey: ["llm-options"], queryFn: api.llmOptions, staleTime: 60_000 });
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 5000 });
  const musicQuery = useQuery({ queryKey: ["music"], queryFn: api.music, staleTime: 20_000 });
  const activeRunQuery = useQuery({
    queryKey: ["run", activeRunId],
    queryFn: () => api.run(activeRunId),
    enabled: Boolean(activeRunId && !isComposingNewChat),
    refetchInterval: (query) => (isTerminal(query.state.data?.status) ? false : 1500)
  });

  const createRun = useMutation({
    mutationFn: api.createRun,
    onSuccess: async (run) => {
      setError("");
      setIsComposingNewChat(false);
      setMessageDraft("");
      setActiveRunId(run.id);
      setSelectedStageRunId(run.id);
      setSelectedStageId(run.stages[0]?.id || "");
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.setQueryData(["run", run.id], run);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Run failed to start.")
  });

  const uploadMusic = useMutation({
    mutationFn: api.uploadPlaygroundMusic,
    onSuccess: (asset) => {
      setError("");
      setMusicSource("upload");
      setUploadedMusic(asset);
      setSelectedMusicId("");
      updateSettings({ music_path: asset.music_path });
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Music upload failed.")
  });

  const rerunStage = useMutation({
    mutationFn: ({
      runId,
      stageId,
      message,
      settingsPatch,
      forcedAgentInstructions
    }: {
      runId: string;
      stageId: string;
      message: string;
      settingsPatch: Partial<PlaygroundSettings>;
      forcedAgentInstructions?: Record<string, string>;
    }) =>
      api.rerunStage(runId, stageId, {
        message,
        music_path: selectedMusicPath(),
        settings_patch: {
          ...settingsPatch,
          music_path: selectedMusicPath()
        },
        forced_agent_instructions: forcedAgentInstructions
      }),
    onSuccess: async (run) => {
      setError("");
      setIsComposingNewChat(false);
      setActiveRunId(run.id);
      setSelectedStageRunId(run.id);
      setSelectedStageId(run.stages[0]?.id || "");
      setStageOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.setQueryData(["run", run.id], run);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Agent rerun failed.")
  });

  const runs = runsQuery.data ?? [];
  const musicItems = musicQuery.data ?? [];
  const activeRun = isComposingNewChat ? undefined : activeRunQuery.data;
  const threadRuns = useMemo(() => (activeRun ? (activeRun.thread_runs?.length ? activeRun.thread_runs : [activeRun]) : []), [activeRun]);
  const selectedMusic = useMemo(() => musicItems.find((item) => item.id === selectedMusicId), [musicItems, selectedMusicId]);
  const activeMusicPath = musicSource === "upload" ? uploadedMusic?.music_path || "" : selectedMusic?.music_path || "";
  const selectedStageRun = useMemo(() => threadRuns.find((run) => run.id === selectedStageRunId) || activeRun, [activeRun, selectedStageRunId, threadRuns]);
  const selectedStage = useMemo(() => {
    const stages = selectedStageRun?.stages ?? [];
    return stages.find((stage) => stage.id === selectedStageId) || stages[0];
  }, [selectedStageRun?.stages, selectedStageId]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.style.colorScheme = theme;
  }, [theme]);

  useEffect(() => {
    if (!isComposingNewChat && !activeRunId && runs[0]?.id) setActiveRunId(runs[0].id);
  }, [activeRunId, isComposingNewChat, runs, setActiveRunId]);

  useEffect(() => {
    if (activeRun?.id && !selectedStageRunId) setSelectedStageRunId(activeRun.id);
  }, [activeRun?.id, selectedStageRunId]);

  useEffect(() => {
    if (!selectedStageId && selectedStageRun?.stages?.[0]?.id) setSelectedStageId(selectedStageRun.stages[0].id);
  }, [selectedStageRun?.stages, selectedStageId, setSelectedStageId]);

  useEffect(() => {
    if (activeMusicPath && settings.music_path !== activeMusicPath) {
      updateSettings({ music_path: activeMusicPath });
    }
  }, [activeMusicPath, settings.music_path, updateSettings]);

  useEffect(() => {
    if (!activeMusicPath && settings.music_path) {
      updateSettings({ music_path: "" });
    }
  }, [activeMusicPath, settings.music_path, updateSettings]);

  function selectTemplateMusic(item: MusicAsset | undefined) {
    setMusicSource("template");
    setSelectedMusicId(item?.id || "");
    updateSettings({ music_path: item?.music_path || "" });
  }

  function selectUploadedMusic() {
    if (!uploadedMusic) return;
    setMusicSource("upload");
    setSelectedMusicId("");
    updateSettings({ music_path: uploadedMusic.music_path });
  }

  function clearUploadedMusic() {
    setUploadedMusic(null);
    if (musicSource === "upload") {
      setMusicSource("template");
      updateSettings({ music_path: selectedMusic?.music_path || "" });
    }
  }

  function selectedMusicLabel() {
    if (musicSource === "upload" && uploadedMusic) return uploadedMusic.name;
    if (selectedMusic) return selectedMusic.name;
    return "";
  }

  function selectedMusicPath() {
    if (musicSource === "upload" && uploadedMusic) return uploadedMusic.music_path;
    if (selectedMusic) return selectedMusic.music_path;
    return "";
  }

  function selectedMusicForComposer() {
    if (musicSource === "upload" && uploadedMusic) {
      return {
        id: uploadedMusic.id,
        name: uploadedMusic.name,
        description: "",
        tags: [],
        mood: "own file",
        source: uploadedMusic.source,
        duration_ms: 0,
        music_path: uploadedMusic.music_path,
        url: uploadedMusic.url,
        filename: uploadedMusic.filename,
        size_bytes: uploadedMusic.size_bytes
      };
    }
    return selectedMusic;
  }

  useEffect(() => {
    if (selectedMusic && musicSource === "template" && settings.music_path !== selectedMusic.music_path) {
      updateSettings({ music_path: selectedMusic.music_path });
    }
  }, [musicSource, selectedMusic, settings.music_path, updateSettings]);

  function createSettingsPatch(): Partial<PlaygroundSettings> {
    return {
      duration: settings.duration,
      voice_speed: settings.voice_speed,
      caption_words: settings.caption_words,
      image_count: settings.image_count,
      music_volume: settings.music_volume,
      min_visual_segment_ms: settings.min_visual_segment_ms,
      visual_motion: settings.visual_motion,
      transition_style: settings.transition_style,
      transition_seconds: settings.transition_seconds,
      zoom_variant: settings.zoom_variant,
      music_path: selectedMusicPath()
    };
  }

  function submitRun() {
    if (!messageDraft.trim() || createRun.isPending) return;
    const parentRunId = !isComposingNewChat ? activeRunId || activeRun?.id || "" : "";
    createRun.mutate({
      message: messageDraft.trim(),
      genre_id: genreId || genresQuery.data?.[0]?.genre_id || "scary_stories",
      duration: settings.duration,
      llm_provider: provider,
      llm_model: model,
      llm_api_key: apiKey,
      parent_run_id: parentRunId,
      start_new_thread: isComposingNewChat,
      chat_history: !isComposingNewChat && parentRunId ? buildOutgoingChatHistory(threadRuns, messageDraft.trim()) : [],
      music_path: selectedMusicPath(),
      settings_patch: createSettingsPatch()
    });
  }

  function newChat() {
    setIsComposingNewChat(true);
    setActiveRunId("");
    setSelectedStageRunId("");
    setSelectedStageId("");
    setMessageDraft("");
    setError("");
  }

  function refreshAll() {
    setError("");
    void queryClient.invalidateQueries({ queryKey: ["runs"] });
    void queryClient.invalidateQueries({ queryKey: ["music"] });
    if (activeRunId) void queryClient.invalidateQueries({ queryKey: ["run", activeRunId] });
  }

  return (
    <main className={`${theme === "dark" ? "dark" : ""} grid h-screen grid-cols-[minmax(340px,390px)_minmax(0,1fr)] overflow-hidden bg-slate-50 text-slate-950 dark:bg-slate-950 dark:text-slate-50`}>
      <aside className="min-h-0 border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
        <RunComposer
          genres={genresQuery.data ?? []}
          llmOptions={llmQuery.data ?? [{ provider: "env", label: "Docker / .env", models: [], default_model: "" }]}
          music={selectedMusicForComposer()}
          musicItems={musicItems}
          musicVolume={settings.music_volume}
          runCount={runs.length}
          genreId={genreId}
          provider={provider}
          model={model}
          apiKey={apiKey}
          selectedMusicId={selectedMusicId}
          onGenreChange={setGenreId}
          onProviderChange={setProvider}
          onModelChange={setModel}
          onApiKeyChange={setApiKey}
          onSelectMusicTemplate={selectTemplateMusic}
          onMusicVolumeChange={(value) => updateSettings({ music_volume: value })}
          onOpenMusic={() => setMusicOpen(true)}
          onOpenRuns={() => setRunsOpen(true)}
          onNewChat={newChat}
        />
      </aside>

      <section className="relative grid min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden bg-slate-50 dark:bg-slate-950">
        <header className="flex min-h-20 items-start justify-between gap-4 border-b border-slate-200 bg-slate-50 pb-4 dark:border-slate-800 dark:bg-slate-950">
          <div className="min-w-0 p-4 pb-0">
            <span className="mb-2 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-bold uppercase text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
              <Sparkles className="h-3.5 w-3.5" />
              Chat run
            </span>
            <h2 className="line-clamp-2 max-w-4xl text-xl font-bold leading-tight tracking-tight">{activeRun?.route_summary || "Ready to test the pipeline"}</h2>
            {activeRun ? <small className="mt-2 block text-xs text-slate-500 dark:text-slate-400">Updated {formatDate(activeRun.updated_at)}</small> : null}
          </div>
          <div className="flex items-center gap-2 p-4 pb-0">
            <StatusBadge status={activeRun?.status || "idle"} />
            <Button variant="secondary" size="icon" aria-label="Toggle theme" title="Toggle theme" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" size="icon" aria-label="Reset controls" title="Reset controls" onClick={resetSettings}>
              <RotateCcw className="h-4 w-4" />
            </Button>
            <Button size="icon" aria-label="Refresh data" title="Refresh data" onClick={refreshAll}>
              <Database className="h-4 w-4" />
            </Button>
          </div>
        </header>

        {error ? (
          <div className="absolute left-4 right-4 top-24 z-10 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-800 shadow-sm">
            <AlertTriangle className="h-4 w-4" />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="min-h-0 overflow-auto p-4">
          <div className="mx-auto grid max-w-6xl gap-4">
            {!activeRun ? (
              <ChatBubble role="assistant">
                <strong className="block text-sm text-slate-950 dark:text-slate-50">Tell me what video to make.</strong>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  Put duration, caption density, and image count directly in your message, for example: "Make a 45 second scary story with 3 words per caption and 12 images."
                </p>
              </ChatBubble>
            ) : (
              <>
                {threadRuns.map((run, index) => (
                  <Fragment key={run.id}>
                    <ChatBubble role="user">{run.raw_user_message || run.user_message}</ChatBubble>
                    <WorkflowCard
                      run={run}
                      index={index}
                      selectedStageId={selectedStageRunId === run.id ? selectedStage?.id || "" : ""}
                      onSelectStage={(stage) => {
                        setSelectedStageRunId(run.id);
                        setSelectedStageId(stage.id);
                        setStageOpen(true);
                      }}
                    />
                  </Fragment>
                ))}
              </>
            )}
          </div>
        </div>

        <form
          className="border-t border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950"
          onSubmit={(event) => {
            event.preventDefault();
            submitRun();
          }}
        >
          <div className="mx-auto grid max-w-6xl grid-cols-[minmax(0,1fr)_104px] items-end gap-3">
            <Textarea
              className="max-h-32 min-h-16 resize-none"
              value={messageDraft}
              onChange={(event) => setMessageDraft(event.target.value)}
              rows={2}
              placeholder="Type a video request or edit. Example: 45 seconds, 3 caption words, 12 images..."
            />
            <Button className="h-16" disabled={createRun.isPending || !messageDraft.trim()} type="submit">
              <Send className="h-4 w-4" />
              <span>{createRun.isPending ? "Starting" : "Send"}</span>
            </Button>
          </div>
        </form>

      </section>

      <Modal title="Sound Bed" open={musicOpen} onClose={() => setMusicOpen(false)} wide={false}>
        <MusicLibrary
          items={musicItems}
          selectedId={selectedMusicId}
          source={musicSource}
          uploadedMusic={uploadedMusic}
          activeLabel={selectedMusicLabel()}
          uploading={uploadMusic.isPending}
          onSourceChange={setMusicSource}
          onSelectTemplate={selectTemplateMusic}
          onSelectUpload={selectUploadedMusic}
          onUpload={(file) => uploadMusic.mutate(file)}
          onClearUpload={clearUploadedMusic}
          onRefresh={() => void musicQuery.refetch()}
        />
      </Modal>

      <Modal title="Recent Runs" open={runsOpen} onClose={() => setRunsOpen(false)} wide={false}>
        <RunHistory
          runs={runs}
          activeRunId={activeRunId}
          onSelect={(id) => {
            setIsComposingNewChat(false);
            setActiveRunId(id);
            setSelectedStageRunId(id);
            setSelectedStageId("");
            setRunsOpen(false);
          }}
          onRefresh={() => void runsQuery.refetch()}
        />
      </Modal>

      <Modal title={selectedStage ? selectedStage.agent_name.replaceAll("_", " ") : "Stage Details"} open={stageOpen} onClose={() => setStageOpen(false)} wide>
        <StageDetail
          stage={selectedStage}
          settings={selectedStageRun?.settings || settings}
          canRerun={Boolean(selectedStageRun?.id && selectedStageRun && isTerminal(selectedStageRun.status))}
          rerunPending={rerunStage.isPending}
          onOpenMusic={() => setMusicOpen(true)}
          onRerun={(stage, message, settingsPatch, forcedAgentInstructions) => {
            if (!selectedStageRun?.id) return;
            rerunStage.mutate({ runId: selectedStageRun.id, stageId: stage.id, message, settingsPatch, forcedAgentInstructions });
          }}
        />
      </Modal>
    </main>
  );
}

function buildOutgoingChatHistory(runs: PlaygroundRun[], nextMessage: string): ChatMessage[] {
  const history: ChatMessage[] = [];
  for (const run of runs) {
    const userMessage = run.raw_user_message || run.user_message;
    if (userMessage) history.push({ role: "user", content: userMessage });
    if (run.route_summary) history.push({ role: "assistant", content: run.route_summary });
  }
  history.push({ role: "user", content: nextMessage });
  return history.slice(-12);
}

function WorkflowCard({
  run,
  index,
  selectedStageId,
  onSelectStage
}: {
  run: PlaygroundRun;
  index: number;
  selectedStageId: string;
  onSelectStage: (stage: Stage) => void;
}) {
  return (
    <ChatBubble role="assistant">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <small className="mb-1 block text-xs font-bold uppercase text-slate-500 dark:text-slate-400">Workflow {index + 1}</small>
          <strong className="block text-sm text-slate-950 dark:text-slate-50">{run.route_summary || "Pipeline run"}</strong>
          <small className="mt-1 block text-xs text-slate-500 dark:text-slate-400">Updated {formatDate(run.updated_at)}. Click a stage to inspect files, logs, prompts, and outputs.</small>
        </div>
        <StatusBadge status={run.status} />
      </div>
      <div className="h-[520px] min-h-0 overflow-hidden">
        <StageGraph stages={run.stages || []} selectedStageId={selectedStageId} onSelect={onSelectStage} />
      </div>
    </ChatBubble>
  );
}

function ChatBubble({ role, children }: { role: "user" | "assistant"; children: ReactNode }) {
  const isUser = role === "user";
  return (
    <article className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[92%] rounded-md border p-4 shadow-sm ${
          isUser
            ? "border-cyan-700 bg-cyan-700 text-white"
            : "border-slate-200 bg-white text-slate-950 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-50"
        }`}
      >
        {children}
      </div>
    </article>
  );
}

function Modal({ title, open, onClose, children, wide = false }: { title: string; open: boolean; onClose: () => void; children: ReactNode; wide?: boolean }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/45 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={title}>
      <div className={`grid ${wide ? "h-[92vh] max-h-[92vh] max-w-[96vw]" : "max-h-[88vh] max-w-xl"} w-full grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-md border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950`}>
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <h2 className="text-lg font-bold capitalize text-slate-950 dark:text-slate-50">{title}</h2>
          <Button variant="ghost" size="icon" aria-label="Close modal" title="Close modal" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </header>
        <div className="min-h-0 overflow-auto">{children}</div>
      </div>
    </div>
  );
}
