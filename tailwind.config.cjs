// Mirrors ieltsMock/tailwind.config.cjs so the dashboard and the student app
// read as one product. Pinned to Tailwind 3.4 to match; Tailwind 4 changed the
// config format and the two would drift immediately.
module.exports = {
  content: ['./templates/**/*.html', './apps/**/*.py'],
  theme: {
    extend: {
      colors: {
        coral: {
          50: '#FEF3F2',
          100: '#FEE4E2',
          200: '#FECDCA',
          300: '#FDA29B',
          400: '#F97066',
          500: '#F0524A',
          600: '#D92D20',
          700: '#B42318',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
        display: ['"Plus Jakarta Sans"', 'Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
