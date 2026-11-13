// The note editor (requirements S12.18.15), loaded only when a note is edited: ProseMirror with
// the schema of note-spec.json, a toolbar above it, the list shortcuts, links made from the
// toolbar, by Ctrl/Cmd+K, by pasting an address or by typing one, and the popovers that make
// and follow them. What it gives its caller is the document as a note keeps it.
import { Schema } from 'prosemirror-model';
import { EditorState, Plugin, TextSelection } from 'prosemirror-state';
import { Decoration, DecorationSet, EditorView } from 'prosemirror-view';
import { history, redo, undo } from 'prosemirror-history';
import { keymap } from 'prosemirror-keymap';
import {
  baseKeymap,
  chainCommands,
  exitCode,
  lift,
  setBlockType,
  toggleMark,
  wrapIn,
} from 'prosemirror-commands';
import { liftListItem, sinkListItem, splitListItem, wrapInList } from 'prosemirror-schema-list';
import { InputRule, inputRules, undoInputRule, wrappingInputRule } from 'prosemirror-inputrules';
import { useEffect, useRef, useState } from 'preact/hooks';
import { html } from './html.js';
import { Icon } from './icon.js';
import { openMenu } from './menu.js';
import { Field, ValueInput } from './fields.js';
import { isEmpty, SPEC } from './note-check.js';
import { readHref, trailingAddress } from './note-links.js';
import { cleanPastedHTML } from './note-paste.js';
import { noPages } from './note-view.js';

/** @typedef {import('./note-links.js').Own} Own */
/** @typedef {import('./note-view.js').Pages} Pages */

/** The address this page itself is at, as an own server, its pages under `/ui/`. */
const HERE = /** @type {Own[]} */ (
  typeof location === 'undefined' ? [] : [{ origin: location.origin, base: '/ui/' }]
);

/**
 * How each kind of block is drawn and read back from pasted markup. A heading is drawn as its
 * level (h1 to h3) inside the editor, which styles them itself; where a note is read, the screen
 * says which levels they take (NoteView's `heading`). A heading copied from a note read keeps its
 * level; any other comes in as the nearest; a pasted table's cells come in as paragraphs;
 * anything not named here comes in as its text.
 * @type {Record<string, any>}
 */
const NODE_DOM = {
  paragraph: {
    toDOM: () => ['p', 0],
    parseDOM: [{ tag: 'p' }, { tag: 'td' }, { tag: 'th' }],
  },
  heading: {
    defining: true,
    toDOM: (/** @type {any} */ n) => [`h${n.attrs.level}`, 0],
    parseDOM: [
      {
        tag:
          'h1[data-note-level], h2[data-note-level], h3[data-note-level], h4[data-note-level], h5[data-note-level], h6[data-note-level]',
        priority: 60,
        getAttrs: (/** @type {HTMLElement} */ dom) => {
          const level = Number(dom.getAttribute('data-note-level'));
          return level >= 1 && level <= 3 ? { level } : { level: 3 };
        },
      },
      { tag: 'h1', attrs: { level: 1 } },
      { tag: 'h2', attrs: { level: 2 } },
      { tag: 'h3', attrs: { level: 3 } },
      { tag: 'h4', attrs: { level: 3 } },
      { tag: 'h5', attrs: { level: 3 } },
      { tag: 'h6', attrs: { level: 3 } },
    ],
  },
  pre: {
    code: true,
    defining: true,
    toDOM: () => ['pre', { class: 'note-pre' }, 0],
    parseDOM: [{ tag: 'pre', preserveWhitespace: 'full' }],
  },
  quote: { defining: true, toDOM: () => ['blockquote', 0], parseDOM: [{ tag: 'blockquote' }] },
  bullets: { toDOM: () => ['ul', 0], parseDOM: [{ tag: 'ul' }] },
  numbers: { toDOM: () => ['ol', 0], parseDOM: [{ tag: 'ol' }] },
  item: { defining: true, toDOM: () => ['li', 0], parseDOM: [{ tag: 'li' }] },
  break: { selectable: false, toDOM: () => ['br'], parseDOM: [{ tag: 'br' }] },
};

/** Marks as drawn, and read back from pasted markup by their tags (its styles become tags first,
 * in note-paste.js). */
