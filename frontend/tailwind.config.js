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
        display: ['Bricolage Grotesque', 'system-ui', 'sans-serif'],
        sans:    ['Geist', 'system-ui', '-apple-system', 'sans-serif'],
        mono:    ['Geist Mono', 'ui-monospace', 'monospace'],
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
          base:       "#18181B",
          elevated:   "#27272A",
          elevated2:  "#3F3F46",

          // Borders
          subtle:     "rgba(255,255,255,0.06)",
          emphasis:   "rgba(255,255,255,0.12)",

          // Text
          primary:    "#FAFAFA",
          secondary:  "#A1A1AA",
          tertiary:   "#71717A",

          // Accents
          positive:   "#BEF264",
          negative:   "#FB7185",
          "positive-bg": "rgba(190,242,100,0.10)",
          "negative-bg": "rgba(251,113,133,0.10)",

          // Legacy aliases (used in chart + keep-alive components)
          bg:      "#18181B",
          surface: "#27272A",
          raised:  "#3F3F46",
          border:  "#3F3F46",
          profit:  "#BEF264",
          loss:    "#FB7185",
          brand:   "#BEF264",
          gold:    "#F59E0B",
        },

        // BMG green identity tokens (hero / sci-fi design language)
        "bmg-green": {
          DEFAULT: "#4ade80",
          glow:    "rgba(74,222,128,0.4)",
          dim:     "rgba(74,222,128,0.15)",
          border:  "rgba(74,222,128,0.3)",
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
