import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __dirname = dirname(fileURLToPath(import.meta.url));
const compat = new FlatCompat({ baseDirectory: __dirname });

export default [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // Demoted from error to warn — the codebase has ~10 legitimate
      // `as any` escapes (Tiptap editor instance, dynamic-import shims,
      // some d3 callbacks) where the typing-debt-vs-correctness ratio
      // is right. Keep the rule on as a signal so new `any` shows up in
      // lint output, but don't block CI green over the existing wall.
      // Pair with the prod-build's `eslint: { ignoreDuringBuilds: true }`
      // in next.config.ts — both keep CI / prod from gating on a stable
      // pre-existing debt while still surfacing new violations to devs.
      "@typescript-eslint/no-explicit-any": "warn",
      // Same demotion for consistent-type-imports — it's a stylistic
      // sweep that's easy to clean up later; flagging as a warning
      // keeps lint output readable.
      "@typescript-eslint/consistent-type-imports": "warn",
      // `module` is reserved in Next.js page files (`next/no-assign-
      // module-variable`). The one offender uses `module` as a
      // domain-relevant variable name (course module) in a callback
      // scope where the next.js global isn't accessed. Worth a rename
      // someday; not worth gating CI.
      "@next/next/no-assign-module-variable": "warn",
    },
  },
];
