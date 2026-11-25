# Pause a Link

## Pause for {#pause-for}

How long to pause: a duration such as `4h`, `1d` or `2w 3d`, whole numbers of weeks (`w`), days
(`d`), hours (`h`) and minutes (`m`), largest first, at most 52 weeks (`52w`): a longer stop is
what **End Link** is for. **default** fills in a day and **max** 52 weeks; a blank is
refused. While it is paused no data or receipts cross, either way; the two servers still exchange
their removals and narrowings, so a share taken back, a person taken off a share (who then no
longer sees it), or the link ended, still takes effect. The other server is told it is paused,
so it doesn't report this one as unreachable. The link resumes on its own when the time is up;
**Resume Now** on the link ends it sooner.
