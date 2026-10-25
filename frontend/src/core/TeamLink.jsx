import React, { createContext, useContext } from "react";

// An NBA team's name or abbreviation that opens its Team card. The Season tab provides openTeam(abbr) through the
// context; anywhere else (the Draft tab's profiles) the name stays plain text.
export const TeamLinkContext = createContext(null);

export default function TeamLink({ abbr, children }) {
  const open = useContext(TeamLinkContext);
  const text = children ?? abbr;
  if (!open || !abbr) return <>{text}</>;
  return (
    <span className="team-link" role="link" tabIndex={0} title={`Open ${abbr}'s team card`} data-testid={`team-link-${abbr}`}
      onClick={(e) => { e.stopPropagation(); open(abbr); }} onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); open(abbr); } }}>
      {text}
    </span>
  );
}
