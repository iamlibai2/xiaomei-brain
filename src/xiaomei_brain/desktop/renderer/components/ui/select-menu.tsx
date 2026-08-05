import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "./icon";

export interface SelectMenuOption {
  value: string;
  label: string;
  description?: string;
}

export function SelectMenu({
  value,
  options,
  placeholder,
  searchable = false,
  disabled = false,
  placement = "down",
  className = "",
  searchPlaceholder,
  emptyText,
  onChange,
  onOptionHover,
}: {
  value: string;
  options: SelectMenuOption[];
  placeholder: string;
  searchable?: boolean;
  disabled?: boolean;
  placement?: "up" | "down";
  className?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  onChange: (value: string) => void;
  onOptionHover?: (value: string) => void;
}) {
  const { t } = useTranslation();
  const resolvedSearchPlaceholder = searchPlaceholder || t("searchUi.title");
  const resolvedEmptyText = emptyText || t("searchUi.empty");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const selected = options.find((option) => option.value === value);
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = normalizedQuery
    ? options.filter((option) => (
      option.label.toLowerCase().includes(normalizedQuery)
      || option.value.toLowerCase().includes(normalizedQuery)
    ))
    : options;

  useEffect(() => {
    const handleOutside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  return (
    <div
      className={`model-dropdown is-${placement} ${open ? "is-open" : ""} ${className}`.trim()}
      ref={rootRef}
    >
      <button
        type="button"
        className="model-dropdown-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <span className={selected ? "" : "placeholder"}>{selected?.label || placeholder}</span>
        <Icon name="chevron-down" size={15} />
      </button>
      {open && (
        <div className="model-dropdown-menu">
          {searchable && (
            <div className="model-dropdown-search">
              <Icon name="search" size={14} />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={resolvedSearchPlaceholder}
              />
            </div>
          )}
          <div className="model-dropdown-options" role="listbox">
            {filtered.map((option) => (
              <button
                type="button"
                role="option"
                aria-selected={option.value === value}
                className={option.value === value ? "selected" : ""}
                key={option.value}
                onMouseEnter={() => onOptionHover?.(option.value)}
                onClick={(event) => {
                  // SelectMenu is sometimes placed inside a form label. Stop
                  // the label's default activation from clicking the trigger
                  // again immediately after this menu closes.
                  event.preventDefault();
                  event.stopPropagation();
                  setOpen(false);
                  onChange(option.value);
                }}
              >
                <span>{option.label}</span>
                {option.description && <small>{option.description}</small>}
              </button>
            ))}
            {filtered.length === 0 && <p>{resolvedEmptyText}</p>}
          </div>
        </div>
      )}
    </div>
  );
}
