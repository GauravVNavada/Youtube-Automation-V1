export type User = {
  id: number;
  email: string;
  display_name: string;
};

export type Entitlement = {
  active: boolean;
  source: "subscription" | "lifetime" | "none";
  status: string;
  plan_code: string;
  expires_at: string | null;
};

export type Genre = {
  genre_id: string;
  display_name: string;
  category: string;
  tone: string;
  default_duration_sec: number;
  recommended_score: number;
};

export type OnboardingState = {
  user_id: number;
  step: string;
  api_setup_complete: boolean;
  genre_id: string;
  user_intent: string;
  calibration_status: string;
  selected_sample_job_id: string;
  active_chat_id: string;
  completed: boolean;
  completed_at: string | null;
};

export type Chat = {
  id: string;
  title: string;
  context_summary: string;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: number;
  chat_id: string;
  role: "user" | "assistant";
  content: string;
  message_metadata: Record<string, unknown>;
  created_at: string;
};

export type ChatReply = {
  message: Message;
  job_id: string | null;
};

export type Job = {
  id: string;
  user_id: number;
  chat_id: string;
  status: string;
  topic: string;
  genre: string;
  duration: number;
  notes: string;
  settings: Record<string, unknown>;
  parent_job_id: string;
  job_type: string;
  created_at: string;
  updated_at: string;
  download_url?: string | null;
  preview_url?: string | null;
  shorts_cover_url?: string | null;
  youtube_thumbnail_url?: string | null;
};

export type Progress = {
  job_id: string;
  status: string;
  percent: number;
  current_agent: string;
  error_message: string;
  agents: { name: string; label: string; status: string; message: string }[];
};

export type StageLogs = {
  job_id: string;
  stage_name: string;
  label: string;
  status: string;
  message: string;
  events: Record<string, unknown>[];
  input_json: unknown;
  output_json: unknown;
  error_json: Record<string, unknown> | null;
  error_message: string;
  stdout_lines: string[];
};

export type ApiKeyStatus = {
  provider: string;
  status: string;
  source: string;
  model: string;
  last_tested_at: string | null;
};

export type ApiSetup = {
  required: Record<string, boolean>;
  statuses: ApiKeyStatus[];
  llm_options: { provider: string; label: string; default_model: string; configured: boolean }[];
};