const MARK_DOM = /** @type {Record<string, any>} */ ({
  bold: { toDOM: () => ['strong', 0], parseDOM: [{ tag: 'strong' }, { tag: 'b' }] },
  italic: { toDOM: () => ['em', 0], parseDOM: [{ tag: 'em' }, { tag: 'i' }] },
  underline: { toDOM: () => ['u', 0], parseDOM: [{ tag: 'u' }] },
  strike: { toDOM: () => ['s', 0], parseDOM: [{ tag: 's' }, { tag: 'del' }, { tag: 'strike' }] },
  highlight: { toDOM: () => ['mark', { class: 'note-mark' }, 0], parseDOM: [{ tag: 'mark' }] },
  mono: {
    toDOM: () => ['span', { class: 'note-mono' }, 0],
    parseDOM: [{ tag: 'span.note-mono' }, { tag: 'code' }, { tag: 'kbd' }, { tag: 'samp' }, {
      tag: 'tt',
    }],
  },
});

/**
 * The editor's schema: the kinds and marks of note-spec.json, each drawn as above; a link read
 * from pasted markup only when its address is one a note keeps.
 * @param {Own[]} own @param {Pages} pages
 */
export function noteSchema(own, pages) {
  const nodes = /** @type {Record<string, any>} */ ({});
  for (const [name, s] of Object.entries(/** @type {Record<string, any>} */ (SPEC.nodes))) {
    const spec = /** @type {Record<string, any>} */ ({ ...NODE_DOM[name] });
    if (s.content) spec.content = s.content;
    if (s.group) spec.group = s.group;
    if (s.marks !== undefined) spec.marks = s.marks;
    if (s.inline) spec.inline = true;
    if (s.attrs) {
      spec.attrs = Object.fromEntries(
        Object.entries(s.attrs).map(([k, v]) => [k, { default: v[0] }]),
      );
    }
    nodes[name] = spec;
  }
  const marks = /** @type {Record<string, any>} */ ({});
  for (const name of Object.keys(SPEC.marks)) marks[name] = MARK_DOM[name];
  marks.link = {
    inclusive: false,
    attrs: { href: { default: null }, page: { default: null } },
    // Drawn as the note read draws it: an address in a new tab; a page out of reach has none.
    // No tooltip: with the caret in it, its popover says where it goes.
    toDOM: (/** @type {any} */ m) => {
      if (m.attrs.href) {
        return [
          'a',
          { href: m.attrs.href, target: '_blank', rel: 'noopener noreferrer nofollow' },
          0,
        ];
      }
      const p = pages(m.attrs.page);
      return p.off || !p.href
        ? ['a', { class: 'note-link off', 'data-page': m.attrs.page }, 0]
        : ['a', { href: p.href, 'data-page': m.attrs.page }, 0];
    },
    parseDOM: [{
      tag: 'a[href], a[data-page]',
      getAttrs: (/** @type {HTMLElement} */ dom) => {
        const page = dom.getAttribute('data-page');
        const r = page ? { page } : readHref(dom.getAttribute('href') ?? '', [...own, ...HERE]);
        return 'error' in r ? false : r;
      },
    }],
  };
  return new Schema({ nodes, marks });
}

/**
 * A document as a note keeps it: a link holds only the one of its address or page it has.
 * @param {any} json
 * @returns {any}
 */
export function stored(json) {
  if (Array.isArray(json)) return json.map(stored);
  if (!json || typeof json !== 'object') return json;
  const out = /** @type {Record<string, any>} */ ({});
  for (const [k, v] of Object.entries(json)) out[k] = stored(v);
  if (json.type === 'link' && json.attrs) {
    out.attrs = Object.fromEntries(Object.entries(json.attrs).filter(([, v]) => v != null));
  }
  return out;
}

/** The lists a position is inside, innermost last. @param {any} $pos */
function listsAt($pos) {
  const out = [];
  for (let d = 1; d <= $pos.depth; d++) {
    const n = $pos.node(d);
    if (n.type.name === 'bullets' || n.type.name === 'numbers') out.push({ node: n, depth: d });
  }
  return out;
}

/**
 * Where the mark of a type runs round a position, within its block.
 * @param {any} $pos @param {any} type
 * @returns {{ from: number, to: number, mark: any } | null}
 */
