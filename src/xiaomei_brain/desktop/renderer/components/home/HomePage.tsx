import { useState } from "react";
import { useGateway } from "../../hooks/useGateway";
import { HomeHeader } from "./HomeHeader";
import { SceneTabs, HomeMode } from "./SceneTabs";
import { GrowthBuddy } from "./GrowthBuddy";
import { HomeComposer } from "./HomeComposer";

interface HomePageProps {
  gateway: ReturnType<typeof useGateway>;
}

export function HomePage({ gateway }: HomePageProps) {
  const [mode, setMode] = useState<HomeMode>("working");

  return (
    <div className="main-content">
      <div className="activity-banner">
        <button className="activity-banner-button">
          📈 做任务赢积分好礼 &gt;
        </button>
      </div>
      <div className="wb-home-page">
        <HomeHeader mode={mode} />
        <SceneTabs selected={mode} onSelect={setMode} />
        <GrowthBuddy />
        <HomeComposer gateway={gateway} />
      </div>
    </div>
  );
}
