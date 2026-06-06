/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_TIME_ZONE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
