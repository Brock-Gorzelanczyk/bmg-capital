export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";
export const DEMO_EMAIL = "demo@bmgcapital.com";
export const DEMO_PASSWORD = "demo2024";
export type DemoPersona = "long_term" | "active_trader" | "crypto" | "beginner";
export const DEMO_PERSONAS: DemoPersona[] = ["long_term", "active_trader", "crypto", "beginner"];
