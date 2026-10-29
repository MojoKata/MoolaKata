# Walk-through: review 3's import claims

Started Oct 29, 2026. Decisions log; nothing is applied until the final approval. The claims are
those of unit 01 about reading a file into an account (S1.3, S1.5, S1.11); the unit's other
claims (CR3-17, CR3-169, CR3-173, CR3-343, CR3-344, CR3-360, CR3-374) and the connector's
(CR3-66 to CR3-70) are left for their own pieces of work.

## Items

1. CR3-13 (Med): a deleted transaction comes back with the next import that carries it
2. CR3-15 (Med): one cash dividend ends keeping by snapshots, and the holdings vanish
3. CR3-18 (Med): no account can be set to statement import
4. CR3-345 (Low): every file's positions are saved as holdings snapshots, trades or not
5. CR3-16 (Med): a brokerage statement's lines already present are learned as skips
6. CR3-14 (Med): a trade-history CSV makes its securities class `other`, which no source prices
7. CR3-19 (Med): a trade history's columns can't be mapped, so an exchange's CSV imports as cash
8. CR3-174 (Low): a coin and a listed stock with the same ticker become one instrument
9. CR3-170 (Low): an OFX file's end date and ledger balance move a day in UTC
10. CR3-175 (Low): two OFX rows sharing a FITID take the later one's date
11. CR3-171 (Low): a newest-first CSV of a single day keeps its oldest row's balance
12. CR3-172 (Low): uploads waiting for a mapping or a check are held in memory, uncounted

## Decisions
