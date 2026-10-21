// Sleeper's injury tag -> [abbreviation, color class, meaning]: red = won't / likely won't play, yellow = unsure, green = likely plays.
const INJ_TAG = {
  Sus: ["SUS", "out", "suspended"], Suspended: ["SUS", "out", "suspended"], Out: ["OUT", "out", "out"], IR: ["OUT", "out", "out"],
  Doubtful: ["D", "out", "doubtful"], DTD: ["DTD", "", "day-to-day"], GTD: ["GTD", "", "game-time decision"],
  Questionable: ["Q", "", "questionable"], Probable: ["P", "ok", "probable"],
};
export default function InjuryTag({ tag, note }) {
  if (!tag) return null;
  const [abbr, cls, meaning] = INJ_TAG[tag] || [tag, "", tag];
  // the hover spells out the tag only when the tag is an abbreviation (OUT already says it), then Sleeper's note
  const say = abbr.toLowerCase() === meaning ? "" : `${meaning[0].toUpperCase()}${meaning.slice(1)}`;
  return <span className={`inj ${cls}`} data-tip={[say, note].filter(Boolean).join(" · ") || undefined}>{abbr}</span>;
}
