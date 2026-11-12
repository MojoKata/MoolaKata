/// <reference lib="deno.ns" />
// The category lists (S12.2.6) and what a merge may take (S7.2.4), from the list alone.
import {
  categoryOptions,
  defaultMapping,
  mergeTargets,
  monthName,
  NEW,
  useCounts,
  useSteps,
  usesWords,
} from '../app/categories.js';
import { equal } from './assert.js';

/** @param {string} id @param {string} name @param {string} [kind] @param {string | null} [parentId] @param {string} [path] */
const c = (id, name, kind = 'expense', parentId = null, path = name) => ({
  id,
  name,
  kind,
  parentId,
  path,
});
const pet = c('pet', 'Pet');
const dog = c('dog', 'dog', 'expense', 'pet', 'Pet › dog');
const toy = c('toy', 'Toy', 'savings', 'pet', 'Pet › Toy');
const pets = c('pets', 'Pets');
const dogs = c('dogs', 'Dogs', 'expense', 'pets', 'Pets › Dogs');
const dogLower = c('dog2', 'DOG', 'expense', 'pets', 'Pets › DOG');
const vet = c('vet', 'Vet', 'expense', 'pets', 'Pets › Vet');
const wage = c('wage', 'Wage', 'income');
const lonely = c('lonely', 'Lonely');
const list = [pet, dog, toy, pets, dogs, dogLower, vet, wage, lonely];

Deno.test('a list starts with its none, ends with New category…', () => {
  equal(categoryOptions([pet, dog]), [['', 'Uncategorised'], ['pet', 'Pet'], ['dog', 'Pet › dog'], [
    NEW,
    'New category…',
  ]]);
  equal(categoryOptions([], ['', 'Leave it as it is']), [['', 'Leave it as it is'], [
    NEW,
    'New category…',
  ]]);
  equal(categoryOptions([pet], null), [['pet', 'Pet'], [NEW, 'New category…']]);
});

Deno.test('a merge takes another of its kind, a parent with children only another parent', () => {
  // Pet has children: top-level expense categories other than itself.
  equal(mergeTargets(pet, list).map((x) => x.id), ['pets', 'lonely']);
  // A childless one: any expense category, children too, never itself.
  equal(mergeTargets(lonely, list).map((x) => x.id), ['pet', 'dog', 'pets', 'dogs', 'dog2', 'vet']);
  // A child may go into its own parent, never itself; another kind never.
  equal(mergeTargets(dog, list).map((x) => x.id), ['pet', 'pets', 'dogs', 'dog2', 'vet', 'lonely']);
  equal(mergeTargets(wage, list).map((x) => x.id), []);
  equal(mergeTargets(toy, list).map((x) => x.id), []);
});

Deno.test('each child starts on a namesake of the target, any case, else on itself', () => {
  equal(defaultMapping([dog, toy], [dogs, dogLower, vet]), { dog: 'dog2', toy: 'toy' });
  equal(defaultMapping([dog], []), { dog: 'dog' });
  equal(defaultMapping([], [dogs]), {});
});

Deno.test('uses are counted in words, seen and unseen', () => {
  equal(
    [[1, 0], [2, 0], [0, 1], [0, 3], [1, 1], [47, 22]].map(([a, b]) => usesWords(a, b)),
    [
      '1 use you can see',
      '2 uses you can see',
      "1 use you can't see",
      "3 uses you can't see",
      "1 use you can see, and 1 you can't",
      "47 uses you can see, and 22 you can't",
    ],
  );
});

/** A category's uses as the route gives them. @param {Partial<any>} o */
const uses = (o = {}) => ({
  seen: 0,
  unseen: 0,
  transactions: 0,
  rules: [],
  planLines: [],
  moves: [],
  loans: [],
  categories: [],
  ...o,
});
const every = uses({
  seen: 9,
  unseen: 2,
  transactions: 1,
  rules: [{ id: 'r1', payeeMatch: 'petsmart', position: 0 }, {
    id: 'r2',
    payeeMatch: 're:^CHEWY',
    position: 1,
  }],
  planLines: [{ budgetId: 'b1', budgetName: 'Household', month: '2026-01-01' }],
  moves: [
    { budgetId: 'b1', budgetName: 'Household', month: '2026-03-01' },
    { budgetId: 'b1', budgetName: 'Household', month: '2026-03-01' },
    { budgetId: 'b1', budgetName: 'Household', month: '2026-06-01' },
    { budgetId: 'b2', budgetName: 'Scenario', month: '2026-04-01' },
  ],
  loans: [{ accountId: 'a1', name: 'Car loan' }],
  categories: [{ id: 'c1', name: 'Vet' }],
});

Deno.test('the counts of each kind of use', () => {
  equal(useCounts(every), {
    transactions: 1,
    rules: 2,
    planLines: 1,
    moves: 4,
    loans: 1,
    categories: 1,
    seen: 9,
  });
  equal(monthName('2026-03-01'), 'Mar 2026');
});

Deno.test('each kind of use is a step, linked to where it is', () => {
  const steps = useSteps(every, useCounts(every), 'cat');
  equal(steps.map((s) => [s.kind, s.count, s.done]), [
    ['transactions', 1, false],
    ['rules', 2, false],
    ['planLines', 1, false],
    ['moves', 4, false],
    ['loans', 1, false],
    ['categories', 1, false],
  ]);
  equal(steps.map((s) => s.items), [
    [{ label: '1 transaction filed under it', href: '/ui/transactions?category=cat' }],
    [
      { label: '“petsmart”', href: '/ui/transactions/rules/r1' },
      { label: 're:^CHEWY', href: '/ui/transactions/rules/r2' },
    ],
    [{ label: 'Household, from Jan 2026', href: '/ui/budgets/b1/month?month=2026-01' }],
    [
      {
        label: 'Household: ',
        links: [
          { label: 'Mar 2026', href: '/ui/budgets/b1/month?month=2026-03' },
          { label: 'Jun 2026', href: '/ui/budgets/b1/month?month=2026-06' },
        ],
      },
      {
        label: 'Scenario: ',
        links: [{ label: 'Apr 2026', href: '/ui/budgets/b2/month?month=2026-04' }],
      },
    ],
    [{ label: 'Car loan', href: '/ui/accounts/a1/settings' }],
    [{ label: 'Vet', href: '/ui/budgets/none/categories' }],
  ]);
  const two = uses({ seen: 2, transactions: 2 });
  equal(useSteps(two, useCounts(two), 'cat')[0].items[0].label, '2 transactions filed under it');
});

Deno.test('a kind cleared since the tour started stays, done; one never there is no step', () => {
  const start = useCounts(every);
  const now = uses({ seen: 1, transactions: 1 });
  const steps = useSteps(now, start, 'cat');
  equal(steps.map((s) => [s.kind, s.count, s.done, s.items.length]), [
    ['transactions', 1, false, 1],
    ['rules', 0, true, 0],
    ['planLines', 0, true, 0],
    ['moves', 0, true, 0],
    ['loans', 0, true, 0],
    ['categories', 0, true, 0],
  ]);
  // A kind that appears after the start is a step too; one never there isn't.
  const later = uses({ seen: 1, loans: [{ accountId: 'a', name: 'Loan' }] });
  equal(useSteps(later, useCounts(uses({ seen: 1, transactions: 1 })), 'cat').map((s) => s.kind), [
    'transactions',
    'loans',
  ]);
});
