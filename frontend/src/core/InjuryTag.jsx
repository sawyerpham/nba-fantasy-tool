// Sleeper's injury tag -> [abbreviation, color class, meaning]: red = won't / likely won't play, yellow = unsure, green = likely plays.
const INJ_TAG = {
  Sus: ["SUS", "out", "suspended"], Suspended: ["SUS", "out", "suspended"], Out: ["OUT", "out", "out"], IR: ["OUT", "out", "out"],
  Doubtful: ["D", "out", "doubtful"], DTD: ["DTD", "", "day-to-day"], GTD: ["GTD", "", "game-time decision"],
  Questionable: ["Q", "", "questionable"], Probable: ["P", "ok", "probable"],
};
/** True for Sleeper injury tags that mean he won't (or likely won't) play: Out, IR, Suspended, Doubtful. */
export const isOut = (tag) => INJ_TAG[tag]?.[1] === "out";
/** Small badge for a player's Sleeper injury tag: abbreviation, colour class, and a hover with the meaning plus Sleeper's note. Renders nothing without a tag. */
export default function InjuryTag({ tag, note }) {
  if (!tag) return null;
  const [abbr, cls, meaning] = INJ_TAG[tag] || [tag, "", tag];
  const say = abbr.toLowerCase() === meaning ? "" : `${meaning[0].toUpperCase()}${meaning.slice(1)}`;
  return <span className={`inj ${cls}`} data-tip={[say, note].filter(Boolean).join(" · ") || undefined}>{abbr}</span>;
}
