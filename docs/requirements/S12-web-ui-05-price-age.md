# S12.5. A price's age

5. **Every value derived from a price** shows its age on hover, and the header shows the last
   price refresh with a dot that turns amber when prices are stale, on every screen but
   Profile, whose header holds Sign Out instead (S12.2.16). Prices are stale when a holding in
   an account the person can see has no price at all, or is valued by a stale one: each
   holding is judged by the price that values it for its account's owner (S4.10), by that
   price's own rule: a close by S4.7, a statement's value by S4.3, a typed price once over 90
   days old, and an option at intrinsic value by its underlying's price (S3.7). With no
   source that fetches enabled, the header reads *No Price Source* instead (S4.2.3).
