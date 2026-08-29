/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_FLASK_ORIGIN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
