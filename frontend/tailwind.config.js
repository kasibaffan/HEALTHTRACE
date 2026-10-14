/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Aptos', '"Segoe UI Variable"', '"Segoe UI"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', '"Cascadia Code"', 'Menlo', 'Consolas', 'monospace'],
      },
      colors: {
        brand: { 50: '#effaf8', 100: '#d3f3ee', 500: '#0d9488', 600: '#0f766e', 700: '#115e59', 900: '#0b2f33' },
      },
      boxShadow: {
        card: '0 1px 2px rgba(15,23,42,0.05), 0 1px 3px rgba(15,23,42,0.04)',
        drawer: '-12px 0 40px rgba(15,23,42,0.18)',
      },
      keyframes: {
        slideIn: { from: { transform: 'translateX(24px)', opacity: '0' }, to: { transform: 'none', opacity: '1' } },
        fadeIn: { from: { opacity: '0' }, to: { opacity: '1' } },
        rise: { from: { transform: 'translateY(8px)', opacity: '0' }, to: { transform: 'none', opacity: '1' } },
      },
      animation: { slideIn: 'slideIn .22s ease-out', fadeIn: 'fadeIn .18s ease-out', rise: 'rise .2s ease-out' },
    },
  },
  plugins: [],
}
