/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./frontend/templates/**/*.html", "./frontend/assets/js/app.js"],
  theme: {
    extend: {
      fontFamily: {
        vazir: ["Vazirmatn", "sans-serif"]
      },
      colors: {
        ink: "#172A3A",
        navy: "#11395B",
        teal: "#087E8B",
        aqua: "#54C6C4",
        sand: "#F3E9D2",
        coral: "#E76F51",
        mist: "#F4F8F8"
      },
      boxShadow: {
        card: "0 12px 35px rgba(17, 57, 91, 0.08)"
      }
    }
  },
  plugins: []
};
