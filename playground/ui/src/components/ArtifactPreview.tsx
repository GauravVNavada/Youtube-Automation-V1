import { ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";
import type { Artifact } from "../types";
import { compactPath, formatBytes } from "../utils/format";
import { Button } from "./ui/button";

const PLAYGROUND_BASE = "/api/playground";

export function ArtifactPreview({ artifact }: { artifact: Artifact }) {
  const [text, setText] = useState("");
  const url = `${PLAYGROUND_BASE}/artifacts/${artifact.id}`;

  useEffect(() => {
    if (!["json", "text"].includes(artifact.kind)) return;
    let cancelled = false;
    fetch(url)
      .then((response) => response.text())
      .then((value) => {
        if (!cancelled) setText(value);
      })
      .catch(() => {
        if (!cancelled) setText("Unable to load preview.");
      });
    return () => {
      cancelled = true;
    };
  }, [artifact.id, artifact.kind, url]);

  return (
    <article className="grid min-h-44 grid-rows-[auto_minmax(0,1fr)] rounded-md border border-slate-200 bg-slate-50 p-2.5 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-2 grid grid-cols-[minmax(0,1fr)_32px] items-start gap-2">
        <span className="min-w-0">
          <strong className="block truncate text-xs text-slate-950 dark:text-slate-50" title={compactPath(artifact.path)}>{compactPath(artifact.path)}</strong>
          <small className="mt-0.5 block text-xs text-slate-500">
            {artifact.kind} · {formatBytes(artifact.size_bytes)}
          </small>
        </span>
        <Button asChild variant="secondary" size="icon" aria-label={`Open ${compactPath(artifact.path)}`} title={`Open ${compactPath(artifact.path)}`}>
          <a href={url} target="_blank" rel="noreferrer">
            <ExternalLink className="h-4 w-4" />
          </a>
        </Button>
      </div>
      {artifact.kind === "image" ? <img className="block h-32 w-full rounded-md bg-slate-950 object-contain" src={url} alt={compactPath(artifact.path)} /> : null}
      {artifact.kind === "audio" ? <audio className="mt-8 w-full" controls src={url} /> : null}
      {artifact.kind === "video" ? <video className="block h-32 w-full rounded-md bg-slate-950 object-contain" controls src={url} /> : null}
      {["json", "text"].includes(artifact.kind) ? (
        <pre className="h-32 overflow-hidden rounded-md bg-slate-950 p-2 font-mono text-[11px] leading-5 text-slate-100">{text || "Loading..."}</pre>
      ) : null}
    </article>
  );
}
