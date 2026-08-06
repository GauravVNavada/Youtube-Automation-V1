import { Braces, FileText, ListTree, Radio, RefreshCw, SlidersHorizontal, TerminalSquare } from "lucide-react";
import { useEffect, useState } from "react";
import type { PlaygroundSettings, Stage } from "../types";
import { formatDate, titleize } from "../utils/format";
import { ArtifactPreview } from "./ArtifactPreview";
import { StatusBadge } from "./ui/badge";
import { Button } from "./ui/button";
import { Checkbox } from "./ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Textarea } from "./ui/input";
import { Field, Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";

type TabId = "overview" | "controls" | "input" | "prompt" | "output" | "logs" | "artifacts";

const tabs: { id: TabId; label: string; icon: typeof ListTree }[] = [
  { id: "overview", label: "Overview", icon: ListTree },
  { id: "controls", label: "Controls", icon: SlidersHorizontal },
  { id: "input", label: "Input", icon: Braces },
  { id: "prompt", label: "Prompt", icon: FileText },
  { id: "output", label: "Output", icon: Braces },
  { id: "logs", label: "Logs", icon: TerminalSquare },
  { id: "artifacts", label: "Files", icon: Radio }
];

type StageDetailProps = {
  stage: Stage | undefined;
  settings: PlaygroundSettings;
  canRerun: boolean;
  rerunPending: boolean;
  onOpenMusic: () => void;
  onRerun: (stage: Stage, message: string, settingsPatch: Partial<PlaygroundSettings>, forcedAgentInstructions?: Record<string, string>) => void;
};

export function StageDetail({ stage, settings, canRerun, rerunPending, onOpenMusic, onRerun }: StageDetailProps) {
  const [tab, setTab] = useState<TabId>("overview");
  const [rerunMessage, setRerunMessage] = useState("");
  const [instructionPreset, setInstructionPreset] = useState("");
  const [draftSettings, setDraftSettings] = useState<PlaygroundSettings>(settings);

  useEffect(() => {
    setDraftSettings(settings);
    setRerunMessage("");
    setInstructionPreset("");
  }, [stage?.id]);

  if (!stage) return <Card className="grid h-full min-h-0 place-items-center text-sm text-slate-500">Select a stage.</Card>;
  const selectedPreset = stagePresets(stage.id).find((preset) => preset.value === instructionPreset);
  const forcedInstruction = selectedPreset?.instruction || "";
  const updateDraftSettings = (patch: Partial<PlaygroundSettings>) => setDraftSettings((current) => ({ ...current, ...patch }));
  const resetDraftSettings = () => setDraftSettings(settings);
  const runWithControls = () => {
    const forced = forcedInstruction ? { [stage.agent_name || stage.id]: forcedInstruction } : undefined;
    onRerun(stage, rerunMessage, draftSettings, forced);
  };

  return (
    <Card className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden">
      <CardHeader className="p-3">
        <div>
          <span className="mb-1 block text-xs font-bold uppercase text-slate-500">Selected stage</span>
          <CardTitle>{titleize(stage.agent_name)}</CardTitle>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={stage.status} />
          <Button
            disabled={!canRerun || rerunPending}
            onClick={runWithControls}
            title={canRerun ? "Rerun this agent with current parameters" : "Wait for the run to finish before rerunning an agent"}
          >
            <RefreshCw className="h-4 w-4" />
            <span>{rerunPending ? "Rerunning" : "Rerun agent"}</span>
          </Button>
        </div>
      </CardHeader>

      <CardContent className="min-h-0 overflow-hidden p-3 pt-0">
        <Tabs className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)]" value={tab} onValueChange={(value) => setTab(value as TabId)}>
          <TabsList>
            {tabs.map((item) => {
              const Icon = item.icon;
              return (
                <TabsTrigger value={item.id} key={item.id}>
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  <span>{item.label}</span>
                </TabsTrigger>
              );
            })}
          </TabsList>

          <TabsContent className="min-h-0 overflow-auto" value="overview">
            <div className="grid grid-cols-2 gap-2.5">
              <div className="col-span-full rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div>
                    <span className="block text-xs font-semibold uppercase text-slate-500">Agent rerun</span>
                    <strong className="text-sm text-slate-950 dark:text-slate-50">Use this node's parameters</strong>
                  </div>
                  <Button variant="secondary" size="sm" disabled={!canRerun || rerunPending} onClick={runWithControls}>
                    <RefreshCw className="h-4 w-4" />
                    {rerunPending ? "Starting" : "Rerun"}
                  </Button>
                </div>
                <Textarea
                  className="min-h-20 resize-none"
                  value={rerunMessage}
                  onChange={(event) => setRerunMessage(event.target.value)}
                  placeholder="Optional rerun note for this agent..."
                />
                {!canRerun ? <small className="mt-2 block text-xs font-semibold text-slate-500">Rerun becomes available after the current run finishes.</small> : null}
              </div>
              <Info label="Mode" value={titleize(stage.execution_mode)} />
              <Info label="Started" value={formatDate(stage.started_at) || "Not started"} />
              <Info label="Completed" value={formatDate(stage.completed_at) || "Not completed"} />
              <Info label="Updated" value={formatDate(stage.updated_at) || "Not available"} />
              <Info label="Error" value={stage.error_text || "None"} wide />
            </div>
          </TabsContent>

          <TabsContent className="min-h-0 overflow-auto" value="controls">
            <StageControls
              stage={stage}
              settings={draftSettings}
              instructionPreset={instructionPreset}
              rerunMessage={rerunMessage}
              canRerun={canRerun}
              rerunPending={rerunPending}
              onInstructionPresetChange={setInstructionPreset}
              onRerunMessageChange={setRerunMessage}
              onSettingsChange={updateDraftSettings}
              onSettingsReset={resetDraftSettings}
              onOpenMusic={onOpenMusic}
              onRerun={runWithControls}
            />
          </TabsContent>

          <TabsContent className="min-h-0 overflow-auto" value="input">
            <JsonBlock value={stage.input_json} />
          </TabsContent>
          <TabsContent className="min-h-0 overflow-auto" value="prompt">
            <pre className="max-h-full overflow-auto rounded-md border border-slate-800 bg-slate-950 p-3 font-mono text-xs leading-6 text-slate-100">{stage.prompt_text || "No prompt captured."}</pre>
          </TabsContent>
          <TabsContent className="min-h-0 overflow-auto" value="output">
            <JsonBlock value={stage.output_json} />
          </TabsContent>
          <TabsContent className="min-h-0 overflow-auto" value="logs">
            <LogList stage={stage} />
          </TabsContent>
          <TabsContent className="min-h-0 overflow-auto" value="artifacts">
            <ArtifactList stage={stage} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function StageControls({
  stage,
  settings,
  instructionPreset,
  rerunMessage,
  canRerun,
  rerunPending,
  onInstructionPresetChange,
  onRerunMessageChange,
  onSettingsChange,
  onSettingsReset,
  onOpenMusic,
  onRerun
}: {
  stage: Stage;
  settings: PlaygroundSettings;
  instructionPreset: string;
  rerunMessage: string;
  canRerun: boolean;
  rerunPending: boolean;
  onInstructionPresetChange: (value: string) => void;
  onRerunMessageChange: (value: string) => void;
  onSettingsChange: (patch: Partial<PlaygroundSettings>) => void;
  onSettingsReset: () => void;
  onOpenMusic: () => void;
  onRerun: () => void;
}) {
  const groups = controlsForStage(stage.id);
  const presets = stagePresets(stage.id);
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900">
        <div>
          <span className="block text-xs font-bold uppercase text-slate-500">Node parameters</span>
          <strong className="text-sm text-slate-950 dark:text-slate-50">{titleize(stage.agent_name)} rerun controls</strong>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onSettingsReset}>Reset</Button>
          <Button size="sm" disabled={!canRerun || rerunPending} onClick={onRerun}>
            <RefreshCw className="h-4 w-4" />
            {rerunPending ? "Starting" : "Rerun node"}
          </Button>
        </div>
      </div>

      {presets.length ? (
        <Field>
          <Label>Agent instruction preset</Label>
          <Select value={instructionPreset || "none"} onValueChange={(value) => onInstructionPresetChange(value === "none" ? "" : value)}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No preset</SelectItem>
              {presets.map((preset) => <SelectItem key={preset.value} value={preset.value}>{preset.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
      ) : null}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
        {groups.duration ? <DurationControl settings={settings} onChange={onSettingsChange} /> : null}
        {groups.script ? (
          <>
            <RangeField label="Voice speed" value={settings.voice_speed} min={0.65} max={1.4} step={0.01} suffix="x" onChange={(voice_speed) => onSettingsChange({ voice_speed })} />
            <RangeField label="Caption words" value={settings.caption_words} min={1} max={8} step={1} suffix="words" onChange={(caption_words) => onSettingsChange({ caption_words })} />
          </>
        ) : null}
        {groups.visuals ? (
          <>
            <RangeField label="Images / assets" value={settings.image_count} min={1} max={24} step={1} suffix="assets" onChange={(image_count) => onSettingsChange({ image_count })} />
            <RangeField label="Min visual segment" value={settings.min_visual_segment_ms} min={1200} max={8000} step={100} suffix="ms" onChange={(min_visual_segment_ms) => onSettingsChange({ min_visual_segment_ms })} />
          </>
        ) : null}
        {groups.audio ? (
          <>
            <RangeField label="Voice speed" value={settings.voice_speed} min={0.65} max={1.4} step={0.01} suffix="x" onChange={(voice_speed) => onSettingsChange({ voice_speed })} />
            <RangeField label="Music volume" value={settings.music_volume} min={0} max={0.8} step={0.01} display={`${Math.round(settings.music_volume * 100)}%`} onChange={(music_volume) => onSettingsChange({ music_volume })} />
          </>
        ) : null}
        {groups.music ? (
          <div className="rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900">
            <Label>Music source</Label>
            <Button className="mt-3 w-full" variant="secondary" onClick={onOpenMusic}>Choose music</Button>
            <RangeField className="mt-3" label="Music volume" value={settings.music_volume} min={0} max={0.8} step={0.01} display={`${Math.round(settings.music_volume * 100)}%`} onChange={(music_volume) => onSettingsChange({ music_volume })} />
          </div>
        ) : null}
        {groups.render ? (
          <>
            <ToggleControl label="Visual motion" checked={settings.visual_motion} onChange={(visual_motion) => onSettingsChange({ visual_motion })} />
            <SelectField label="Transition" value={settings.transition_style} options={["slide", "fade", "wipe", "cut"]} onValueChange={(transition_style) => onSettingsChange({ transition_style: transition_style as PlaygroundSettings["transition_style"] })} />
            <SelectField label="Zoom" value={settings.zoom_variant} options={["mixed", "center_in", "center_out", "still"]} onValueChange={(zoom_variant) => onSettingsChange({ zoom_variant: zoom_variant as PlaygroundSettings["zoom_variant"] })} />
            <RangeField label="Transition time" value={settings.transition_seconds} min={0} max={1.2} step={0.05} suffix="s" onChange={(transition_seconds) => onSettingsChange({ transition_seconds })} />
          </>
        ) : null}
      </div>

      <Field>
        <Label>Extra rerun note</Label>
        <Textarea className="min-h-20 resize-none" value={rerunMessage} onChange={(event) => onRerunMessageChange(event.target.value)} placeholder="Optional note only for this node rerun..." />
      </Field>
    </div>
  );
}

function controlsForStage(stageId: string) {
  if (["desktop_master_agent", "parameter_agent", "master_agent"].includes(stageId)) {
    return { duration: true, script: true, visuals: true, audio: true, music: true, render: true };
  }
  return {
    duration: ["style_sampler_agent", "script_agent", "audio_agent", "render_agent"].includes(stageId),
    script: ["style_sampler_agent", "topic_discovery_agent", "research_agent", "script_agent", "validation_agent"].includes(stageId),
    visuals: ["timed_visual_agent", "asset_agent", "thumbnail_agent"].includes(stageId),
    audio: ["audio_agent", "caption_agent"].includes(stageId),
    music: ["music_agent"].includes(stageId),
    render: ["render_agent", "final_output"].includes(stageId)
  };
}

function stagePresets(stageId: string) {
  const common = [{ value: "strict", label: "Strictly follow current controls", instruction: "Strictly follow the current playground controls and do not invent alternate duration, caption, visual, or audio settings." }];
  const byStage: Record<string, { value: string; label: string; instruction: string }[]> = {
    script_agent: [
      { value: "more_twists", label: "More twists", instruction: "Rewrite with stronger retention: open loop, one mid-script twist, one surprise reveal, and a complete ending." },
      { value: "shorter", label: "Tighter script", instruction: "Make the narration tighter and easier to finish within the selected duration." }
    ],
    asset_agent: [
      { value: "literal_assets", label: "More literal assets", instruction: "Prefer concrete, literal, subject-matching assets over atmospheric or vague visuals." }
    ],
    timed_visual_agent: [
      { value: "faster_visuals", label: "Faster visual pacing", instruction: "Use quicker visual changes while keeping every visual cue readable and relevant." }
    ],
    audio_agent: [
      { value: "clearer_voice", label: "Clearer voice", instruction: "Prioritize clear narration timing and avoid long pauses." }
    ],
    caption_agent: [
      { value: "punchier_captions", label: "Punchier captions", instruction: "Keep captions short, punchy, and easy to read at Shorts speed." }
    ],
    music_agent: [
      { value: "lower_music", label: "Lower music bed", instruction: "Keep music supportive and never let it cover narration." }
    ],
    render_agent: [
      { value: "clean_render", label: "Cleaner render", instruction: "Prioritize clean transitions, no visual clutter, and exact requested duration." }
    ]
  };
  return [...(byStage[stageId] || []), ...common];
}

function DurationControl({ settings, onChange }: { settings: PlaygroundSettings; onChange: (patch: Partial<PlaygroundSettings>) => void }) {
  return (
    <Field>
      <Label>Duration</Label>
      <div className="grid grid-cols-3 gap-2">
        {[30, 45, 60].map((value) => (
          <Button key={value} variant={settings.duration === value ? "default" : "secondary"} onClick={() => onChange({ duration: value })}>{value}s</Button>
        ))}
      </div>
    </Field>
  );
}

function RangeField({ className = "", label, value, min, max, step, suffix = "", display, onChange }: { className?: string; label: string; value: number; min: number; max: number; step: number; suffix?: string; display?: string; onChange: (value: number) => void }) {
  return (
    <Field className={className}>
      <div className="flex items-center justify-between gap-3">
        <Label>{label}</Label>
        <span className="text-xs font-bold text-cyan-800 dark:text-cyan-300">{display || `${value}${suffix ? ` ${suffix}` : ""}`}</span>
      </div>
      <input className="h-2 w-full accent-cyan-700" type="range" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </Field>
  );
}

function SelectField({ label, value, options, onValueChange }: { label: string; value: string; options: string[]; onValueChange: (value: string) => void }) {
  return (
    <Field>
      <Label>{label}</Label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger><SelectValue /></SelectTrigger>
        <SelectContent>{options.map((option) => <SelectItem key={option} value={option}>{option.replaceAll("_", " ")}</SelectItem>)}</SelectContent>
      </Select>
    </Field>
  );
}

function ToggleControl({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="flex min-h-20 items-center justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm font-semibold dark:border-slate-800 dark:bg-slate-900">
      <span>{label}</span>
      <Checkbox checked={checked} onCheckedChange={(value) => onChange(value === true)} />
    </label>
  );
}

function Info({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={`min-h-16 rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900 ${wide ? "col-span-full" : ""}`}>
      <span className="block text-xs font-semibold text-slate-500">{label}</span>
      <strong className="mt-1.5 block text-sm leading-5 text-slate-950 [overflow-wrap:anywhere] dark:text-slate-50">{value}</strong>
    </div>
  );
}

function JsonBlock({ value }: { value: Record<string, unknown> }) {
  return <pre className="max-h-full overflow-auto rounded-md border border-slate-800 bg-slate-950 p-3 font-mono text-xs leading-6 text-slate-100">{JSON.stringify(value || {}, null, 2)}</pre>;
}

function LogList({ stage }: { stage: Stage }) {
  if (!stage.events?.length) return <div className="grid min-h-20 place-items-center rounded-md border border-dashed border-slate-300 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">No logs captured.</div>;
  return (
    <div className="grid gap-3">
      {stage.events.map((event) => (
        <article className={`rounded-md border p-3 ${event.level === "error" ? "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950" : "border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900"}`} key={event.id}>
          <header className="mb-2 flex items-center justify-between gap-3">
            <strong>{formatDate(event.timestamp)}</strong>
            <span className="text-xs font-bold text-slate-500">{event.level}</span>
          </header>
          <p className="mb-2 text-sm leading-5 text-slate-800 dark:text-slate-200">{event.message}</p>
          <pre className="max-h-80 overflow-auto rounded-md bg-slate-950 p-3 font-mono text-xs leading-5 text-slate-100">{JSON.stringify(event.payload_json || {}, null, 2)}</pre>
        </article>
      ))}
    </div>
  );
}

function ArtifactList({ stage }: { stage: Stage }) {
  if (!stage.artifacts?.length) return <div className="grid min-h-20 place-items-center rounded-md border border-dashed border-slate-300 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">No files captured.</div>;
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-2.5">
      {stage.artifacts.map((artifact) => (
        <ArtifactPreview artifact={artifact} key={artifact.id} />
      ))}
    </div>
  );
}
