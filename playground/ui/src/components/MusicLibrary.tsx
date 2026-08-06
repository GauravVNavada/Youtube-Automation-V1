import { FileMusic, Music2, Pause, Play, RefreshCw, Upload, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { MusicAsset, MusicSource, PlaygroundMusicUpload } from "../types";
import { compactPath, formatBytes } from "../utils/format";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Tabs, TabsList, TabsTrigger } from "./ui/tabs";

type MusicLibraryProps = {
  items: MusicAsset[];
  selectedId: string;
  source: MusicSource;
  uploadedMusic: PlaygroundMusicUpload | null;
  activeLabel: string;
  uploading: boolean;
  onSourceChange: (source: MusicSource) => void;
  onSelectTemplate: (item: MusicAsset | undefined) => void;
  onSelectUpload: () => void;
  onUpload: (file: File) => void;
  onClearUpload: () => void;
  onRefresh: () => void;
};

export function MusicLibrary({
  items,
  selectedId,
  source,
  uploadedMusic,
  activeLabel,
  uploading,
  onSourceChange,
  onSelectTemplate,
  onSelectUpload,
  onUpload,
  onClearUpload,
  onRefresh
}: MusicLibraryProps) {
  const [previewUrl, setPreviewUrl] = useState("");
  const [isPlaying, setIsPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const templateItems = useMemo(() => items.filter((item) => item.source !== "upload"), [items]);
  const selectedTemplate = useMemo(() => templateItems.find((item) => item.id === selectedId), [selectedId, templateItems]);
  const activeName = activeLabel || "No music selected";
  const selectedPreviewUrl = source === "upload" ? uploadedMusic?.url || "" : selectedTemplate?.url || "";
  const selectedIsPreviewing = Boolean(selectedPreviewUrl && previewUrl === api.assetUrl(selectedPreviewUrl) && isPlaying);

  function pickFile(fileList: FileList | null) {
    const file = fileList?.item(0);
    if (file) onUpload(file);
    if (inputRef.current) inputRef.current.value = "";
  }

  function preview(url: string) {
    const resolved = api.assetUrl(url);
    if (!resolved) return;
    if (previewUrl === resolved && audioRef.current && !audioRef.current.paused) {
      audioRef.current.pause();
      setIsPlaying(false);
      return;
    }
    setPreviewUrl(resolved);
    window.setTimeout(() => {
      void audioRef.current?.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false));
    }, 0);
  }

  function selectTemplateById(value: string) {
    const item = templateItems.find((template) => template.id === value);
    onSelectTemplate(item);
    if (audioRef.current) {
      audioRef.current.pause();
      setIsPlaying(false);
    }
  }

  return (
    <Card className="min-h-full rounded-none border-0 shadow-none">
      <CardHeader className="border-b border-slate-200 dark:border-slate-800">
        <div>
          <span className="mb-1 block text-xs font-bold uppercase text-slate-500">Music source</span>
          <CardTitle>Sound bed</CardTitle>
        </div>
        <Button variant="ghost" size="icon" aria-label="Refresh templates" title="Refresh templates" onClick={onRefresh}>
          <RefreshCw className="h-4 w-4" />
        </Button>
      </CardHeader>

      <CardContent className="space-y-5">
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900">
          <span className="block text-xs font-semibold uppercase text-slate-500">Selected</span>
          <div className="mt-2 grid grid-cols-[minmax(0,1fr)_40px] items-center gap-3">
            <strong className="block truncate text-sm text-slate-950 dark:text-slate-50">{activeName}</strong>
            <Button
              variant="ghost"
              size="icon"
              aria-label={selectedIsPreviewing ? "Pause selected music" : "Play selected music"}
              title={selectedIsPreviewing ? "Pause selected music" : "Play selected music"}
              disabled={!selectedPreviewUrl}
              onClick={() => preview(selectedPreviewUrl)}
            >
              {selectedIsPreviewing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </Button>
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

        <Tabs value={source} onValueChange={(value) => onSourceChange(value as MusicSource)}>
          <TabsList className="grid grid-cols-2 bg-slate-100">
            <TabsTrigger value="template">
              <FileMusic className="h-4 w-4" />
              <span>Templates</span>
            </TabsTrigger>
            <TabsTrigger value="upload">
              <Upload className="h-4 w-4" />
              <span>Own file</span>
            </TabsTrigger>
          </TabsList>
        </Tabs>

        {source === "template" ? (
          <div className="space-y-3">
            <div className="space-y-2">
              <label className="text-xs font-bold uppercase text-slate-500" htmlFor="template-music-select">
                Choose from static DB
              </label>
              <Select value={selectedId || undefined} onValueChange={selectTemplateById}>
                <SelectTrigger id="template-music-select" aria-label="Choose music from static database">
                  <SelectValue placeholder="Select template music" />
                </SelectTrigger>
                <SelectContent className="max-h-72">
                  {templateItems.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {selectedTemplate ? (
              <article className="grid grid-cols-[40px_minmax(0,1fr)_40px] items-center gap-3 rounded-md border border-cyan-700 bg-white p-3 shadow-[inset_3px_0_0_#0e7490] dark:bg-slate-900">
                <span className="grid h-10 w-10 place-items-center rounded-md bg-cyan-100 text-cyan-800">
                  <Music2 className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <strong className="block truncate text-sm text-slate-950 dark:text-slate-50">{selectedTemplate.name}</strong>
                  <small className="block truncate text-xs text-slate-500">
                    {selectedTemplate.mood || "template"} · {compactPath(selectedTemplate.filename)}
                  </small>
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`${selectedIsPreviewing ? "Pause" : "Play"} ${selectedTemplate.name}`}
                  title={`${selectedIsPreviewing ? "Pause" : "Play"} ${selectedTemplate.name}`}
                  onClick={() => preview(selectedTemplate.url)}
                >
                  {selectedIsPreviewing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                </Button>
              </article>
            ) : null}

            {!templateItems.length ? <EmptyState text="No template music in the static catalog." /> : null}
          </div>
        ) : (
          <div className="space-y-3">
            <button
              className="grid min-h-36 w-full place-items-center rounded-md border border-dashed border-slate-300 bg-slate-50 p-4 text-center transition hover:border-cyan-500 hover:bg-cyan-50 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800"
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={uploading}
            >
              <span className="grid h-11 w-11 place-items-center rounded-md bg-white text-cyan-700 shadow-sm dark:bg-slate-950 dark:text-cyan-300">
                <Upload className="h-5 w-5" />
              </span>
              <span className="mt-3 text-sm font-bold text-slate-900 dark:text-slate-50">{uploading ? "Uploading" : "Choose music file"}</span>
              <small className="mt-1 text-xs text-slate-500">MP3, WAV, M4A, AAC, OGG, FLAC</small>
            </button>
            <input ref={inputRef} className="sr-only" type="file" accept="audio/*" onChange={(event) => pickFile(event.target.files)} />

            {uploadedMusic ? (
              <article className={`grid grid-cols-[minmax(0,1fr)_40px_40px] items-center gap-2 rounded-md border bg-white p-3 dark:bg-slate-900 ${source === "upload" ? "border-cyan-700 shadow-[inset_3px_0_0_#0e7490]" : "border-slate-200 dark:border-slate-800"}`}>
                <button className="min-w-0 text-left" type="button" onClick={onSelectUpload}>
                  <strong className="block truncate text-sm text-slate-950 dark:text-slate-50">{uploadedMusic.name}</strong>
                  <small className="block truncate text-xs text-slate-500">
                    {compactPath(uploadedMusic.filename)} · {formatBytes(uploadedMusic.size_bytes)}
                  </small>
                </button>
                <Button variant="ghost" size="icon" aria-label={`Preview ${uploadedMusic.name}`} title={`Preview ${uploadedMusic.name}`} onClick={() => preview(uploadedMusic.url)}>
                  {selectedIsPreviewing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                </Button>
                <Button variant="ghost" size="icon" aria-label="Clear upload" title="Clear upload" onClick={onClearUpload}>
                  <X className="h-4 w-4" />
                </Button>
              </article>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="grid min-h-24 place-items-center rounded-md border border-dashed border-slate-300 bg-slate-50 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">{text}</div>;
}
