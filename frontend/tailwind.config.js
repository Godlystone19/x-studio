/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        accent: 'rgb(var(--color-primary-rgb) / <alpha-value>)',
        background: 'rgb(var(--color-background-rgb) / <alpha-value>)',
        surface: 'rgb(var(--color-surface-rgb) / <alpha-value>)',
        charcoal: 'rgb(var(--color-charcoal-rgb) / <alpha-value>)',
        foreground: 'rgb(var(--color-text-primary-rgb) / <alpha-value>)',
        muted: 'rgb(var(--color-text-secondary-rgb) / <alpha-value>)',
        border: 'rgb(var(--color-border-rgb) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['Manrope', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: {
        subtle: '0 1px 3px rgb(0 0 0 / 22%)',
      },
    },
  },
  plugins: [],
}
