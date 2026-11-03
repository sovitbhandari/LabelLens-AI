/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#07131f",
          900: "#0d2438",
          700: "#2a4a63",
          500: "#5b7c94",
          300: "#9db4c5",
        },
        paper: {
          50: "#f4fbfc",
          100: "#e7f6f8",
          200: "#cfe9ef",
        },
        aqua: {
          700: "#0a6b7c",
          600: "#0e8fa3",
          500: "#18b4c9",
          300: "#7ad7e4",
          100: "#d7f5fa",
        },
        coral: {
          700: "#c2412b",
          600: "#e85d3a",
          500: "#ff7a4d",
          300: "#ffb39a",
          100: "#ffe4d8",
        },
        gold: {
          600: "#c9891a",
          500: "#e8a820",
          300: "#f2cf70",
          100: "#fff1c9",
        },
        moss: {
          600: "#2f7d4f",
          500: "#3f9a63",
          300: "#8dcca8",
          100: "#d9f3e3",
        },
        warn: {
          600: "#b45309",
          100: "#ffedd5",
        },
        accent: {
          600: "#0e8fa3",
          500: "#18b4c9",
          100: "#d7f5fa",
        },
      },
      fontFamily: {
        sans: ['"Sora"', "ui-sans-serif", "sans-serif"],
        display: ['"Fraunces"', "Georgia", "serif"],
      },
      boxShadow: {
        panel: "0 12px 40px rgba(7, 19, 31, 0.08)",
        soft: "0 4px 18px rgba(14, 143, 163, 0.12)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(14px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-8px)" },
        },
        "hue-shift": {
          "0%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
          "100%": { backgroundPosition: "0% 50%" },
        },
        shimmer: {
          "0%": { backgroundPosition: "200% 0" },
          "100%": { backgroundPosition: "-200% 0" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.55s ease-out both",
        float: "float 7s ease-in-out infinite",
        "hue-shift": "hue-shift 14s ease infinite",
        shimmer: "shimmer 2.4s linear infinite",
      },
    },
  },
  plugins: [],
};
