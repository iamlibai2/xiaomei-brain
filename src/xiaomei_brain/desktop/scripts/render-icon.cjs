const { app, BrowserWindow } = require("electron");
const { writeFile } = require("node:fs/promises");
const path = require("node:path");

app.commandLine.appendSwitch("force-device-scale-factor", "1");

app.whenReady().then(async () => {
  const source = path.join(__dirname, "..", "assets", "icon.svg");
  const destination = path.join(__dirname, "..", "assets", "icon.png");
  const window = new BrowserWindow({
    width: 512,
    height: 512,
    show: false,
    frame: false,
    transparent: true,
    webPreferences: { offscreen: true },
  });

  await window.loadFile(source);
  const image = await window.webContents.capturePage({ x: 0, y: 0, width: 512, height: 512 });
  await writeFile(destination, image.toPNG());
  window.destroy();
  app.quit();
});
