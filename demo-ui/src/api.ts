import { OptimizeRequest, OptimizeResponse } from './types';

// Backend API base URL from Vite environment variable, with fallback to Render URL
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'https://gridwise-hackathon.onrender.com';

export function getApiBaseUrl(): string {
  return API_BASE_URL.replace(/\/+$/, '');
}

export function setApiBaseUrl(_url: string): void {
  // No-op: API URL is configured via VITE_API_BASE_URL environment variable
}

export async function checkHealth(signal?: AbortSignal): Promise<{ status: string }> {
  const base = getApiBaseUrl();
  const url = `${base}/health`;
  const res = await fetch(url, { signal, headers: { 'Accept': 'application/json' } });
  if (!res.ok) {
    throw new Error(`Health check failed with HTTP ${res.status}`);
  }
  return await res.json();
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