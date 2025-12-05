/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Custom colors for trading dashboard
        bull: {
          DEFAULT: '#22c55e',
          light: '#86efac',
          dark: '#16a34a',
        },
        bear: {
          DEFAULT: '#ef4444',
          light: '#fca5a5',
          dark: '#dc2626',
        },
        neutral: {
          DEFAULT: '#6b7280',
        },
      },
    },
  },
  plugins: [],
}
