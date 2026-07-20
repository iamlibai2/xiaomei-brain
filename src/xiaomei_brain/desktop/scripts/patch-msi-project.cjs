const { readFile, writeFile } = require("node:fs/promises");

module.exports = async function patchMsiProject(projectPath) {
  const source = await readFile(projectPath, "utf8");
  const property = '<Property Id="DISABLEADVTSHORTCUTS" Value="1"/>';
  const occurrences = source.split(property).length - 1;
  if (occurrences !== 1) {
    throw new Error(`Expected one DISABLEADVTSHORTCUTS property, found ${occurrences}`);
  }

  const patched = source.replace(
    property,
    "<!-- Keep advertised shortcuts so Windows Installer resolves the registered executable component. -->",
  );
  await writeFile(projectPath, patched, "utf8");
};
