import type { ApiSetup, BillingPlan, Checkout, Entitlement, TokenResponse, User } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";
const TOKEN_KEY = "modular-shorts-token";

type RequestOptions = RequestInit & {
  json?: unknown;
  token?: string;
};

export function getStoredToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setStoredToken(token: string) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  let body = options.body;
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  }
  if (options.token) headers.set("Authorization", `Bearer ${options.token}`);
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers, body });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === "string" ? payload.detail : `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  plans: () => request<BillingPlan[]>("/billing/plans"),
  signup: (input: { email: string; password: string; display_name: string }) =>
    request<TokenResponse>("/auth/signup", { method: "POST", json: input }),
  login: (input: { email: string; password: string }) =>
    request<TokenResponse>("/auth/login", { method: "POST", json: input }),
  me: (token: string) => request<User>("/auth/me", { token }),
  updateProfile: (token: string, displayName: string) =>
    request<User>("/account/profile", { method: "PUT", token, json: { display_name: displayName } }),
  apiKeys: (token: string) => request<ApiSetup>("/account/api-keys", { token }),
  saveApiKey: (token: string, input: { provider: string; value: string; model: string }) =>
    request<ApiSetup>("/account/api-keys", { method: "POST", token, json: input }),
  entitlement: (token: string) => request<Entitlement>("/billing/entitlement", { token }),
  checkout: (token: string, planCode: string) =>
    request<Checkout>("/billing/checkout", { method: "POST", token, json: { plan_code: planCode } }),
  verify: (token: string, payload: Record<string, string>) =>
    request<Entitlement>("/billing/verify", { method: "POST", token, json: payload })
};

export function formatMoney(amountPaise: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0
  }).format(amountPaise / 100);
}

export function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>("script[data-razorpay]");
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("Razorpay checkout failed to load.")));
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    script.dataset.razorpay = "true";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Razorpay checkout failed to load."));
    document.body.appendChild(script);
  });
}
