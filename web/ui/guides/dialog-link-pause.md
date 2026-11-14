# Pause a Link

## Pause for {#pause-for}

How long to pause: a duration such as `4h`, `1d` or `2w 3d`, whole numbers of weeks (`w`), days
(`d`), hours (`h`) and minutes (`m`), largest first. **default** fills in a day; a blank is
refused. While it is paused this server
neither pulls from the other one nor answers it, and the other server is told it is paused, so it
doesn't report this one as unreachable. The link resumes on its own when the time is up;
**Resume Now** on the link ends it sooner.
