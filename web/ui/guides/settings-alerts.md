# Alerts

How alerts behave for everyone. Each user chooses in Profile whether alerts reach them by email.

![Settings: Alerts](shots/settings-alerts.png)

## Alert when a source has failed for {#alert-source}

How long a price source, or email, may keep failing before admins are alerted. A source that fails
now and then and recovers raises nothing; one that keeps failing raises one alert, which resolves by
itself when it works again. A duration such as `12h`, `2d` or `1w 3d`, largest unit first: `1h`
to `2w`, `2d` by default. **min**, **default** and **max** under the field fill those in; a
blank, or one outside the range, is refused at Save.

## Daily summary at {#alert-summary-time}

When the daily summary email goes to those who chose it, in each person's own time zone. It lists
the alerts opened since the last one, and none is sent on a day without any. Type the time as
`7am`, `7:30 pm` or `19:30`, or press ↓ for the times every 15 minutes.
