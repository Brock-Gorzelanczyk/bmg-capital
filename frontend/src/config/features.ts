const flag = (key: string, defaultOn = true) =>
  (import.meta.env[key] ?? (defaultOn ? "true" : "false")) !== "false";

export const FEATURES = {
  LEARNING_CENTER:  flag("VITE_FF_LEARN"),
  EXPLAIN_THIS:     flag("VITE_FF_EXPLAIN"),
  GUIDED_TOURS:     flag("VITE_FF_TOURS"),
  GAMIFICATION:     flag("VITE_FF_GAMIFY"),
  TRADE_JOURNAL:    flag("VITE_FF_JOURNAL"),
  AI_COPILOT:       flag("VITE_FF_AI", false),
  SOCIAL:           flag("VITE_FF_SOCIAL", false),
  CERTIFICATIONS:   flag("VITE_FF_CERTS"),
} as const;
