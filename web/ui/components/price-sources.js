// A price source as a draft adds, changes or removes it (requirements S4.2): Settings › Prices,
// and the welcome's step that turns on the sources needing no key (S12.14.1).
import { Record } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';

export class SrcRec extends Record {
  /** @override */
  static prefix = 'Src';
  /** @override */
  static fields = FIELDS.SourceRecord;
}