export function markAround($pos, type) {
  const start = $pos.start();
  /** @type {{ from: number, to: number, mark: any }[]} */
  const runs = [];
  $pos.parent.forEach((/** @type {any} */ child, /** @type {number} */ offset) => {
    const a = start + offset, b = a + child.nodeSize;
    const m = type.isInSet(child.marks);
    const last = runs.at(-1);
    if (m && last && last.to === a && last.mark.eq(m)) last.to = b;
    else if (m) runs.push({ from: a, to: b, mark: m });
  });
  return runs.find((r) => r.from <= $pos.pos && $pos.pos <= r.to) ?? null;
}

/**
 * Commands run one after another as one change, each on what the last left; the last may do
 * nothing when `lastMay` (a paragraph made a paragraph).
 * @param {...any} cmds
 * @returns {import('prosemirror-state').Command}
 */
function steps(...cmds) {
  const lastMay = cmds.at(-1) === true;
  const list = lastMay ? cmds.slice(0, -1) : cmds;
  return (state, dispatch) => {
    /** @type {any} */
    let tr = null;
    let at = state;
    for (const [i, c] of list.entries()) {
      /** @type {any} */
      let got = null;
      const ok = c(at, (/** @type {any} */ t) => (got = t));
      if (!ok || !got) {
        if (lastMay && i === list.length - 1 && tr) break;
        return false;
      }
      if (!tr) tr = got;
      else for (const step of got.steps) tr.step(step);
      at = state.apply(tr);
    }
    if (dispatch && tr) dispatch(tr.scrollIntoView());
    return true;
  };
}

/**
 * The editor's commands, for the toolbar and its keys.
 * @param {Schema} schema
 */
function commandsOf(schema) {
  const n = schema.nodes, m = schema.marks;
  /** @type {import('prosemirror-state').Command} */
  const indent = (state, dispatch) => {
    const lists = listsAt(state.selection.$from);
    if (!lists.length) return false;
    // In a list Tab stays in the note: it indents where it can (not past the deepest a note
    // allows, nor a list's first item), and otherwise does nothing.
    if (lists.length < SPEC.limits.listDepth) sinkListItem(n.item)(state, dispatch);
    return true;
  };
  /** @param {any} type @returns {import('prosemirror-state').Command} */
  const list = (type) => (state, dispatch) => {
    const lists = listsAt(state.selection.$from);
    const inner = lists.at(-1);
    if (!inner) return wrapInList(type)(state, dispatch);
    if (inner.node.type === type) return liftListItem(n.item)(state, dispatch);
    if (dispatch) {
      const pos = state.selection.$from.before(inner.depth);
      dispatch(state.tr.setNodeMarkup(pos, type));
    }
    return true;
  };
  /** @param {string} kind @returns {import('prosemirror-state').Command} */
  const block = (kind) => (state, dispatch) => {
    const $f = state.selection.$from;
    let inQuote = false;
    for (let d = 1; d <= $f.depth; d++) if ($f.node(d).type === n.quote) inQuote = true;
    if (kind === 'quote') {
      if (inQuote) return lift(state, dispatch);
      // A heading or pre-formatted text is quoted as a paragraph: a quote holds no other.
      return wrapIn(n.quote)(state, dispatch) ||
        steps(setBlockType(n.paragraph), wrapIn(n.quote))(state, dispatch);
    }
    const level = /^h([1-3])$/.exec(kind)?.[1];
    const to = level
      ? setBlockType(n.heading, { level: Number(level) })
      : kind === 'pre'
      ? setBlockType(n.pre)
      : setBlockType(n.paragraph);
    // Out of a quote first: another kind of block is never a quote too.
    return inQuote ? steps(lift, to, true)(state, dispatch) : to(state, dispatch);
  };
  return {
    bold: toggleMark(m.bold),
    italic: toggleMark(m.italic),
    underline: toggleMark(m.underline),
    strike: toggleMark(m.strike),
    highlight: toggleMark(m.highlight),
    mono: toggleMark(m.mono),
    bullets: list(n.bullets),
    numbers: list(n.numbers),
    indent,
    outdent: liftListItem(n.item),
    block,
    breakLine: chainCommands(exitCode, (state, dispatch) => {
      dispatch?.(state.tr.replaceSelectionWith(n.break.create()).scrollIntoView());
      return true;
    }),
  };
}

