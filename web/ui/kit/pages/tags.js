// The ui-kit's page for several of a list (S12.18.12): tags that may grow, people picked only,
// many chips in rows or on one line.
import { useRef, useState } from 'preact/hooks';
import { html } from '../html.js';
import { Field } from '../fields.js';
import { TagInput } from '../tags.js';
import { Demo, Page, show } from './parts.js';

const TAGS = [
  { key: 'Tag_work', label: 'work', uses: 41 },
  { key: 'Tag_trips', label: 'work trips', uses: 6 },
  { key: 'Tag_coffee', label: 'coffee', uses: 23 },
  { key: 'Tag_medical', label: 'medical', uses: 9 },
  { key: 'Tag_wood', label: 'woodworking', uses: 2 },
  { key: 'Tag_2026', label: '2026', uses: 14 },
  { key: 'Tag_gifts', label: 'gifts', uses: 5 },
];
const PEOPLE = [
  { key: 'Persn_emma', label: 'Emma Griffin' },
  { key: 'Persn_noah', label: 'Noah Griffin' },
  { key: 'Persn_margaret', label: 'Margaret Griffin' },
  { key: 'Persn_tom', label: 'Tom Griffin' },
  { key: 'Persn_sam', label: 'Sam Okafor' },
];
const MANY = Array.from({ length: 20 }, (_, i) => ({
  key: `Tag_m${i}`,
  label: [
    'groceries',
    'household',
    'kids',
    'school',
    'sports',
    'travel',
    'car',
    'garden',
    'pets',
    'books',
    'music',
    'gifts',
    'health',
    'dental',
    'vision',
    'insurance',
    'taxes',
    'charity',
    'repairs',
    'fees',
  ][i],
  uses: 20 - i,
}));

/** One field and its report: the keys it holds, and the names it made. @param {any} p */
function Tags({ id, title, note, first = [], items = TAGS, ...props }) {
  const [keys, setKeys] = useState(/** @type {string[]} */ (first));
  const [made, setMade] = useState(/** @type {{ key: string, label: string }[]} */ ([]));
  const [line, setLine] = useState('nothing yet');
  // Names made this time, as soon as they are made: the change that holds them comes before
  // the page draws again.
  const names = useRef(/** @type {Record<string, string>} */ ({}));
  const all = [...items, ...made];
  return html`
    <${Demo} id=${id} title=${title} note=${note} report=${line}>
      <${Field} label=${props.noun?.[1] === 'people' ? 'For' : 'Tags'} id=${id}>
        <${TagInput} value=${keys} items=${all} onChange=${(/** @type {string[]} */ k) => {
          setKeys(k);
          setLine(show(k.map((x) => all.find((i) => i.key === x)?.label ?? names.current[x] ?? x)));
        }} onCreate=${(/** @type {string} */ name) => {
          const key = `Tag_new_${Object.keys(names.current).length + 1}`;
          names.current[key] = name.toLowerCase();
          setMade((m) => [...m, { key, label: name.toLowerCase() }]);
          return key;
        }}
          ...${props} />
        </${Field}>
        </${Demo}>
  `;
}

export default function TagsPage() {
  return html`
    <${Page} title="Several of a list" about=${html`Each chosen item is a chip with its own ×,
      and after them a box to type in; typing lists the matches below it, the most used first
      before anything is typed. Where the list may grow (tags), a name that matches none
      becomes a new item; where it can't (people), it is refused. The field grows a row at a
      time to <code>maxRows</code> rows of chips and then scrolls; kept to one line, it scrolls
      sideways behind a count of the chips out of sight.`}
      keys=${[
        [
          'Typing',
          'Lists the items that match: the whole name, its start, a later word, then anywhere in it.',
        ],
        ['↓ / ↑', 'Opens the list on the first / last, then moves through it, round from the end.'],
        ['Home / End', 'With the list open: its first / last. Closed: the caret’s.'],
        ['Enter', 'Adds the item reached, or what is typed. Never submits the form.'],
        [',', 'Adds what is typed; the comma is never typed itself.'],
        ['Backspace', 'In an empty box: takes off the last chip (not while the key repeats).'],
        ['Escape', 'Closes the list, and goes no further (a dialog around it stays open).'],
        ['Paste', 'Names separated by commas: each added.'],
        ['Tab', 'Adds what is typed, and moves on.'],
      ]}
      props=${[
        ['value', 'string[]', 'The keys of the chosen items.'],
        ['items', '{ key, label, uses? }[]', 'Every item that may be chosen.'],
        ['onChange', '(keys: string[]) => void', 'Hears the keys after each change.'],
        ['allowNew', 'boolean', 'A name matching none is made, through onCreate.'],
        ['onCreate', '(name: string) => string', 'Makes a new item, giving its key.'],
        ['noun', '[one, many]', 'What one item is called: Remove work, 3 tags before.'],
        ['autoGrow', 'boolean', 'Grows to maxRows rows (default); off, one line.'],
        ['maxRows', 'number', 'Rows of chips before it scrolls (3).'],
        ['readonly, disabled', 'boolean', 'Read: the names as text. Off: no changes.'],
      ]}>
      <${Tags} id="tags" title="Tags: may grow" allowNew=${true}
        placeholder="ex: coffee, work" />
      <${Tags} id="tags-filled" title="Tags, filled" allowNew=${true}
        first=${['Tag_work', 'Tag_coffee']} />
      <${Tags} id="people" title="People: picked only" items=${PEOPLE}
        noun=${['person', 'people']} first=${['Persn_emma']} />
      <${Tags} id="many" title="Many: three rows, then it scrolls" allowNew=${true}
        items=${MANY} first=${MANY.map((i) => i.key)} />
      <${Tags} id="one-line" title="One line, with a count" allowNew=${true} items=${MANY}
        autoGrow=${false} first=${MANY.map((i) => i.key)} note="autoGrow=false, as a filter" />
      <${Tags} id="tags-off" title="Off" first=${['Tag_work']} disabled=${true} />
      <${Tags} id="tags-read" title="Read" first=${['Tag_work', 'Tag_medical']}
        readonly=${true} />
      </${Page}>
  `;
}
