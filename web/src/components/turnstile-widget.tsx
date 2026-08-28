import { useEffect, useId, useRef, useState } from "react";

declare global {
  interface Window {
    turnstile?: {
      render: (
        container: HTMLElement,
        options: {
          sitekey: string;
          callback?: (token: string) => void;
          "expired-callback"?: () => void;
          "error-callback"?: () => void;
          theme?: "light" | "dark" | "auto";
        },
      ) => string;
      remove: (widgetId: string) => void;
      reset: (widgetId: string) => void;
    };
    onTurnstileLoad?: () => void;
  }
}

const TURNSTILE_SCRIPT_ID = "cf-turnstile-script";
const TURNSTILE_SCRIPT_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?onload=onTurnstileLoad";

export const TURNSTILE_SITE_KEY =
  (import.meta.env.VITE_TURNSTILE_SITE_KEY as string | undefined)?.trim() ?? "";

export function turnstileEnabled(): boolean {
  return TURNSTILE_SITE_KEY.length > 0;
}

function loadTurnstileScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve();
  const existing = document.getElementById(TURNSTILE_SCRIPT_ID);
  if (existing) {
    return new Promise((resolve) => {
      if (window.turnstile) resolve();
      else window.onTurnstileLoad = () => resolve();
    });
  }
  return new Promise((resolve, reject) => {
    window.onTurnstileLoad = () => resolve();
    const script = document.createElement("script");
    script.id = TURNSTILE_SCRIPT_ID;
    script.src = TURNSTILE_SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onerror = () => reject(new Error("Failed to load Turnstile"));
    document.head.appendChild(script);
  });
}

type TurnstileWidgetProps = {
  onToken: (token: string | null) => void;
  className?: string;
};

export function TurnstileWidget({ onToken, className }: TurnstileWidgetProps) {
  const containerId = useId().replace(/:/g, "");
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetIdRef = useRef<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!turnstileEnabled() || !containerRef.current) return;
    let cancelled = false;

    (async () => {
      try {
        await loadTurnstileScript();
        if (cancelled || !containerRef.current || !window.turnstile) return;
        widgetIdRef.current = window.turnstile.render(containerRef.current, {
          sitekey: TURNSTILE_SITE_KEY,
          theme: "auto",
          callback: (token) => onToken(token),
          "expired-callback": () => onToken(null),
          "error-callback": () => {
            setError(true);
            onToken(null);
          },
        });
      } catch {
        if (!cancelled) {
          setError(true);
          onToken(null);
        }
      }
    })();

    return () => {
      cancelled = true;
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
    };
  }, [onToken]);

  if (!turnstileEnabled()) return null;

  return (
    <div className={className}>
      <div ref={containerRef} id={containerId} />
      {error && (
        <p className="mt-2 text-sm text-destructive">
          Turnstile failed to load. Refresh and try again.
        </p>
      )}
    </div>
  );
}
