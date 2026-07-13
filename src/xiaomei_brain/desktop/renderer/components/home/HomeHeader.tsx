import { useTranslation } from "react-i18next";

export type HomeMode = "working" | "coding" | "design";

interface HomeHeaderProps {
  mode: HomeMode;
}

const SUBTITLE_KEYS: Record<HomeMode, string> = {
  working: "home.superpowerWorking",
  coding: "home.superpowerCoding",
  design: "home.superpowerDesign",
};

export function HomeHeader({ mode }: HomeHeaderProps) {
  const { t } = useTranslation();
  return (
    <header className="wb-home-header">
      <h1 className="wb-home-header__title">xiaomei-brain</h1>
      <p className="wb-home-header__subtitle">{t(SUBTITLE_KEYS[mode])}</p>
    </header>
  );
}
