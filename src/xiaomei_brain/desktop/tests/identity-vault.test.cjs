const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { IdentityVault } = require("../dist/main/identity-vault.js");

test("IdentityVault manages multiple encrypted Desktop accounts", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "xiaomei-identities-"));
  try {
    const vault = new IdentityVault(root);
    assert.equal(vault.status().exists, false);

    const first = vault.create("Alice", "alice-password");
    const aliceSubject = first.subject;
    assert.equal(first.accounts.length, 1);
    assert.equal(first.unlocked, true);

    const second = vault.create("Bob", "bob-password");
    const bobSubject = second.subject;
    assert.equal(second.accounts.length, 2);
    assert.equal(second.activeSubject, bobSubject);

    const selected = vault.select(aliceSubject);
    assert.equal(selected.unlocked, false);
    assert.equal(selected.activeSubject, aliceSubject);
    assert.equal(vault.unlock("alice-password", aliceSubject).displayName, "Alice");
    vault.changePassword("bob-password", "bob-password-new", bobSubject);
    assert.equal(vault.status().activeSubject, aliceSubject);
    assert.equal(vault.status().unlocked, true);

    const exported = path.join(root, "alice-backup.json");
    vault.exportBackup(exported, aliceSubject);
    assert.equal(fs.existsSync(exported), true);

    const afterRemoval = vault.remove(bobSubject, "bob-password-new");
    assert.equal(afterRemoval.accounts.length, 1);
    assert.equal(afterRemoval.accounts[0].displayName, "Alice");
    assert.equal(afterRemoval.activeSubject, aliceSubject);
    assert.equal(afterRemoval.unlocked, true);

    const third = vault.create("Charlie", "charlie-password");
    assert.throws(
      () => vault.remove(third.subject, "wrong-password"),
      /密码不正确/,
    );
    const afterActiveRemoval = vault.remove(third.subject, "charlie-password");
    assert.equal(afterActiveRemoval.accounts.length, 1);
    assert.equal(afterActiveRemoval.activeSubject, aliceSubject);
    assert.equal(afterActiveRemoval.unlocked, false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("IdentityVault migrates the former single-vault file", () => {
  const sourceRoot = fs.mkdtempSync(path.join(os.tmpdir(), "xiaomei-identity-source-"));
  const migrationRoot = fs.mkdtempSync(path.join(os.tmpdir(), "xiaomei-identity-migrate-"));
  try {
    const source = new IdentityVault(sourceRoot);
    source.create("Legacy", "legacy-password");
    source.exportBackup(path.join(migrationRoot, "identity-vault.json"));

    const migrated = new IdentityVault(migrationRoot);
    const status = migrated.status();
    assert.equal(status.accounts.length, 1);
    assert.equal(status.displayName, "Legacy");
    assert.equal(fs.existsSync(path.join(migrationRoot, "identity-vault.json")), false);
    assert.equal(migrated.unlock("legacy-password").unlocked, true);
  } finally {
    fs.rmSync(sourceRoot, { recursive: true, force: true });
    fs.rmSync(migrationRoot, { recursive: true, force: true });
  }
});
