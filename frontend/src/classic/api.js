// Thin JSON client for the Draft Advisor API (proxied to the FastAPI backend by Vite).

const BASE = "/api";

/**
 * Send a JSON request to the API (under /api).
 * Resolves to the parsed body: null for 204, the raw text when it isn't JSON.
 * Rejects with Error(detail) on a non-2xx response, using FastAPI's `detail` when present.
 */
async function request(method, path, body) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(BASE + path, init);
  if (res.status === 204) return null;
  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail = data && data.detail !== undefined ? data.detail : res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body = {}) => request("POST", path, body),
  put: (path, body) => request("PUT", path, body),
  patch: (path, body) => request("PATCH", path, body),
  del: (path) => request("DELETE", path),
};

/** Build a query string from `params`, skipping undefined, null and empty-string values. Returns "" when nothing is left. */
export const qs = (params) => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return entries.length ? "?" + new URLSearchParams(entries).toString() : "";
};
