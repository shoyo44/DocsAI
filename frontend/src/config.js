const trimTrailingSlash = (value) => value.replace(/\/+$/, '');

export const API_BASE = trimTrailingSlash(
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'
);

export const WS_BASE = trimTrailingSlash(
  import.meta.env.VITE_WS_BASE_URL || API_BASE.replace(/^http/, 'ws')
);

export const TENANT_ID = import.meta.env.VITE_TENANT_ID || 'tenant-123';
