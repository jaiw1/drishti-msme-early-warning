/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Brand fills. The `*tx` variants are the same hues darkened until they clear
        // 4.5:1 against white and against their own tinted chip background — a contrast
        // audit found the brand tones fail as TEXT (rag-amber is 3.19:1 on white) while
        // being perfectly legible as a bar, a dot or a solid fill. Fills keep the brand
        // colour; anything a user has to READ uses the `tx` variant.
        idbi: {
          green: '#02684F',   // 6.78:1 on white — fine as text
          greenlt: '#038C6B', // fill only (white on it is 4.23:1)
          greendk: '#01503C', // hover/active for white-on-green buttons
          orange: '#FF4D01',  // fill only (3.33:1 on white)
          orangetx: '#c2410c', // 5.18:1 on white
        },
        rag: {
          red: '#dc2626', amber: '#d97706', green: '#16a34a',      // fills, dots, bars
          redtx: '#b91c1c', ambertx: '#b45309', greentx: '#15803d', // text
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'Segoe UI', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
