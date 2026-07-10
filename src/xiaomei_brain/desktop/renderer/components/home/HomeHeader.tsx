export type HomeMode = "working" | "coding" | "design";

const SUBTITLES: Record<HomeMode, string> = {
  working: "你的职场超能力",
  coding: "你的开发超能力",
  design: "你的设计超能力",
};

interface HomeHeaderProps {
  mode: HomeMode;
}

export function HomeHeader({ mode }: HomeHeaderProps) {
  return (
    <header className="wb-home-header">
      <h1 className="wb-home-header__title">xiaomei-brain</h1>
      <p className="wb-home-header__subtitle">{SUBTITLES[mode]}</p>
    </header>
  );
}
