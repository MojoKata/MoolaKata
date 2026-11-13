/// <reference lib="deno.ns" />
// A note's links and its document (requirements S12.18.15): every address read, refused or kept
// as a page; every kind of block and mark checked against the table the editor and the server
// share; the limits; the plain text.
import { isHref, isPage, readHref, trailingAddress } from '../note-links.js';
import { checkNote, follows, isEmpty, plainText, SPEC, terms } from '../note-check.js';
import { equal } from './assert.js';

const OWN = [{ origin: 'https://moolakata.loco', base: '/ui/' }];

Deno.test('an address on the web, as typed or pasted', () => {
  equal(
    [
      'https://example.com/a?b=1#c',
      'http://example.com',
      '  https://example.com  ',
      'www.example.com/x',
      'HTTPS://EXAMPLE.COM/Path',
    ].map((t) => readHref(t)),
    [
      { href: 'https://example.com/a?b=1#c' },
      { href: 'http://example.com/' },
      { href: 'https://example.com/' },
      { href: 'https://www.example.com/x' },
      { href: 'https://example.com/Path' },
    ],
  );
});

Deno.test('what is refused: other schemes, a password in it, half an address, too long', () => {
  const why = (/** @type {string} */ t) => /** @type {any} */ (readHref(t)).error;
  equal(
    [
      why(''),
      why('javascript:alert(1)'),
      why('data:text/html,<b>x</b>'),
      why('mailto:a@b.c'),
      why('ftp://example.com'),
      why('https://user:pw@example.com'),
      why('example.com'),
      why('/ui/accounts'),
      why('https://' + 'a'.repeat(2000) + '.com'),
    ],
    [
      'Type an address, such as https://example.com.',
      'Only http and https addresses.',
      'Only http and https addresses.',
      'Only http and https addresses.',
      'Only http and https addresses.',
      'An address with a password in it is refused.',
      'Type a whole address, starting https://.',
      'Type a whole address, starting https://.',
      'At most 2,000 characters.',
    ],
  );
});

Deno.test("this server's address is kept as the page alone; its files and API are refused", () => {
  const r = (/** @type {string} */ t) => readHref(t, OWN);
  equal(
    [
      r('https://moolakata.loco/ui/accounts/Acct_7Q2'),
      r('https://moolakata.loco/ui/budgets/Bud_3K9?month=2026-10#cash'),
      r('https://moolakata.loco/ui/settings'),
      r('https://moolakata.loco/ui/linked/Lnk_1/accounts/Acct_7Q2'),
      r('https://moolakata.loco/api/accounts'),
      r('https://moolakata.loco/ui/v/0.1.0/app/main.js'),
      r('https://moolakata.loco/ui/'),
      r('https://other.loco/ui/accounts/Acct_7Q2'),
      r('http://moolakata.loco/ui/accounts'),
    ],
    [
      { page: 'accounts/Acct_7Q2' },
      { page: 'budgets/Bud_3K9?month=2026-10#cash' },
      { page: 'settings' },
      { href: 'https://moolakata.loco/ui/linked/Lnk_1/accounts/Acct_7Q2' },
      { error: 'Not a page of MoolaKata.' },
      { error: 'Not a page of MoolaKata.' },
      { error: 'Not a page of MoolaKata.' },
      { href: 'https://other.loco/ui/accounts/Acct_7Q2' },
      // Another origin (http, not https): an address like any other.
      { href: 'http://moolakata.loco/ui/accounts' },
    ],
  );
});

Deno.test('a page as a note keeps one, and an address', () => {
  equal(
    [
      'accounts',
      'accounts/Acct_7Q2',
      'budgets/Bud_3K9/?m=1#x',
      '',
      '/accounts',
      'accounts/../settings',
      'v/1/app.js',
      'api/x',
      'linked/L/accounts',
      'Accounts',
      'a b',
      42,
    ].map(isPage),
    [true, true, true, false, false, false, false, false, false, false, false, false],
  );
  equal(
    ['https://example.com/', 'https://example.com', 'javascript:x', null].map(isHref),
    [true, false, false, false],
  );
});

Deno.test('a bare address typed, closing punctuation left out', () => {
  equal(
    [
      trailingAddress('see https://example.com/a.'),
      trailingAddress('www.example.com),'),
      trailingAddress('xhttps://example.com'),
      trailingAddress('no address'),
      trailingAddress('https://'),
    ],
    ['https://example.com/a', 'www.example.com', null, null, null],
  );
});

