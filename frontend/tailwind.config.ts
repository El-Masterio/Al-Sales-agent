import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // Instrument-panel palette — dark console with signal-green agent activity
        ink: {
          950: "#0a0e0d",
          900: "#0f1513",
          800: "#161d1a",
          700: "#1d2622",
          600: "#2a352f",
          500: "#3a4843",
        },
        signal: {
          // live agent activity — phosphor green
          DEFAULT: "#3ddc84",
          dim: "#2ba968",
          glow: "#5cf0a0",
        },
        amber: {
          // needs-human / pending
          DEFAULT: "#e8a33d",
        },
        coral: {
          // negative / stopped
          DEFAULT: "#e85d5d",
        },
        mist: {
          500: "#6b7c75",
          400: "#8a9b93",
          300: "#aab8b2",
          200: "#c9d3ce",
          100: "#e8edeb",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        panel: "10px",
      },
      boxShadow: {
        panel: "0 1px 0 rgba(255,255,255,0.03) inset, 0 8px 24px rgba(0,0,0,0.4)",
        "signal-glow": "0 0 12px rgba(61,220,132,0.35)",
      },
      keyframes: {
        pulse_ring: {
          "0%": { transform: "scale(0.9)", opacity: "0.7" },
          "70%": { transform: "scale(1.6)", opacity: "0" },
          "100%": { opacity: "0" },
        },
      },
      animation: {
        "pulse-ring": "pulse_ring 2s cubic-bezier(0.4,0,0.6,1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;
