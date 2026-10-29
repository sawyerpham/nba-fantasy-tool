// The outline triangle inside a button.neon-arrow (styles.css): the app's ◀ ▶ step buttons.
export default function NeonArrow({ dir }) {
  return <svg viewBox="0 0 16 20" aria-hidden="true"><polygon points={dir === "left" ? "12,3 3,10 12,17" : "4,3 13,10 4,17"} /></svg>;
}
