import { History, Music2, Pause, Play, Plus, Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { Genre, LlmOption, MusicAsset } from "../types";
import { formatPercent } from "../utils/format";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Input } from "./ui/input";
import { Field, Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

type RunComposerProps = {
  genres: Genre[];
  llmOptions: LlmOption[];
  music: MusicAsset | undefined;
  musicItems: MusicAsset[];
  musicVolume: number;
  runCount: number;
  genreId: string;
  provider: string;
  model: string;
  apiKey: string;
  selectedMusicId: string;
  onGenreChange: (value: string) => void;
  onProviderChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onApiKeyChange: (value: string) => void;
  onSelectMusicTemplate: (item: MusicAsset | undefined) => void;
  onMusicVolumeChange: (value: number) => void;
  onOpenMusic: () => void;
  onOpenRuns: () => void;
  onNewChat: () => void;
};

export function RunComposer({
  genres,
  llmOptions,
  music,
  musicItems,
  musicVolume,
  runCount,
  genreId,
  provider,
  model,
  apiKey,
  selectedMusicId,
  onGenreChange,
  onProviderChange,
  onModelChange,
  onApiKeyChange,
  onSelectMusicTemplate,
  onMusicVolumeChange,
  onOpenMusic,
  onOpenRuns,
  onNewChat
}: RunComposerProps) {
  const [previewUrl, setPreviewUrl] = useState("");
  const [isPlaying, setIsPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const selectedProvider = useMemo(() => llmOptions.find((item) => item.provider === provider), [llmOptions, provider]);
  const genreOptions = genres.map((genre) => ({ value: genre.genre_id, label: genre.display_name }));
  const providerOptions = llmOptions.map((item) => ({ value: item.provider, label: item.label }));
  const modelOptions = (selectedProvider?.models ?? []).map((value) => ({ value, label: value }));
  const templateMusic = useMemo(() => musicItems.filter((item) => item.source !== "upload"), [musicItems]);
  const selectedTemplateId = templateMusic.some((item) => item.id === selectedMusicId) ? selectedMusicId : undefined;
  const currentPreviewUrl = resolveAssetUrl(music?.url || "");
  const selectedIsPreviewing = Boolean(currentPreviewUrl && previewUrl === currentPreviewUrl && isPlaying);

  function selectTemplateById(value: string) {
    const item = templateMusic.find((template) => template.id === value);
    onSelectMusicTemplate(item);
    if (audioRef.current) {
      audioRef.current.pause();
      setIsPlaying(false);
    }
  }

  function togglePreview() {
    if (!currentPreviewUrl) return;
    if (previewUrl === currentPreviewUrl && audioRef.current && !audioRef.current.paused) {
      audioRef.current.pause();
      setIsPlaying(false);
      return;
    }
    setPreviewUrl(currentPreviewUrl);
    window.setTimeout(() => {
      void audioRef.current?.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false));
    }, 0);
  }

  return (
    <Card className="flex h-full flex-col rounded-none border-0 shadow-none">
      <CardHeader className="border-b border-slate-200 p-4 dark:border-slate-800">
        <div>
          <span className="mb-1 block text-xs font-bold uppercase text-slate-500">Agent</span>
          <CardTitle>Playground</CardTitle>
        </div>
        <Button variant="secondary" size="icon" aria-label="Open run history" title="Open run history" onClick={onOpenRuns}>
          <History className="h-4 w-4" />
        </Button>
      </CardHeader>

      <CardContent className="flex min-h-0 flex-1 flex-col p-4">
        <Button className="w-full" variant="secondary" onClick={onNewChat}>
          <Plus className="h-4 w-4" />
          <span>New Chat</span>
        </Button>
        <div className="mt-4 grid gap-3">
          <SelectControl label="Genre" value={genreId} onValueChange={onGenreChange} options={genreOptions} />
          <SelectControl label="Provider" value={provider} onValueChange={onProviderChange} options={providerOptions} />
          {provider !== "env" ? <SelectControl label="Model" value={model} onValueChange={onModelChange} options={modelOptions} placeholder="Model" /> : null}
          <Field>
            <Label>Run key</Label>
            <Input type="password" value={apiKey} onChange={(event) => onApiKeyChange(event.target.value)} placeholder="Optional for playground" />
          </Field>
        </div>

        <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900">
          <div className="grid min-h-10 grid-cols-[32px_minmax(0,1fr)_36px_auto] items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-md bg-white text-cyan-700 dark:bg-slate-950 dark:text-cyan-300">
              <Music2 className="h-4 w-4" />
            </span>
            <strong className="truncate text-sm text-slate-950 dark:text-slate-50">{music ? music.name : "No music selected"}</strong>
            <Button variant="ghost" size="icon" aria-label={selectedIsPreviewing ? "Pause music" : "Play music"} title={selectedIsPreviewing ? "Pause music" : "Play music"} disabled={!currentPreviewUrl} onClick={togglePreview}>
              {selectedIsPreviewing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" size="sm" onClick={onOpenMusic}>
              <Upload className="h-4 w-4" />
              Upload
            </Button>
          </div>

          <Field className="mt-3">
            <Label htmlFor="music-template-select">Music template</Label>
            <Select value={selectedTemplateId} onValueChange={selectTemplateById} disabled={!templateMusic.length}>
              <SelectTrigger id="music-template-select" aria-label="Choose music from static database" className="mt-1 bg-white dark:bg-slate-950">
                <SelectValue placeholder={templateMusic.length ? "Choose from static DB" : "No DB music found"} />
              </SelectTrigger>
              <SelectContent className="max-h-64">
                {templateMusic.map((item) => (
                  <SelectItem value={item.id} key={item.id}>
                    {item.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <small className="mt-1 block truncate text-xs text-slate-500 dark:text-slate-400">
              {templateMusic.length ? (music?.filename ? music.filename : `${templateMusic.length} DB templates loaded`) : "Static DB returned no music templates."}
            </small>
          </Field>

          <div className="mt-3 grid grid-cols-[minmax(0,1fr)_42px] items-center gap-3">
            <input
              className="h-2 w-full accent-cyan-700"
              type="range"
              min={0}
              max={0.8}
              step={0.01}
              value={musicVolume}
              onChange={(event) => onMusicVolumeChange(Number(event.target.value))}
              aria-label="Music volume"
            />
            <small className="text-right text-xs font-bold text-cyan-800 dark:text-cyan-300">{formatPercent(musicVolume)}</small>
          </div>
          {previewUrl ? (
            <audio
              ref={audioRef}
              className="sr-only"
              preload="metadata"
              src={previewUrl}
              onPlay={() => setIsPlaying(true)}
              onPause={() => setIsPlaying(false)}
              onEnded={() => setIsPlaying(false)}
            />
          ) : null}
        </div>

        <button className="mt-auto truncate text-left text-xs font-semibold text-slate-500 hover:text-cyan-800 dark:hover:text-cyan-300" type="button" onClick={onOpenRuns}>
          {runCount} recent runs
        </button>
      </CardContent>
    </Card>
  );
}

function resolveAssetUrl(path: string) {
  if (!path) return "";
  return path.startsWith("http") || path.startsWith("/") ? path : `/${path}`;
}

function SelectControl({
  label,
  value,
  onValueChange,
  options,
  placeholder = "Select"
}: {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
}) {
  return (
    <Field>
      <Label>{label}</Label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem value={option.value} key={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
}
