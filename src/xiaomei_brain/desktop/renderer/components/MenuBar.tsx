import { useState, useRef, useEffect } from "react";

interface MenuItem {
  label: string;
  action?: () => void;
  separator?: boolean;
}

const menus: Record<string, MenuItem[]> = {
  "编辑(E)": [
    { label: "撤销", action: () => document.execCommand("undo") },
    { label: "重做", action: () => document.execCommand("redo") },
    { separator: true, label: "" },
    { label: "剪切", action: () => document.execCommand("cut") },
    { label: "复制", action: () => document.execCommand("copy") },
    { label: "粘贴", action: () => document.execCommand("paste") },
    { label: "全选", action: () => document.execCommand("selectAll") },
  ],
  "窗口(W)": [
    { label: "重新加载", action: () => location.reload() },
    { label: "开发者工具", action: () => {} },
    { separator: true, label: "" },
    { label: "关闭", action: () => window.win.close() },
  ],
  "帮助(H)": [
    {
      label: "关于 xiaomei-brain",
      action: () =>
        alert("xiaomei-brain Desktop\n版本 1.0.0\nAI Agent 大脑框架"),
    },
  ],
};

export function MenuBar() {
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [maximized, setMaximized] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!window.win) return;
    window.win.isMaximized().then(setMaximized);
    window.win.onMaximizeChange(setMaximized);
  }, []);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div className="menubar" ref={menuRef}>
      <div className="menubar-logo">
        <div className="menubar-logo-icon">小</div>
      </div>

      <div className="menubar-items">
        {Object.keys(menus).map((key) => (
          <div className="menubar-item" key={key}>
            <button
              className={`menubar-item-button ${openMenu === key ? "open" : ""}`}
              onClick={() => setOpenMenu(openMenu === key ? null : key)}
            >
              {key}
            </button>
            {openMenu === key && (
              <div className="menubar-dropdown">
                {menus[key].map((item, i) =>
                  item.separator ? (
                    <div className="menubar-dropdown-separator" key={i} />
                  ) : (
                    <button
                      key={i}
                      className="menubar-dropdown-item"
                      onClick={() => {
                        item.action?.();
                        setOpenMenu(null);
                      }}
                    >
                      {item.label}
                    </button>
                  )
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="menubar-spacer" />

      {window.win && (
        <div className="menubar-window-controls">
          <button
            className="menubar-window-btn"
            onClick={() => window.win.minimize()}
            title="最小化"
          >
            &#x2212;
          </button>
          <button
            className="menubar-window-btn"
            onClick={() => window.win.maximize()}
            title={maximized ? "还原" : "最大化"}
          >
            {maximized ? "\u29C9" : "\u25A1"}
          </button>
          <button
            className="menubar-window-btn menubar-window-btn-close"
            onClick={() => window.win.close()}
            title="关闭"
          >
            &#x2715;
          </button>
        </div>
      )}
    </div>
  );
}
