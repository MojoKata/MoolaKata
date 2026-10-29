# Schema review

What a later review of the database's schema (`docs/schema.md`) is to look at. Each entry
says what the table or field is today and the question it raises. Every table has a synthetic
id (§2) except a pure relation: a many-to-many table of two keys and nothing of its own.

1. **`TaskRun`**: each background job's last run (`startedAt`, `finishedAt`, `error`), keyed by
   the job's name as the code registers it (`backups`, `pruning`, `mail`, …). It carries
   values of its own, so it falls under the id rule; it was left as it is because the code
   finds a job's row by its name. Give it an id, the name a unique column?
2. **An organisation's causes** (`Organisation.causes`): a JSON list of words describing a
   charity ("education, health"), used like tags on the giving screens (S7.9). Should causes be
   records of their own, shared across organisations, as tags are records (`Tag`)?
3. **Tags shared in a household**: a `Tag` is its owner's, as S2.6 says (the user's own). A
   household would rather share one set of tags ("vacation", "tax-deductible"), each person
   still tagging only for themselves, or tagging for everyone. Who owns a shared tag, who may
   rename it, and what a receiver of a shared account sees.
