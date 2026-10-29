/** The outline-triangle icon for a step button (◀ / ▶). Used inside a button with class `neon-arrow` (styles.css), which supplies the glow. */
export default function NeonArrow({ dir }) {
  return <svg viewBox="0 0 16 20" aria-hidden="true"><polygon points={dir === "left" ? "12,3 3,10 12,17" : "4,3 13,10 4,17"} /></svg>;
}
