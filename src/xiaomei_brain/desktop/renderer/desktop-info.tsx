import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { DesktopInfo } from "./types";

const DesktopInfoContext = createContext<DesktopInfo | null>(null);

export function DesktopInfoProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<DesktopInfo | null>(null);

  useEffect(() => {
    void window.desktop.getInfo().then(setInfo).catch((error) => {
      console.error("Failed to load Desktop information", error);
    });
  }, []);

  return (
    <DesktopInfoContext.Provider value={info}>
      {children}
    </DesktopInfoContext.Provider>
  );
}

export function useDesktopInfo(): DesktopInfo | null {
  return useContext(DesktopInfoContext);
}
