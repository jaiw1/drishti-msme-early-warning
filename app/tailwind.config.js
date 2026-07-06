/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        idbi: { green: '#02684F', greenlt: '#038C6B', orange: '#FF4D01' },
        rag: { red: '#dc2626', amber: '#d97706', green: '#16a34a' },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'Segoe UI', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
