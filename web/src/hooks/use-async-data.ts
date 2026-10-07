import {
  type DependencyList,
  type Dispatch,
  type SetStateAction,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

export type AsyncDataOptions = {
  /** Runs before every load attempt (e.g. clearing stale selection detail). */
  reset?: () => void;
  /** Maps a thrown value to the stored `error` string; defaults to `err.message`. */
  errorMessage?: (err: unknown) => string;
  /** Failure handler; when set, `error` is left alone. */
  onError?: (err: unknown) => void;
};

/**
 * Fetch-on-mount/deps with loading + error state and a stale-result guard:
 * each run gets an epoch and only the latest may apply, so an older in-flight
 * response is dropped when deps change or reload() runs again. `load`/`apply`
 * may be fresh closures — only `deps` retriggers the cycle. `reload()` re-runs
 * it manually and never throws; failures land in `error`/`onError`.
 */
export function useAsyncData<T>(
  load: () => Promise<T>,
  apply: (data: T) => void,
  deps: DependencyList,
  options?: AsyncDataOptions,
): {
  loading: boolean;
  error: string | null;
  setError: Dispatch<SetStateAction<string | null>>;
  reload: () => Promise<void>;
} {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const epochRef = useRef(0);
  const loadRef = useRef(load);
  const applyRef = useRef(apply);
  const optsRef = useRef(options);
  loadRef.current = load;
  applyRef.current = apply;
  optsRef.current = options;

  const reload = useCallback(async () => {
    const epoch = ++epochRef.current;
    optsRef.current?.reset?.();
    setLoading(true);
    setError(null);
    try {
      const data = await loadRef.current();
      if (epoch !== epochRef.current) return;
      applyRef.current(data);
    } catch (err) {
      if (epoch !== epochRef.current) return;
      const opts = optsRef.current;
      if (opts?.onError) {
        opts.onError(err);
      } else {
        setError(opts?.errorMessage?.(err) ?? (err instanceof Error ? err.message : String(err)));
      }
    } finally {
      if (epoch === epochRef.current) setLoading(false);
    }
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: deps is the caller's trigger list.
  useEffect(() => {
    void reload();
  }, deps);

  return { loading, error, setError, reload };
}
