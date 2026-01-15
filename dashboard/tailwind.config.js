/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      screens: {
        // Mobile-first breakpoint cascade
        'xs': '480px',   // Large phones
        'sm': '640px',   // Small tablets (default)
        'md': '768px',   // Tablets (default)
        'lg': '1024px',  // Desktops (default)
        'xl': '1280px',  // Large desktops (default)
        '2xl': '1536px', // Wide screens (default)
        '3xl': '1920px', // Ultra-wide monitors
      },
      // Container query breakpoints (Tailwind 3.4+ native support)
      containers: {
        'xs': '320px',
        'sm': '384px',
        'md': '448px',
        'lg': '512px',
        'xl': '576px',
        '2xl': '672px',
      },
      colors: {
        // Custom colors for trading dashboard (PRESERVED)
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
