/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx,js,jsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        display:  ["'Space Grotesk'", 'system-ui', 'sans-serif'],
        sans:     ["'Space Grotesk'", "'Inter'", 'system-ui', '-apple-system', 'sans-serif'],
        mono:     ["'JetBrains Mono'", "'Geist Mono'", 'ui-monospace', 'monospace'],
        "mono-t": ["'JetBrains Mono'", "'Geist Mono'", 'ui-monospace', 'monospace'],
        "ui-t":   ["'Space Grotesk'", "'Inter'", 'system-ui', 'sans-serif'],
      },
      colors: {
        // ── shadcn compatibility layer ────────────────────────────
        border:      "hsl(var(--border))",
        input:       "hsl(var(--input))",
        ring:        "hsl(var(--ring))",
        background:  "hsl(var(--background))",
        foreground:  "hsl(var(--foreground))",
        primary: {
          DEFAULT:    "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT:    "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT:    "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT:    "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT:    "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        card: {
          DEFAULT:    "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },

        // ── BMG design tokens ─────────────────────────────────────
        bmg: {
          // Backgrounds
          base:       "#040804",
          elevated:   "#080d08",
          elevated2:  "#0c120c",

          // Borders
          subtle:     "rgba(74,222,128,0.10)",
          emphasis:   "rgba(74,222,128,0.20)",

          // Text
          primary:    "#eafbe9",
          secondary:  "#dce8dc",
          tertiary:   "#7e8e7e",

          // Accents
          positive:   "#4ade80",
          negative:   "#f87171",
          "positive-bg": "rgba(74,222,128,0.10)",
          "negative-bg": "rgba(248,113,113,0.10)",

          // Legacy aliases (used in chart + keep-alive components)
          bg:      "#040804",
          surface: "#080d08",
          raised:  "#0c120c",
          border:  "#0c120c",
          profit:  "#4ade80",
          loss:    "#f87171",
          brand:   "#4ade80",
          gold:    "#fbbf24",
        },

        // BMG green identity tokens (hero / sci-fi design language)
        "bmg-green": {
          DEFAULT: "#4ade80",
          glow:    "rgba(74,222,128,0.4)",
          dim:     "rgba(74,222,128,0.15)",
          border:  "rgba(74,222,128,0.3)",
        },

        // ── Terminal design system 2026 ──────────────────────────
        t: {
          // Surfaces
          bg0:    "#040804",
          bg1:    "#060c06",
          bg2:    "#0a120a",
          // Borders
          dim:    "rgba(74,222,128,0.12)",
          mid:    "rgba(74,222,128,0.25)",
          hot:    "#4ade80",
          // Text
          hi:     "#d7ecd9",
          mid2:   "#8aa88e",   // 'mid' is taken by border
          muted:  "#5a7a5e",
          // Signal
          green:  "#4ade80",
          bright: "#86efac",
          gdim:   "#2d6b45",
          red:    "#f87171",
          amber:  "#fbbf24",
          cyan:   "#22d3ee",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      boxShadow: {
        card: "0 1px 2px rgba(0,0,0,0.20), 0 8px 24px rgba(0,0,0,0.15)",
        "card-hover": "0 1px 2px rgba(0,0,0,0.25), 0 12px 32px rgba(0,0,0,0.25)",
      },
      animation: {
        'count-up':    'countUp 0.6s ease-out',
        'fade-in':     'fadeIn 0.2s ease-out',
        'pulse-once':  'pulseOnce 1.4s ease-in-out',
        'page-in':     'pageIn 0.15s ease-out',
        'flash-green': 'flashGreen 0.4s ease-out',
        'flash-red':   'flashRed 0.4s ease-out',
        'card-rise':   'cardRise 0.15s ease-out',
      },
      keyframes: {
        countUp: {
          '0%':   { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          '0%':   { opacity: '0' },
          '100%': { opacity: '1' },
        },
        pulseOnce: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(139,92,246,0)' },
          '40%':      { boxShadow: '0 0 0 6px rgba(139,92,246,0.35)' },
          '70%':      { boxShadow: '0 0 0 10px rgba(139,92,246,0.10)' },
        },
        pageIn: {
          '0%':   { opacity: '0' },
          '100%': { opacity: '1' },
        },
        flashGreen: {
          '0%':   { backgroundColor: 'rgba(74,222,128,0.25)' },
          '100%': { backgroundColor: 'transparent' },
        },
        flashRed: {
          '0%':   { backgroundColor: 'rgba(248,113,113,0.25)' },
          '100%': { backgroundColor: 'transparent' },
        },
        cardRise: {
          '0%':   { transform: 'translateY(0)' },
          '100%': { transform: 'translateY(-2px)' },
        },
      },
      transitionDuration: {
        fast: '150ms',
        base: '200ms',
        slow: '250ms',
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}
