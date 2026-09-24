/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx,ts,tsx}", "./components/**/*.{js,jsx,ts,tsx}"],
  presets: [require("nativewind/preset")],
  theme: {
    extend: {
      colors: {
        bg: "#0a0812",
        card: "#181426",
        card2: "#110e1c",
        border: "#2b2542",
        fg: "#edecf4",
        muted: "#a49dc0",
        accent: "#7c3aed",
        accent2: "#a855f7",
        accent3: "#d946ef",
        light: "#c4b1ff",
      },
    },
  },
  plugins: [],
};
