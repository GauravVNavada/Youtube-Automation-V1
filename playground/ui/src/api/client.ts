import type { CreateRunInput, Genre, LlmOption, MusicAsset, PlaygroundMusicUpload, PlaygroundRun, RunSummary, Stage, StageRerunInput } from "../types";

const PLAYGROUND_BASE = "/api/playground";
const ASSET_BASE = "/api/assets";

type RequestOptions = RequestInit & {
  json?: unknown;
};

async function request<T>(url: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  let body = options.body;
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  }

  const response = await fetch(url, {
    ...options,
    body,
    headers
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = typeof payload.detail === "string" ? payload.detail : `Request failed with ${response.status}`;
    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

export const api = {
  assetUrl(path: string): string {
    if (!path) return "";
    return path.startsWith("http") || path.startsWith("/") ? path : `/${path}`;
  },

  genres(): Promise<Genre[]> {
    return request<Genre[]>(`${PLAYGROUND_BASE}/genres`);
  },

  llmOptions(): Promise<LlmOption[]> {
    return request<LlmOption[]>(`${PLAYGROUND_BASE}/llm-options`);
  },

  runs(): Promise<RunSummary[]> {
    return request<RunSummary[]>(`${PLAYGROUND_BASE}/runs`);
  },

  run(id: string): Promise<PlaygroundRun> {
    return request<PlaygroundRun>(`${PLAYGROUND_BASE}/runs/${id}`);
  },

  stage(runId: string, stageId: string): Promise<Stage> {
    return request<Stage>(`${PLAYGROUND_BASE}/runs/${runId}/stages/${stageId}`);
  },

  createRun(input: CreateRunInput): Promise<PlaygroundRun> {
    return request<PlaygroundRun>(`${PLAYGROUND_BASE}/runs`, {
      method: "POST",
      json: input
    });
  },

  rerunStage(runId: string, stageId: string, input: StageRerunInput): Promise<PlaygroundRun> {
    return request<PlaygroundRun>(`${PLAYGROUND_BASE}/runs/${runId}/stages/${stageId}/rerun`, {
      method: "POST",
      json: input
    });
  },

  music(): Promise<MusicAsset[]> {
    return request<MusicAsset[]>(`${ASSET_BASE}/music`);
  },

  async uploadPlaygroundMusic(file: File): Promise<PlaygroundMusicUpload> {
    const form = new FormData();
    form.append("file", file);
    return request<PlaygroundMusicUpload>(`${PLAYGROUND_BASE}/music/uploads`, {
      method: "POST",
      body: form
    });
  }
};

export function isTerminal(status: string | undefined): boolean {
  return status === "succeeded" || status === "failed" || status === "skipped";
}
