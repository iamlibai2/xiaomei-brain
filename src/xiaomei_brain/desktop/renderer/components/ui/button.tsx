import React from "react";
import { Icon, type IconName } from "./icon";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "chip" | "text";
type ButtonSize = "xs" | "sm" | "md" | "lg" | "icon-sm" | "icon-md" | "icon-lg";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: IconName;
  iconSize?: number;
  pill?: boolean;
  children?: React.ReactNode;
}

// ── Variant → CSS class ──

const variantClass: Record<ButtonVariant, string> = {
  primary: "ui-btn-primary",
  secondary: "ui-btn-secondary",
  ghost: "ui-btn-ghost",
  danger: "ui-btn-danger",
  chip: "ui-btn-chip",
  text: "ui-btn-text",
};

const sizeClass: Record<ButtonSize, string> = {
  xs: "ui-btn-xs",
  sm: "ui-btn-sm",
  md: "ui-btn-md",
  lg: "ui-btn-lg",
  "icon-sm": "ui-btn-icon-sm",
  "icon-md": "ui-btn-icon-md",
  "icon-lg": "ui-btn-icon-lg",
};

export function Button({
  variant = "ghost",
  size = "md",
  icon,
  iconSize,
  pill,
  className,
  children,
  ...props
}: ButtonProps) {
  const cls = [
    "ui-btn",
    variantClass[variant],
    sizeClass[size],
    pill ? "ui-btn-pill" : "",
    className || "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button className={cls} {...props}>
      {icon && <Icon name={icon} size={iconSize ?? (size.startsWith("icon") ? 16 : 14)} />}
      {children}
    </button>
  );
}