/** @param {string} text @param {any[]} [marks] */
const t = (text, marks) => (marks ? { type: 'text', text, marks } : { type: 'text', text });
/** @param {...any} c */
const p = (...c) => ({ type: 'paragraph', content: c });
/** @param {...any} c */
const doc = (...c) => ({ type: 'doc', content: c });
/** @param {...any} c */
const li = (...c) => ({ type: 'item', content: c });
/** @param {any} d */
const problems = (d) => checkNote(d).problems;

Deno.test('every kind of block and mark a note holds passes', () => {
  const all = doc(
    { type: 'heading', attrs: { level: 1 }, content: [t('H')] },
    { type: 'heading', attrs: { level: 2 }, content: [t('S')] },
    { type: 'heading', attrs: { level: 3 }, content: [t('T')] },
    p(
      ...['bold', 'italic', 'underline', 'strike', 'highlight', 'mono'].map((m) =>
        t(m, [{ type: m }])
      ),
      { type: 'break' },
      t('a', [{ type: 'link', attrs: { href: 'https://example.com/' } }]),
      t('p', [{ type: 'bold' }, { type: 'link', attrs: { page: 'accounts/Acct_1' } }]),
    ),
    { type: 'pre', content: [t('  kept\n  as typed')] },
    { type: 'quote', content: [p(t('q')), { type: 'bullets', content: [li(p(t('i')))] }] },
    { type: 'numbers', content: [li(p(t('1')), { type: 'bullets', content: [li(p(t('2')))] })] },
    p(),
  );
  equal(problems(all), []);
  equal(checkNote(all).chars, 64);
});

Deno.test('what a note refuses, each in its place', () => {
  equal(problems(null), ['Not a note.']);
  equal(problems({ type: 'paragraph' }), ['Not a note.']);
  equal(problems(doc()), ['doc: holds nothing']);
  equal(problems({ ...doc(p(t('x'))), extra: 1 }), ['doc: extra not known']);
  equal(problems(doc({ type: 'table' })), [
    'doc: holds table',
    'doc[0]: “table” is not a kind a note holds',
  ]);
  equal(problems(doc({ type: 'doc' })), [
    'doc: holds doc',
    'doc[0]: “doc” is not a kind a note holds',
  ]);
  equal(problems(doc(p(t('x')), 'x')), ['doc: holds paragraph, ', 'doc[1]: not a node']);
  equal(problems(doc({ ...p(t('x')), style: 'x' })), ['doc[0]: style not known']);
  // Attributes: a heading's level, and none where none belong.
  equal(problems(doc({ type: 'heading', content: [t('x')] })), ['doc[0].heading: no level']);
  equal(problems(doc({ type: 'heading', attrs: { level: 4 }, content: [t('x')] })), [
    'doc[0].heading: level 4',
  ]);
  equal(problems(doc({ type: 'heading', attrs: { level: 0 }, content: [t('x')] })), [
    'doc[0].heading: level 0',
  ]);
  equal(problems(doc({ type: 'heading', attrs: { level: 2, id: 'x' }, content: [t('x')] })), [
    'doc[0].heading: id not known',
  ]);
  equal(problems(doc({ ...p(t('x')), attrs: { a: 1 } })), [
    'doc[0].paragraph: attributes where none belong',
  ]);
  // Text: some, and only in a text node.
  equal(problems(doc(p({ type: 'text', text: '' }))), ['doc[0].paragraph[0].text: no text']);
  equal(problems(doc({ ...p(), text: 'x' })), ['doc[0].paragraph: text where none belongs']);
  equal(problems(doc(p({ type: 'break', content: [] }))), [
    'doc[0].paragraph[0].break: holds nothing',
  ]);
  // What each holds: a list its items, an item a paragraph first, a quote no heading.
  equal(problems(doc({ type: 'bullets', content: [p(t('x'))] })), [
    'doc[0].bullets: holds paragraph',
  ]);
  equal(
    problems(
      doc({ type: 'bullets', content: [li({ type: 'bullets', content: [li(p(t('x')))] })] }),
    ),
    [
      'doc[0].bullets[0].item: holds bullets',
    ],
  );
  equal(
    problems(
      doc({
        type: 'quote',
        content: [{ type: 'heading', attrs: { level: 2 }, content: [t('x')] }],
      }),
    ),
    [
      'doc[0].quote: holds heading',
    ],
  );
  equal(problems(doc(p(p(t('x'))))), ['doc[0].paragraph: holds paragraph']);
});

