# Building a React UI from Attached UX Designs

When the user attaches UX designs (images or PDF exports), the generated UI should look like those designs, not like the legacy JSP. The designs decide **how it looks**; the JSP behaviour and the API contract decide **what it shows and does**.

## 1. Extract the design tokens first

Before writing any page, read every design and write `frontend/src/styles/theme.css`:

```css
:root {
  /* Colours — exact hex values read from the designs */
  --color-primary: #1f6feb;
  --color-surface: #ffffff;
  --color-text: #1b1f24;
  --color-muted: #57606a;
  --color-danger: #cf222e;
  /* Typography */
  --font-family: "Inter", system-ui, sans-serif;
  --font-size-body: 14px;
  --font-size-h1: 28px;
  /* Spacing, radius, shadow */
  --space-1: 4px; --space-2: 8px; --space-3: 16px; --space-4: 24px;
  --radius: 8px;
  --shadow-card: 0 1px 3px rgb(0 0 0 / 0.12);
}
```

Every component uses these variables — no hard-coded colours or sizes scattered through the components. Import `theme.css` once in `src/main.tsx`.

## 2. Components follow the design's structure

- Every visual element the designs repeat (cards, table rows, buttons, form fields, nav bars, badges) becomes one shared component in `frontend/src/components/`.
- Match the design's layout: grid/column structure, alignment, ordering, grouping, and the approximate pixel sizes and spacing shown. Use CSS (modules or plain files per component) — do not add a UI component library unless the plan explicitly calls for one.
- Match iconography in spirit. If an icon library is already in the manifest, use its closest icon; otherwise use simple inline SVGs.
- Logos, photos and illustrations in a design: add a placeholder asset in `frontend/src/assets/` and note it in your summary — never crop images out of the design screenshot.

## 3. States the design may not show

For states the designs don't cover (loading, empty, error, disabled, hover/focus, validation errors), derive them consistently from the design tokens: same colours, spacing and type scale. Field-level validation errors still render next to their fields.

## 4. When design and behaviour disagree

- A design shows a field or action the API contract doesn't support → build the layout slot, leave the unsupported control out (or disabled with a TODO), and list it in your summary. Never call an endpoint that isn't in the contract.
- The JSP / contract has a field the design doesn't show → keep the field (behaviour wins), placed where it fits the design's layout, and list it.
- Pages no design covers → follow the visual language of the closest designed page, as the plan's UX Design Mapping says.

## 5. Responsiveness and accessibility

- If the designs are desktop-only, make the layout degrade gracefully to narrow screens (stack columns, keep tap targets ≥ 40px). If mobile designs are attached too, follow them at small widths.
- Keep accessibility even where a design is silent: real `<label>`s for inputs, alt text, visible focus styles, sufficient text contrast. If a design colour fails contrast for body text, use the nearest compliant shade and say so.

## 6. Report deviations

In the Frontend Generate Result, list which design each page follows, and every deliberate deviation from a design with the reason.
