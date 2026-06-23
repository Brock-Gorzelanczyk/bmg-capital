import axios from "axios";
import { API_BASE } from "@/config";

const client = axios.create({ baseURL: API_BASE });

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("bmg_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Endpoints that genuinely speak for the session's validity. Only these
// trigger the global logout on 401. Random feature endpoints returning 401
// (admin-gate misses, transient backend issues, race conditions) used to
// boot the user out wholesale after a few navigations — that was bug #6
// in the audit. We now treat 401 from non-auth endpoints as a per-request
// permission/state issue and let the calling code handle it.
const AUTH_PATHS = ["/auth/me", "/auth/login", "/auth/register", "/auth/refresh"];

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const url: string = error.config?.url ?? "";
      const isAuthEndpoint = AUTH_PATHS.some((p) => url.includes(p));
      if (isAuthEndpoint) {
        // Authoritative: the token is actually bad. Clear + redirect.
        localStorage.removeItem("bmg_token");
        window.dispatchEvent(new Event("auth:expired"));
      }
      // For other endpoints, just propagate the 401 — caller can show
      // "permission denied" or retry as appropriate. Do NOT log the user
      // out on a single feature 401.
    }
    return Promise.reject(error);
  }
);

export default client;
