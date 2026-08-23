import { useEffect, useState } from "react";

const TICK_MS = 1000;

/** Shared clock so relative timestamps in the chat list stay in sync. */
export function useNow(): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), TICK_MS);
    return () => window.clearInterval(id);
  }, []);

  return now;
}