/**
 * The toolbar's buttons: what each does, its words and keys, and the mark it shows on.
 * @type {{ key: string, label: string, keys: string, face: any, mark?: string }[]}
 */
const MARK_BUTTONS = [
  { key: 'bold', label: 'Bold', keys: 'Ctrl/Cmd+B', face: html`<b>B</b>`, mark: 'bold' },
  { key: 'italic', label: 'Italic', keys: 'Ctrl/Cmd+I', face: html`<i>I</i>`, mark: 'italic' },
  {
    key: 'underline',
    label: 'Underline',
    keys: 'Ctrl/Cmd+U',
    face: html`<u>U</u>`,
    mark: 'underline',
  },
  {
    key: 'strike',
    label: 'Strikethrough',
    keys: 'Ctrl/Cmd+Shift+X',
    face: html`<s>S</s>`,
    mark: 'strike',
  },
  {
    key: 'highlight',
    label: 'Highlight',
    keys: 'Ctrl/Cmd+Shift+H',
    face: html`<span class="note-mark">H</span>`,
    mark: 'highlight',
  },
  {
    key: 'mono',
    label: 'Monospace',
    keys: 'Ctrl/Cmd+Shift+M',
    face: html`<span class="note-mono">M</span>`,
    mark: 'mono',
  },
];

/** The block menu's kinds: its key, its words, its keys. @type {[string, string, string][]} */
const BLOCKS = [
  ['paragraph', 'Paragraph', 'Ctrl/Cmd+Alt+0'],
  ['h1', 'Heading 1', 'Ctrl/Cmd+Alt+1'],
  ['h2', 'Heading 2', 'Ctrl/Cmd+Alt+2'],
  ['h3', 'Heading 3', 'Ctrl/Cmd+Alt+3'],
  ['pre', 'Pre-formatted', ''],
  ['quote', 'Quote', ''],
];

/** Which block the selection is in, as the block menu names it. @param {any} state */
function blockOf(state) {
  const $f = state.selection.$from;
  for (let d = $f.depth; d > 0; d--) if ($f.node(d).type.name === 'quote') return 'quote';
  const p = $f.parent;
  if (p.type.name === 'heading') return `h${p.attrs.level}`;
  return p.type.name === 'pre' ? 'pre' : 'paragraph';
}

/** Whether a mark is on where the selection is. @param {any} state @param {any} type */
function markOn(state, type) {
  const { from, to, empty, $from } = state.selection;
  if (empty) return !!type.isInSet(state.storedMarks || $from.marks());
  return state.doc.rangeHasMark(from, to, type);
}

/**
 * The note editor: the toolbar, the text, the count near the limit, and the link popovers.
 * @param {{ value: any, onChange: (doc: any) => void, id?: string, placeholder?: string,
 *   disabled?: boolean, own?: Own[], pages?: Pages, open?: (page: string) => void,
 *   bad?: string, onLeave?: () => void }} p
 */
