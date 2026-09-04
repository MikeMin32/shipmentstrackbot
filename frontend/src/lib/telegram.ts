export interface TelegramUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
}

export interface TelegramWebApp {
  initData: string;
  initDataUnsafe: {
    user?: TelegramUser;
    start_param?: string;
  };
  colorScheme: "light" | "dark";
  themeParams: Record<string, string>;
  ready: () => void;
  expand: () => void;
  close: () => void;
  setHeaderColor: (color: string) => void;
  setBackgroundColor: (color: string) => void;
  disableVerticalSwipes?: () => void;
  HapticFeedback?: {
    impactOccurred: (style: "light" | "medium" | "heavy") => void;
    notificationOccurred: (type: "error" | "success" | "warning") => void;
  };
  BackButton: {
    show: () => void;
    hide: () => void;
    onClick: (fn: () => void) => void;
    offClick: (fn: () => void) => void;
  };
  showConfirm: (message: string, callback: (ok: boolean) => void) => void;
  showAlert: (message: string, callback?: () => void) => void;
}

declare global {
  interface Window {
    Telegram?: {
      WebApp: TelegramWebApp;
    };
  }
}

export function getTelegram(): TelegramWebApp | null {
  return window.Telegram?.WebApp ?? null;
}

export function applyTelegramTheme(webApp: TelegramWebApp): void {
  const root = document.documentElement;
  const params = webApp.themeParams || {};
  const map: Record<string, string> = {
    bg_color: "--tg-theme-bg-color",
    text_color: "--tg-theme-text-color",
    hint_color: "--tg-theme-hint-color",
    link_color: "--tg-theme-link-color",
    button_color: "--tg-theme-button-color",
    button_text_color: "--tg-theme-button-text-color",
    secondary_bg_color: "--tg-theme-secondary-bg-color",
    header_bg_color: "--tg-theme-header-bg-color",
    accent_text_color: "--tg-theme-accent-text-color",
    section_bg_color: "--tg-theme-section-bg-color",
    destructive_text_color: "--tg-theme-destructive-text-color",
  };
  for (const [key, cssVar] of Object.entries(map)) {
    const value = params[key];
    if (value) {
      root.style.setProperty(cssVar, value);
    }
  }
  root.dataset.colorScheme = webApp.colorScheme;
  document.body.style.background = params.bg_color || params.secondary_bg_color || "";
  try {
    webApp.setHeaderColor(params.header_bg_color || params.bg_color || "secondary_bg_color");
    webApp.setBackgroundColor(params.bg_color || params.secondary_bg_color || "#ffffff");
  } catch {
    // Older Telegram clients may not support these methods.
  }
}

export function initTelegram(): TelegramWebApp | null {
  const webApp = getTelegram();
  if (!webApp) {
    return null;
  }
  webApp.ready();
  webApp.expand();
  webApp.disableVerticalSwipes?.();
  applyTelegramTheme(webApp);
  return webApp;
}

export function haptic(kind: "success" | "error" | "warning" | "light" = "light"): void {
  const feedback = getTelegram()?.HapticFeedback;
  if (!feedback) {
    return;
  }
  if (kind === "light") {
    feedback.impactOccurred("light");
  } else {
    feedback.notificationOccurred(kind);
  }
}

export function confirmAction(message: string): Promise<boolean> {
  const webApp = getTelegram();
  if (webApp?.showConfirm) {
    return new Promise((resolve) => webApp.showConfirm(message, resolve));
  }
  return Promise.resolve(window.confirm(message));
}
