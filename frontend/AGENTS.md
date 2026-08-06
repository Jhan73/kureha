## Frontend Standards

* Use Next.js (App Router) + TypeScript.
* Use Tailwind CSS for styling.
* Use shadcn/ui as the primary component library.
* Use the Vega preset.
* Use Tabler Icons for all icons.
* Do not introduce additional UI libraries unless explicitly requested.

### Styling

* Use CSS variables for all theme tokens (colors, radius, shadows, spacing).
* Prefer semantic tokens (`--background`, `--foreground`, `--primary`, etc.).
* Avoid hardcoded colors.

### Theme

* All UI must support Light Mode and Dark Mode.
* New components must work correctly in both themes.

### Components

* Build reusable, composable components.
* Extract repeated UI into shared components.
* Avoid duplicated implementations.
* Keep business logic separate from UI components.

### Accessibility

* Preserve shadcn/ui accessibility behavior.
* Ensure keyboard navigation and focus states work correctly.

### Comments

* Minimal. Never cite `tasks.md`, specs, `design.md`, ADRs, or PR/work-unit history in code.
* Keep a comment only for non-obvious constraints (security/auth tradeoffs, wire-format quirks, documented gaps) — never narrative essays or restatements of the identifier.

### Agent Rules

Before creating custom UI:

1. Check whether a shadcn/ui component already exists.
2. Use CSS variables and existing design tokens.
3. Support Light/Dark Mode.
4. Use Tabler Icons.
5. Prioritize reusability and consistency.
