// What a corporate action may be recorded on (requirements S2.4), from the positions held on
// its day alone.

/**
 * The holdings an action may be recorded on: each stock held, long or short (S2.4.6), and
 * for a split, a stock only whose options are held, the split reaching them (S3.10.1).
 * @param {any[]} open the positions held on the action's day
 * @param {string | undefined} accountId one account's alone
 * @param {string} kind
 */
export function holdings(open, accountId, kind) {
  const mine = open.filter((p) => !accountId || p.accountId === accountId);
  const stocks = mine.filter((p) => p.instrumentClass !== 'option');
  const have = new Set(stocks.map((p) => p.accountId + p.instrumentId));
  const through = kind !== 'split'
    ? []
    : mine.filter((p) =>
      p.instrumentClass === 'option' && p.underlyingId &&
      !have.has(p.accountId + p.underlyingId)
    ).map((p) => ({
      accountId: p.accountId,
      accountName: p.accountName,
      instrumentId: p.underlyingId,
      symbol: p.underlyingSymbol,
      optionsOnly: true,
    }));
  const seen = new Set();
  return [...stocks, ...through].filter((p) => {
    const k = p.accountId + p.instrumentId;
    return seen.has(k) ? false : (seen.add(k), true);
  });
}
