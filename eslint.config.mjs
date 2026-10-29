// npx eslint@9 static/js     (no package.json needed)
export default [
  {
    files: ["static/js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        window: "readonly", document: "readonly", navigator: "readonly", location: "readonly", history: "readonly",
        localStorage: "readonly", fetch: "readonly", crypto: "readonly", console: "readonly", setTimeout: "readonly",
        clearTimeout: "readonly", setInterval: "readonly", clearInterval: "readonly", requestAnimationFrame: "readonly",
        URL: "readonly", URLSearchParams: "readonly", FormData: "readonly", TextEncoder: "readonly", Intl: "readonly",
        HashChangeEvent: "readonly", getComputedStyle: "readonly", Node: "readonly", self: "readonly", caches: "readonly",
        CB: "readonly", CB_STRINGS: "writable", qrcode: "readonly", jsQR: "readonly", Chart: "readonly",
      },
    },
    rules: {
      "no-unused-vars": ["error", { args: "none", caughtErrors: "none" }],
      "no-undef": "error",
      "no-redeclare": "error",
      "no-dupe-keys": "error",
      "no-unreachable": "error",
      eqeqeq: ["error", "smart"],
      "prefer-const": "error",
      "no-var": "error",
    },
  },
];