export function NoteEditor(
  {
    value,
    onChange,
    id,
    placeholder = '',
    disabled = false,
    own = [],
    pages = noPages,
    open,
    bad,
    onLeave,
  },
) {
  const host = useRef(/** @type {HTMLDivElement | null} */ (null));
  const wrap = useRef(/** @type {HTMLDivElement | null} */ (null));
  const bar = useRef(/** @type {HTMLDivElement | null} */ (null));
  const viewRef = useRef(/** @type {EditorView | null} */ (null));
  const [, setTick] = useState(0);
  const [, setFocus] = useState(0);
  const [pop, setPop] = useState(
    /** @type {null | { from: number, to: number, text: string,
    error?: string, existing: boolean, x: number, y: number }} */ (null),
  );
  const props = useRef({ onChange, pages, open, own, disabled });
  props.current = { onChange, pages, open, own, disabled };
  const known = () => [...props.current.own, ...HERE];

  useEffect(() => {
    const schema = noteSchema(own, (page) => props.current.pages(page));
    const cmd = commandsOf(schema);
    const linkType = schema.marks.link;
    /** Opens the address popover over the selection, or over the link the caret is in. */
    const askLink = (/** @type {EditorView} */ view) => {
      const { state } = view;
      let { from, to } = state.selection;
      const around = markAround(state.selection.$from, linkType);
      const existing = !!around &&
        (state.selection.empty || (from >= around.from && to <= around.to));
      if (existing && around) ({ from, to } = around);
      const a = around?.mark.attrs;
      const text = existing ? (a.href ?? pageAddress(a.page)) : '';
      const c = view.coordsAtPos(from),
        w = /** @type {HTMLElement} */ (wrap.current).getBoundingClientRect();
      const z = zoomOf(wrap.current);
      setPop({ from, to, text, existing, x: (c.left - w.left) / z, y: (c.bottom - w.top) / z + 4 });
      return true;
    };
    /** The page's address on this server, for editing a link to one. @param {string} page */
    const pageAddress = (page) => {
      const h = known()[0];
      return h ? `${h.origin}${h.base}${page}` : page;
    };
    /** Follows the link at a position. @param {EditorState} state @param {number} pos */
    const follow = (state, pos) => {
      const around = markAround(state.doc.resolve(pos), linkType);
      if (!around) return false;
      const a = around.mark.attrs;
      if (a.href) globalThis.open(a.href, '_blank', 'noopener,noreferrer');
      else if (!props.current.pages(a.page).off) props.current.open?.(a.page);
      return true;
    };
    const autolink = new InputRule(
      /(?<=^|\s)((?:https?:\/\/|www\.)\S+)\s$/i,
      (state, match, start, end) => {
        const addr = trailingAddress(match[1]);
        if (!addr) return null;
        const r = readHref(addr, known());
        if ('error' in r) return null;
        const from = start, to = start + addr.length;
        if (state.doc.rangeHasMark(from, to, linkType)) return null;
        return state.tr.addMark(from, to, linkType.create(r)).insertText(match[0].slice(-1), end);
      },
    );
    const placeholderPlugin = new Plugin({
      props: {
        decorations: (state) => {
          const d = state.doc;
          if (
            !placeholder || d.childCount !== 1 || d.firstChild?.type.name !== 'paragraph' ||
            d.firstChild.content.size
          ) {
            return null;
          }
          return DecorationSet.create(d, [
            Decoration.node(0, d.firstChild.nodeSize, {
              class: 'note-empty',
              'data-placeholder': placeholder,
            }),
          ]);
        },
      },
    });
    const pastePlugin = new Plugin({
      props: {
        // Markup with no inline style left for the policy to refuse (note-paste.js).
        transformPastedHTML: (html) => cleanPastedHTML(html),
        // An address pasted over text links it; pasted alone, it comes in as its own link.
        handlePaste: (view, event) => {
          const text = event.clipboardData?.getData('text/plain')?.trim() ?? '';
          if (!text || /\s/.test(text) || !/^(https?:\/\/|www\.)/i.test(text)) return false;
          const r = readHref(text, known());
          if ('error' in r) return false;
          const { state } = view;
          const { from, to, empty } = state.selection;
          const mark = linkType.create(r);
          const tr = empty
            ? state.tr.insert(from, schema.text(text, [mark]))
            : state.tr.removeMark(from, to, linkType).addMark(from, to, mark);
          view.dispatch(tr.scrollIntoView());
          return true;
        },
        handleClick: (view, pos, event) =>
          (event.ctrlKey || event.metaKey) && follow(view.state, pos),
      },
    });
    const doc = value ? schema.nodeFromJSON(value) : undefined;
    const state = EditorState.create({
      schema,
      doc,
      plugins: [
        history(),
        inputRules({
          rules: [
            wrappingInputRule(/^\s*([-*])\s$/, schema.nodes.bullets),
            wrappingInputRule(/^(\d+)\.\s$/, schema.nodes.numbers),
            autolink,
          ],
        }),
        keymap({
          'Mod-z': undo,
          'Shift-Mod-z': redo,
          'Mod-y': redo,
          'Mod-b': cmd.bold,
          'Mod-i': cmd.italic,
          'Mod-u': cmd.underline,
          'Mod-Shift-x': cmd.strike,
          'Mod-Shift-h': cmd.highlight,
          'Mod-Shift-m': cmd.mono,
          'Mod-k': (_s, _d, view) => (view ? askLink(view) : true),
          'Mod-Enter': (s) => follow(s, s.selection.from),
          'Mod-Alt-0': cmd.block('paragraph'),
          'Mod-Alt-1': cmd.block('h1'),
          'Mod-Alt-2': cmd.block('h2'),
          'Mod-Alt-3': cmd.block('h3'),
          Enter: splitListItem(schema.nodes.item),
          Tab: cmd.indent,
          'Shift-Tab': cmd.outdent,
          'Shift-Enter': cmd.breakLine,
          Backspace: undoInputRule,
          'Alt-F10': () => {
            /** @type {HTMLElement | null} */ (bar.current?.querySelector('[tabindex="0"]'))
              ?.focus();
            return true;
          },
        }),
        keymap(baseKeymap),
        placeholderPlugin,
        pastePlugin,
      ],
    });
    const view = new EditorView(/** @type {HTMLElement} */ (host.current), {
      state,
      editable: () => !props.current.disabled,
      attributes: {
        class: 'note-text',
        role: 'textbox',
        'aria-multiline': 'true',
        ...(id ? { id, 'aria-labelledby': 'lbl-' + id } : {}),
      },
      dispatchTransaction(tr) {
        const next = view.state.apply(tr);
        view.updateState(next);
        setTick((t) => t + 1);
        if (tr.docChanged) {
          const json = stored(next.doc.toJSON());
          props.current.onChange(isEmpty(json) ? null : json);
        }
      },
      handleDOMEvents: {
        focus: () => (setFocus((f) => f + 1), false),
        blur: () => (setFocus((f) => f + 1), false),
      },
    });
    viewRef.current = view;
    /** @type {any} */ (view).askLink = askLink;
    /** @type {any} */ (view).follow = follow;
    /** @type {any} */ (view).cmd = cmd;
    setTick((t) => t + 1);
    return () => view.destroy();
  }, []);

  // Checked at Save, as every typed field is (S12.18.3).
  useEffect(() => {
    const el = wrap.current;
    const on = () => onLeave?.();
    el?.addEventListener('mk-check', on);
    return () => el?.removeEventListener('mk-check', on);
  });

  const view = viewRef.current;
  const state = view?.state;
  const run = (/** @type {any} */ c) => {
    if (!view) return;
    c(view.state, view.dispatch, view);
    view.focus();
  };
  const cmd = /** @type {any} */ (view)?.cmd;
  const inPre = state?.selection.$from.parent.type.name === 'pre';
  const block = state ? blockOf(state) : 'paragraph';
  const lists = state ? listsAt(state.selection.$from) : [];
  const caretLink = state && view?.hasFocus() && state.selection.empty && !pop
    ? markAround(state.selection.$from, state.schema.marks.link)
    : null;

  /** The toolbar's keys: ← → along it, Home and End to its ends, Escape back to the text. */
  const barKey = (/** @type {KeyboardEvent} */ e) => {
    const all = /** @type {HTMLElement[]} */ ([...(bar.current?.querySelectorAll('button') ?? [])]);
    const at = all.indexOf(/** @type {HTMLElement} */ (document.activeElement));
    const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: all.length - 1 }[e.key];
    if (e.key === 'Escape') {
      e.preventDefault();
      view?.focus();
      return;
    }
    if (to === undefined || at < 0) return;
    e.preventDefault();
    const next = all[(to + all.length) % all.length];
    for (const b of all) b.tabIndex = b === next ? 0 : -1;
    next.focus();
  };
  const keep = (/** @type {MouseEvent} */ e) => e.preventDefault();
  const tool = (
    /** @type {{ key: string, label: string, keys?: string, face: any, on?: boolean,
    off?: string, act: () => void, first?: boolean }} */ t,
  ) =>
    html`
      <button type="button" class=${'note-tool' + (t.on ? ' on' : '')} aria-label=${t.label}
        aria-pressed=${t.on === undefined ? undefined : String(t.on)} data-tip=${t.off
          ? `${t.label}: ${t.off}`
          : t.keys
          ? `${t.label} (${t.keys})`
          : t.label} tabindex=${t.first ? 0 : -1} aria-disabled=${t.off ? 'true' : undefined}
        onMouseDown=${keep} onClick=${() => !t.off && t.act()}>${t.face}</button>
    `;

  const applyLink = () => {
    if (!view || !pop) return;
    const r = readHref(pop.text, known());
    if ('error' in r) {
      setPop({ ...pop, error: r.error });
      return;
    }
    const type = view.state.schema.marks.link;
    const mark = type.create(r);
    let tr = view.state.tr;
    if (pop.from === pop.to) {
      tr = tr.insert(pop.from, view.state.schema.text(pop.text.trim(), [mark]));
    } else tr = tr.removeMark(pop.from, pop.to, type).addMark(pop.from, pop.to, mark);
    view.dispatch(tr.setSelection(TextSelection.create(tr.doc, tr.mapping.map(pop.to))));
    setPop(null);
    view.focus();
  };
  const removeLink = (/** @type {number} */ from, /** @type {number} */ to) => {
    if (!view) return;
    view.dispatch(view.state.tr.removeMark(from, to, view.state.schema.marks.link));
    setPop(null);
    view.focus();
  };

  const chars = state ? [...state.doc.textContent].length : 0;
  const near = chars >= SPEC.limits.chars * 0.8;
  const z = zoomOf(wrap.current);
  const caretAt = caretLink && view && wrap.current
    ? (() => {
      const c = view.coordsAtPos(caretLink.from), w = wrap.current.getBoundingClientRect();
      return { x: (c.left - w.left) / z, y: (c.bottom - w.top) / z + 4 };
    })()
    : null;
  const linkTip = (/** @type {any} */ a) => {
    if (a.href) return a.href;
    const p = pages(a.page);
    return p.off ? `${p.tip} · ${p.why ?? 'Not shared with you'}` : p.tip;
  };

  return html`
    <div class=${'note' + (bad ? ' bad' : '') + (disabled ? ' off' : '')} ref=${wrap}
      data-tip=${bad} data-kind="note"
      onFocusOut=${(/** @type {FocusEvent} */ e) => {
        const to = /** @type {Node | null} */ (e.relatedTarget);
        if (!to || !wrap.current?.contains(to)) onLeave?.();
      }}>
      <div class="note-bar" role="toolbar" aria-label="Formatting" ref=${bar} onKeyDown=${barKey}
        aria-disabled=${disabled ? 'true' : undefined}>
        <button type="button" class="note-tool note-block" tabindex="0" aria-haspopup="menu"
          data-tip="The kind of text" onMouseDown=${keep} onClick=${(/** @type {MouseEvent} */ e) =>
            !disabled && openMenu(
              e,
              BLOCKS.map(([k, label]) => ({
                label,
                on: block === k,
                onSelect: () => run(cmd.block(k)),
              })),
            )}>${BLOCKS.find(([k]) => k === block)
            ?.[1]}<${Icon} name="chev" cls="note-chev" /></button>
        <span class="note-gap" aria-hidden="true"></span>
        ${MARK_BUTTONS.map((b) =>
          tool({
            ...b,
            on: !!state && markOn(state, state.schema.marks[/** @type {string} */ (b.mark)]),
            off: disabled ? 'off' : inPre ? 'not in pre-formatted text' : undefined,
            act: () => run(cmd[b.key]),
          })
        )}
        <span class="note-gap" aria-hidden="true"></span>
        ${tool({
          key: 'link',
          label: 'Link',
          keys: 'Ctrl/Cmd+K',
          face: html`<${Icon} name="link" />`,
          on: !!state && markOn(state, state.schema.marks.link),
          off: disabled ? 'off' : inPre ? 'not in pre-formatted text' : undefined,
          act: () => view && /** @type {any} */ (view).askLink(view),
        })}
        <span class="note-gap" aria-hidden="true"></span>
        ${tool({
          key: 'bullets',
          label: 'Bulleted list',
          keys: 'type - or *',
          face: html`<${Icon} name="list" />`,
          on: lists.at(-1)?.node.type.name === 'bullets',
          off: disabled ? 'off' : undefined,
          act: () => run(cmd.bullets),
        })}
        ${tool({
          key: 'numbers',
          label: 'Numbered list',
          keys: 'type 1.',
          face: html`<${Icon} name="list-num" />`,
          on: lists.at(-1)?.node.type.name === 'numbers',
          off: disabled ? 'off' : undefined,
          act: () => run(cmd.numbers),
        })}
        ${tool({
          key: 'outdent',
          label: 'Outdent',
          keys: 'Shift+Tab',
          face: html`<${Icon} name="outdent" />`,
          off: disabled ? 'off' : !lists.length ? 'in a list only' : undefined,
          act: () => run(cmd.outdent),
        })}
        ${tool({
          key: 'indent',
          label: 'Indent',
          keys: 'Tab',
          face: html`<${Icon} name="indent" />`,
          off: disabled
            ? 'off'
            : !lists.length
            ? 'in a list only'
            : lists.length >= SPEC.limits.listDepth
            ? `lists go ${SPEC.limits.listDepth} deep at most`
            : undefined,
          act: () => run(cmd.indent),
        })}
      </div>
      <div class="note-body" ref=${host}></div>
      ${near
        ? html`
          <div class=${'note-count small' + (chars > SPEC.limits.chars ? ' over' : '')}
            aria-live="polite">${chars.toLocaleString('en-US')} of ${SPEC.limits.chars
              .toLocaleString('en-US')}</div>
        `
        : null}
      ${caretLink && caretAt
        ? html`
          <div class="note-pop caret" style=${{ left: caretAt.x + 'px', top: caretAt.y + 'px' }}
            role="group" aria-label="The link">
            <span class="note-pop-addr small">${linkTip(caretLink.mark.attrs)}</span>
            <button type="button" class="link-btn" onMouseDown=${keep} data-tip="Open it (Ctrl/Cmd+Enter)"
              onClick=${() =>
                state && view && /** @type {any} */
                (view).follow(state, caretLink.from)}>open</button>
            <span class="sep" aria-hidden="true">·</span>
            <button type="button" class="link-btn" onMouseDown=${keep} data-tip="Change it (Ctrl/Cmd+K)"
              onClick=${() => view && /** @type {any} */ (view).askLink(view)}>edit</button>
            <span class="sep" aria-hidden="true">·</span>
            <button type="button" class="link-btn" onMouseDown=${keep} data-tip="Take the link off"
              onClick=${() => removeLink(caretLink.from, caretLink.to)}>remove</button>
          </div>
        `
        : null}
      ${pop
        ? html`
          <${LinkPop} pop=${pop} id=${(id || 'note') + '-link'}
            onText=${(/** @type {string} */ text) => setPop({ ...pop, text, error: undefined })}
            onApply=${applyLink} onRemove=${() => removeLink(pop.from, pop.to)}
            onClose=${() => {
              setPop(null);
              view?.focus();
            }} />
        `
        : null}
    </div>
  `;
}

