import React from "react";

// One colour per position everywhere on the site (colours live in styles.css: .pos-PG ... .pos-C).
const POS_RE = /PG|SG|SF|PF|C/;
export const posClass = (text) => {
  const m = String(text || "").match(POS_RE);
  return m ? `pos-c pos-${m[0]}` : "";
};

// "PG/SF/PF" with each position in its colour.
export function PosList({ list, sep = "/" }) {
  return (list || []).map((p, i) => (
    <React.Fragment key={p}>{i > 0 && sep}<span className={posClass(p)}>{p}</span></React.Fragment>
  ));
}

// Any short label that names a position ("#2 SG", "PG1", "SF×2") in that position's colour.
export function PosTag({ text, className = "" }) {
  return <span className={`${posClass(text)} ${className}`}>{text}</span>;
}
