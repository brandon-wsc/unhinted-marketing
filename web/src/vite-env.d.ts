/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Baked at `vite build` (ADR 0023); unset / unknown → onprem. */
  readonly VITE_DEPLOYMENT_MODE?: "cloud" | "onprem";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
