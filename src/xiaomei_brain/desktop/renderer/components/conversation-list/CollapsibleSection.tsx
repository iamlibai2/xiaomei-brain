import { useState, ReactNode } from "react";

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
        <span className={`section-chevron ${!expanded ? "collapsed" : ""}`}>
          ▾
        </span>
      </button>
      <div className={`section-body ${!expanded ? "collapsed" : ""}`}>
        {children}
      </div>
    </div>
  );
}
