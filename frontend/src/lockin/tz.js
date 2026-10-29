// The league's time zone (Settings > General; the Season page sets it from the week data). Every in-season time
// is shown in it, labelled with its own abbreviation (CDT, PST, ...).
let zone = "America/Chicago";
/** Set the league's time zone (ignored when falsy). */
export const setZone = (z) => { if (z) zone = z; };
/** Format a timestamp in the league's time zone with `toLocaleString` options. */
export const fmt = (ms, opts) => new Date(ms).toLocaleString("en-US", { timeZone: zone, ...opts });
/** A timestamp's clock time ("7:30 PM") in the league's zone; "" for no timestamp. */
export const timeOf = (iso) => (iso ? fmt(iso, { hour: "numeric", minute: "2-digit" }) : "");
/** The league zone's short abbreviation (CDT, PST, ...) at the given time (default: now). */
export const tzAbbr = (ms = Date.now()) =>
  new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "short" }).formatToParts(ms).find((p) => p.type === "timeZoneName")?.value || "";
