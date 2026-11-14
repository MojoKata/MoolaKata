# Copied code in the ui-kit

What the ui-kit adapts from an open-source project keeps that project's licence (requirements
S17.3.10.5). Each file below says so in its first line, and the dependency register lists it
(`docs/dependencies.md`, Copied code). Nothing here updates on its own: a later fix in the project
is copied as a change of its own, read like any other.

## preact-components

- **Project:** preact-components, MIT licence. Copied from the fork
  [MojoKata/preact-components](https://github.com/MojoKata/preact-components) at commit
  `5be54c4069a2d3b3bec8508c41abe79a2ff5b4e0` (its release 14.6.0), which follows
  [spy4x/preact-components](https://github.com/spy4x/preact-components).
- **What was taken, and where it went** (rewritten as plain JavaScript with JSDoc, to the kit's
  names and its own markup and styles; no TSX, Tailwind or package of the project's is loaded):

  | Kit file     | Adapted from       | What                                                                                                                                                                                                                                                                                                                                                |
  | ------------ | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
  | `listbox.js` | `ui/combobox.tsx`  | the list's key table (`nextComboboxState`, `comboboxKeyAction`, `comboboxKey`): which option the arrows reach, Home and End only while open, Enter picking the one reached and never submitting, Escape closing and going no further                                                                                                                |
  | `tags.js`    | `ui/tag-input.tsx` | the tag box's rules (`splitTagText`, `addTags`, `tagSuggestions`, `tagInputKeyAction`): names split at commas as typed or pasted, two names differing only in case being one with the first spelling kept, the chosen left out of the suggestions, a comma adding, Backspace in an empty box taking off the last chip but not while the key repeats |

  Matching what is typed (`listbox.js`, `matching`) is the kit's own: the project's fuzzy search
  lives in a package of its own, not taken. The calendar (`date-input.js`) takes only an idea from
  the project's `system/calendar.tsx`, none of its code: six weeks whatever the month, and the days
  of the months beside it left blank.

### Its licence

```
MIT License

Copyright (c) 2026 Anton Shubin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
