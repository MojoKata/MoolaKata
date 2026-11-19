# S12.8. Accessibility

8. **Accessibility**: everything works by keyboard, every control is labelled, contrast
   meets WCAG AA, and `prefers-reduced-motion` turns transitions off. Dark theme first, with
   light and system. **Desktop browsers only**: phone layouts are not built or tested, since
   phones will get a separate PWA with a narrower, focused set of features ([F#571](https://github.com/MojoKata/MoolaKata/issues/571)). English only,
   no i18n layer. Charts have a **table view** toggle (a screen reader reads the numbers) and
   honour `prefers-reduced-motion`.
