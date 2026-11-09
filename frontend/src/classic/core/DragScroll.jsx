import React, { useLayoutEffect, useRef, useState } from "react";

/** A scrollable box you can also grab and drag (left / right, or up / down with `vertical`); a drag doesn't count as a click on what's under it. */
export default function DragScroll({ className, vertical = false, style, children, ...rest }) {
  const ref = useRef(null), drag = useRef(null);
  const [on, setOn] = useState(false);
  // vertical: grow down to the bottom of the window (re-fit on resize and when the content changes)
  useLayoutEffect(() => {
    if (!vertical) return undefined;
    /** Size the box so its bottom edge meets the bottom of the window (at least 160px tall). */
    const fit = () => { const el = ref.current; if (el) el.style.maxHeight = `${Math.max(160, window.innerHeight - el.getBoundingClientRect().top - 24)}px`; };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  });
  const pos = (e) => (vertical ? e.clientY : e.clientX), prop = vertical ? "scrollTop" : "scrollLeft";
  const down = (e) => { if (e.button === 0) drag.current = { x: pos(e), left: ref.current[prop], moved: false }; };
  const move = (e) => {
    const d = drag.current;
    if (!d) return;
    if (!d.moved && Math.abs(pos(e) - d.x) > 4) { d.moved = true; setOn(true); ref.current.setPointerCapture(e.pointerId); }
    if (d.moved) ref.current[prop] = d.left - (pos(e) - d.x);
  };
  const up = () => { setOn(false); if (drag.current && !drag.current.moved) drag.current = null; };
  // the click that ends a drag lands here first: swallow it so the row under the pointer doesn't open
  const click = (e) => { if (drag.current?.moved) { e.stopPropagation(); e.preventDefault(); } drag.current = null; };
  return <div ref={ref} style={style} {...rest} className={`${className} drag-scroll ${vertical ? "vertical" : ""} ${on ? "dragging" : ""}`} onPointerDown={down} onPointerMove={move}
    onPointerUp={up} onPointerCancel={() => { setOn(false); drag.current = null; }} onClickCapture={click}>{children}</div>;
}
