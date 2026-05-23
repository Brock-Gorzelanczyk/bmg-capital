export const API_BASE = "/api";
// Use the same host the frontend is running on — Vite proxies /ws → backend
const _proto = window.location.protocol === "https:" ? "wss:" : "ws:";
export const WS_URL = `${_proto}//${window.location.host}/ws/stream`;
