import { useState, ReactNode } from "react";
import { Icon } from "../ui";

interface CollapsibleSectionProps {
  title: string;
  count?: number;
  defaultExpanded?: boolean;
  children: ReactNode;
}

export function CollapsibleSection({
  title,
  count,
  defaultExpanded = true,
  children,
}: CollapsibleSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div className="collapsible-section">
      <button
        className="section-header"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="section-header-text">
          {title}
          {count !== undefined && ` (${count})`}
        </span>
        <Icon
          name="chevron-down"
          size={12}
          className={`section-chevron ${!expanded ? "collapsed" : ""}`}
        />
      </button>
      <div className={`section-body ${!expanded ? "collapsed" : ""}`}>
        {children}
      </div>
    </div>
  );
}
