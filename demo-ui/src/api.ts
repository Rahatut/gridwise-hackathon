import { OptimizeRequest, OptimizeResponse } from './types';

const STORAGE_KEY = 'gridwise_custom_api_url';

export function getApiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved !== null && saved.trim() !== '') {
      return saved.trim().replace(/\/+$/, '');
    }
  }
  const envUrl = import.meta.env.VITE_API_BASE_URL;
  if (envUrl && typeof envUrl === 'string' && envUrl.trim() !== '') {
    return envUrl.trim().replace(/\/+$/, '');
  }
  return ''; // Relative path by default
}

export function setApiBaseUrl(url: string): void {
  if (typeof window !== 'undefined') {
    if (!url || url.trim() === '') {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, url.trim().replace(/\/+$/, ''));
    }
  }
}

export async function checkHealth(signal?: AbortSignal): Promise<{ status: string }> {
  const base = getApiBaseUrl();
  const url = `${base}/health`;
  const res = await fetch(url, { signal, headers: { 'Accept': 'application/json' } });
  if (!res.ok) {
    throw new Error(`Health check failed with HTTP ${res.status}`);
  }
  return res.json();
}

export async function optimizeEnergy(
  payload: OptimizeRequest,
  timeoutMs: number = 35000
): Promise<OptimizeResponse> {
  const base = getApiBaseUrl();
  const url = `${base}/optimize-energy`;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!res.ok) {
      let detail = `Server returned HTTP ${res.status}`;
      try {
        const errorJson = await res.json();
        if (errorJson?.detail) {
          detail = typeof errorJson.detail === 'string' 
            ? errorJson.detail 
            : JSON.stringify(errorJson.detail);
        }
      } catch {
        // use default detail
      }
      throw new Error(detail);
    }

    return await res.json();
  } catch (err: any) {
    if (err.name === 'AbortError') {
      throw new Error('Request timed out after 35 seconds. Please check backend latency or API quotas.');
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}
