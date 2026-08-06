export {};

declare global {
  interface Window {
    desktopApi: {
      config: () => Promise<{ apiBase: string; paymentSiteUrl: string }>;
      request: <T>(path: string, options?: { method?: string; json?: unknown; headers?: Record<string, string> }) => Promise<T>;
      openPaymentSite: (suffix?: string) => Promise<void>;
      token: {
        get: () => string;
        set: (value: string) => void;
        clear: () => void;
      };
    };
  }
}
