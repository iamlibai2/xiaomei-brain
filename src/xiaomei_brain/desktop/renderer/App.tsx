import { useEffect } from "react";
import { useCoreStore, initGatewayEvents } from "./store";
import { ConnectPage } from "./components/ConnectPage";
import { MenuBar } from "./components/MenuBar";
import { MainShell } from "./components/MainShell";

export function App() {
  const page = useCoreStore((s) => s.page);

  useEffect(() => {
    initGatewayEvents();
  }, []);

  return (
    <div className="app">
      <MenuBar />
      {page === "connect" ? (
        <ConnectPage />
      ) : (
        <MainShell />
      )}
    </div>
  );
}
