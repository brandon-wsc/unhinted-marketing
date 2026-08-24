import { createContext, type ReactNode, useCallback, useContext, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";

type ToastItem = {
  id: number;
  message: string;
  variant: "destructive" | "info";
};

type ToastContextValue = {
  showError: (message: string) => void;
  showInfo: (message: string) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

const TOAST_DURATION_MS = 4000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const push = useCallback((message: string, variant: ToastItem["variant"]) => {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, message, variant }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id));
    }, TOAST_DURATION_MS);
  }, []);

  const showError = useCallback((message: string) => push(message, "destructive"), [push]);
  const showInfo = useCallback((message: string) => push(message, "info"), [push]);

  return (
    <ToastContext.Provider value={{ showError, showInfo }}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2 px-4 sm:px-0"
      >
        {toasts.map((toast) =>
          toast.variant === "info" ? (
            // Floating overlay: solid popover base — the *-soft washes are ~10%
            // alpha and would show the page through.
            <Alert
              key={toast.id}
              variant="info"
              className="border-info/30 bg-popover text-info-foreground shadow-lg"
            >
              <AlertDescription className="text-info-foreground">{toast.message}</AlertDescription>
            </Alert>
          ) : (
            <Alert
              key={toast.id}
              variant="destructive"
              className="border-destructive/30 bg-popover text-destructive-foreground shadow-lg"
            >
              <AlertDescription className="text-destructive-foreground">
                {toast.message}
              </AlertDescription>
            </Alert>
          ),
        )}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
