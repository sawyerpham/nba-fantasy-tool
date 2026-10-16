// Sleeper's injury tag -> [abbreviation, color class, meaning]: red = won't / likely won't play, yellow = unsure, green = likely plays.
const INJ_TAG = {
  Sus: ["SUS", "out", "suspended"], Suspended: ["SUS", "out", "suspended"], Out: ["O", "out", "out"], IR: ["O", "out", "out"],
  Doubtful: ["D", "out", "doubtful"], DTD: ["DTD", "", "day-to-day"], GTD: ["GTD", "", "game-time decision"],
  Questionable: ["Q", "", "questionable"], Probable: ["P", "ok", "probable"],
};
export default function InjuryTag({ tag, note }) {
  if (!tag) return null;
  const [abbr, cls, meaning] = INJ_TAG[tag] || [tag, "", tag];
  return <span className={`inj ${cls}`} data-tip={`${meaning[0].toUpperCase()}${meaning.slice(1)}${note ? ` · ${note}` : ""}`}>{abbr}</span>;
}
