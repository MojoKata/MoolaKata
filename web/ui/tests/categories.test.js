/// <reference lib="deno.ns" />
// The category lists (S12.2.6) and what a merge may take (S7.2.4), from the list alone.
import { categoryOptions, defaultMapping, mergeTargets, NEW } from '../app/categories.js';
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
