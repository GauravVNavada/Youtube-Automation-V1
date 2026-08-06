export type Genre = {
  genre_id: string;
  display_name: string;
  category?: string;
  tone?: string;
  default_duration_sec?: number;
  word_count_min?: number;
  word_count_max?: number;
  music_mood?: string;
  hook_patterns?: string[];
  banned_phrases?: string[];
  visual_style?: Record<string, unknown>;
  topic_rules?: Record<string, unknown>[];
  script_profile?: Record<string, unknown>;
};

export type LlmOption = {
  provider: string;
  label: string;
  models: string[];
  default_model: string;
};

export type MusicAsset = {
  id: string;
  name: string;
  description: string;
  tags: string[];
  mood: string;
  source: string;
  duration_ms: number;
  music_path: string;
  url: string;
  filename: string;
  size_bytes?: number;
};

export type PlaygroundMusicUpload = {
  id: string;
  name: string;
  filename: string;
  source: "playground_upload";
  music_path: string;
  url: string;
  size_bytes: number;
};

export type MusicSource = "template" | "upload";

export type RunSummary = {
  id: string;
  user_message: string;
  status: RunStatus;
  created_at: string;
  updated_at: string;
  error_text?: string;
};

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "skipped" | string;

export type PlaygroundRun = {
  id: string;
  user_message: string;
  effective_message: string;
  source_prompt: string;
  raw_user_message: string;
  parent_run_id: string;
  chat_history: ChatMessage[];
  intent: string;
  genre_id: string;
  duration: number;
  notes: string;
  settings_patch: Partial<PlaygroundSettings>;
  settings: PlaygroundSettings;
  music_path: string;
  agent_instructions: Record<string, string>;
  llm_provider: string;
  llm_model: string;
  status: RunStatus;
  route_summary: string;
  created_at: string;
  updated_at: string;
  pipeline_run_dir: string;
  stdout_path: string;
  returncode: number | null;
  stages: Stage[];
  thread_runs?: PlaygroundRun[];
};

export type PlaygroundSettings = {
  duration: number;
  voice_speed: number;
  caption_words: number;
  image_count: number;
  music_volume: number;
  min_visual_segment_ms: number;
  visual_motion: boolean;
  transition_style: "slide" | "fade" | "wipe" | "cut";
  transition_seconds: number;
  zoom_variant: "mixed" | "center_in" | "center_out" | "still";
  music_path: string;
};

export type Stage = {
  id: string;
  agent_name: string;
  execution_mode: "ai" | "hybrid" | "deterministic" | "fallback" | string;
  status: RunStatus;
  started_at: string;
  completed_at: string;
  updated_at: string;
  input_json: Record<string, unknown>;
  prompt_text: string;
  output_json: Record<string, unknown>;
  events: StageEvent[];
  artifacts: Artifact[];
  error_text: string;
};

export type StageEvent = {
  id: string;
  timestamp: string;
  level: "info" | "error" | string;
  message: string;
  payload_json: Record<string, unknown>;
};

export type ChatMessage = {
  role: "user" | "assistant" | string;
  content: string;
};

export type Artifact = {
  id: string;
  path: string;
  kind: "image" | "video" | "audio" | "json" | "text" | "file" | string;
  size_bytes: number;
  previewable: boolean;
};

export type CreateRunInput = {
  message: string;
  genre_id: string;
  duration: number;
  llm_provider: string;
  llm_model: string;
  llm_api_key: string;
  parent_run_id?: string;
  start_new_thread?: boolean;
  chat_history?: ChatMessage[];
  music_path: string;
  settings_patch: Partial<PlaygroundSettings>;
};

export type StageRerunInput = {
  message: string;
  music_path: string;
  settings_patch: Partial<PlaygroundSettings>;
  forced_agent_instructions?: Record<string, string>;
};

export const defaultSettings: PlaygroundSettings = {
  duration: 30,
  voice_speed: 1,
  caption_words: 4,
  image_count: 8,
  music_volume: 0.12,
  min_visual_segment_ms: 3500,
  visual_motion: true,
  transition_style: "slide",
  transition_seconds: 0.45,
  zoom_variant: "mixed",
  music_path: ""
};