Deno.test('marks: known, once, none in pre-formatted text, a link to one place a note keeps', () => {
  const at = (/** @type {any[]} */ marks) => problems(doc(p(t('x', marks))));
  equal(at([{ type: 'color' }]), ['doc[0].paragraph[0].text: mark “color” not known']);
  equal(at([{ type: 'bold' }, { type: 'bold' }]), ['doc[0].paragraph[0].text: bold twice']);
  equal(at([{ type: 'bold', attrs: {} }]), ['doc[0].paragraph[0].text: bold takes no attributes']);
  equal(at([{ type: 'bold', x: 1 }]), ['doc[0].paragraph[0].text: x not known']);
  equal(at(/** @type {any} */ ({ length: 1 })), [
    'doc[0].paragraph[0].text: its marks are not a list',
  ]);
  equal(at([{ type: 'link', attrs: { href: 'javascript:alert(1)' } }]), [
    'doc[0].paragraph[0].text: not an http or https address',
  ]);
  equal(at([{ type: 'link', attrs: { page: '../api' } }]), [
    'doc[0].paragraph[0].text: not a page of MoolaKata',
  ]);
  equal(at([{ type: 'link', attrs: { href: 'https://a.b/', page: 'accounts' } }]), [
    'doc[0].paragraph[0].text: a link goes to an address or a page',
  ]);
  equal(at([{ type: 'link' }]), ['doc[0].paragraph[0].text: a link goes to an address or a page']);
  equal(problems(doc({ type: 'pre', content: [t('x', [{ type: 'bold' }])] })), [
    'doc[0].pre[0].text: no marks here',
  ]);
  equal(problems(doc({ type: 'bullets', marks: [{ type: 'bold' }], content: [li(p(t('x')))] })), [
    'doc[0].bullets: no marks here',
  ]);
});

Deno.test('the limits: characters, lists three deep, the size kept', () => {
  const { chars } = SPEC.limits;
  equal(problems(doc(p(t('a'.repeat(chars))))), []);
  equal(problems(doc(p(t('a'.repeat(chars + 1))))), [
    'At most 20,000 characters (this has 20,001).',
  ]);
  /** @param {number} n @returns {any} */
  const nest = (n) => ({
    type: 'bullets',
    content: [li(p(t('x')), ...(n > 1 ? [nest(n - 1)] : []))],
  });
  equal(problems(doc(nest(3))), []);
  equal(problems(doc(nest(4))), ['Lists go 3 deep at most.']);
  const marked = doc(
    p(...Array.from({ length: 4000 }, () => t('ab', [{ type: 'bold' }, { type: 'italic' }]))),
  );
  equal(problems(marked).includes('Too much formatting for its length.'), true);
});

Deno.test("a content rule's terms, and lists of kinds that follow it or don't", () => {
  const item = terms('paragraph (bullets | numbers)*');
  equal(item.map((x) => [[...x.names], x.min, x.max]), [
    [['paragraph'], 1, 1],
    [['bullets', 'numbers'], 0, Infinity],
  ]);
  equal(terms('block+')[0].names.has('pre'), true);
  equal(terms('text?').map((x) => [x.min, x.max]), [[0, 1]]);
  equal(
    [[], ['paragraph'], ['paragraph', 'numbers', 'bullets'], ['bullets'], [
      'paragraph',
      'paragraph',
    ]]
      .map((s) => follows(s, item)),
    [false, true, true, false, false],
  );
});

Deno.test('a note as plain text, and one with no text', () => {
  const d = doc(
    { type: 'heading', attrs: { level: 2 }, content: [t('Plan')] },
    p(t('one'), { type: 'break' }, t('two', [{ type: 'bold' }])),
    { type: 'bullets', content: [li(p(t('a'))), li(p(t('b')))] },
    { type: 'quote', content: [p(t('q'))] },
    { type: 'pre', content: [t('x  y')] },
  );
  equal(plainText(d), 'Plan\none\ntwo\na\nb\nq\nx  y');
  equal([plainText(null), plainText({ type: 'x' })], ['', '']);
  equal([isEmpty(doc(p())), isEmpty(doc(p(t('  ')))), isEmpty(d), isEmpty(null)], [
    true,
    true,
    false,
    true,
  ]);
});
