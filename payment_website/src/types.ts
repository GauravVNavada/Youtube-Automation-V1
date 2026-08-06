export type User = {
  id: number;
  email: string;
  display_name: string;
  created_at: string;
};

export type BillingPlan = {
  code: string;
  label: string;
  kind: "subscription" | "lifetime";
  amount_paise: number;
  currency: string;
  interval: string;
  configured: boolean;
};

export type Checkout = {
  checkout_id: string;
  key_id: string;
  plan_code: string;
  label: string;
  kind: "subscription" | "lifetime";
  amount_paise: number;
  currency: string;
  order_id: string;
  subscription_id: string;
  prefill: Record<string, string>;
};

export type Entitlement = {
  active: boolean;
  source: "subscription" | "lifetime" | "none";
  status: string;
  plan_code: string;
  expires_at: string | null;
};

export type ApiKeyStatus = {
  provider: string;
  status: string;
  source: string;
  model: string;
  last_tested_at: string | null;
};

export type LlmOption = {
  provider: string;
  label: string;
  default_model: string;
  configured: boolean;
};

export type ApiSetup = {
  required: Record<string, boolean>;
  statuses: ApiKeyStatus[];
  llm_options: LlmOption[];
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
};

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open: () => void };
  }
}