/** The page's zoom (the mockup draws at zoom 2), for placing a popover by the text's box. */
function zoomOf(/** @type {Element | null} */ el) {
  if (!el) return 1;
  const z = Number(getComputedStyle(document.documentElement).zoom);
  return z > 0 ? z : 1;
}

/**
 * The address popover: the address, Apply, Remove for a link already there; Enter applies and
 * Escape closes, the focus going back to the text.
 * @param {{ pop: { text: string, error?: string, existing: boolean, x: number, y: number },
 *   id: string, onText: (t: string) => void, onApply: () => void, onRemove: () => void,
 *   onClose: () => void }} p
 */
function LinkPop({ pop, id, onText, onApply, onRemove, onClose }) {
  const box = useRef(/** @type {HTMLDivElement | null} */ (null));
  useEffect(() => {
    /** @type {HTMLElement | null} */ (box.current?.querySelector('input'))?.focus();
  }, []);
  return html`
    <div class="note-pop edit" ref=${box} style=${{ left: pop.x + 'px', top: pop.y + 'px' }}
      role="dialog" aria-label=${pop.existing ? 'Change the link' : 'Make a link'}
      onKeyDown=${(/** @type {KeyboardEvent} */ e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          e.stopPropagation();
          onClose();
        } else if (e.key === 'Enter' && /** @type {HTMLElement} */ (e.target).tagName === 'INPUT') {
          e.preventDefault();
          onApply();
        }
      }}>
      <${Field} label="Address" id=${id} error=${pop.error}>
        <${ValueInput} value=${pop.text} onInput=${onText} clear=${true}
          placeholder="https://example.com" />
        </${Field}>
        <div class="note-pop-acts">
        ${pop.existing
          ? html`<button type="button" class="btn" onClick=${onRemove}>Remove</button>`
          : null}
        <button type="button" class="btn primary" onClick=${onApply}>Apply</button>
      </div>
        </div>
  `;
}
