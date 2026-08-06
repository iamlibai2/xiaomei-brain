import {
  KeyObject,
  createCipheriv,
  createDecipheriv,
  createHash,
  createPrivateKey,
  generateKeyPairSync,
  randomBytes,
  scryptSync,
  sign,
} from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { app } from "electron";

interface VaultFile {
  version: 1;
  displayName: string;
  publicKey: string;
  issuer: string;
  subject: string;
  encryptedPrivateKey: string;
  salt: string;
  iv: string;
  authTag: string;
}

interface VaultIndex {
  version: 1;
  activeSubject: string;
}

export interface IdentityAccountSummary {
  displayName: string;
  issuer: string;
  subject: string;
  active: boolean;
  unlocked: boolean;
}

export interface IdentityVaultStatus {
  exists: boolean;
  unlocked: boolean;
  displayName?: string;
  issuer?: string;
  subject?: string;
  activeSubject?: string;
  accounts: IdentityAccountSummary[];
}

export interface UnlockedIdentity {
  displayName: string;
  publicKey: string;
  issuer: string;
  subject: string;
}

/**
 * Stores multiple Desktop identity keys encrypted at rest.
 *
 * Each identity is an independent credential. Only one identity can be active
 * and unlocked at a time, so every Gateway connection observes one consistent
 * person. The renderer can request challenge signatures but never reads a
 * private key.
 */
export class IdentityVault {
  private readonly legacyFilePath: string;
  private readonly vaultDirectory: string;
  private readonly indexPath: string;
  private privateKey: KeyObject | null = null;
  private unlockedIdentity: UnlockedIdentity | null = null;

  constructor(userDataPath?: string) {
    const userData = userDataPath || app.getPath("userData");
    this.legacyFilePath = path.join(userData, "identity-vault.json");
    this.vaultDirectory = path.join(userData, "identity-vaults");
    this.indexPath = path.join(this.vaultDirectory, "index.json");
    this.ensureStorage();
  }

  status(): IdentityVaultStatus {
    const accounts = this.readAccounts();
    if (accounts.length === 0) {
      return { exists: false, unlocked: false, activeSubject: "", accounts: [] };
    }
    const activeSubject = this.resolveActiveSubject(accounts);
    const active = accounts.find((file) => file.subject === activeSubject) || accounts[0];
    return {
      exists: true,
      unlocked: this.privateKey !== null && this.unlockedIdentity?.subject === active.subject,
      displayName: active.displayName,
      issuer: active.issuer,
      subject: active.subject,
      activeSubject: active.subject,
      accounts: accounts.map((file) => ({
        displayName: file.displayName,
        issuer: file.issuer,
        subject: file.subject,
        active: file.subject === active.subject,
        unlocked: this.privateKey !== null && this.unlockedIdentity?.subject === file.subject,
      })),
    };
  }

  create(displayName: string, password: string): IdentityVaultStatus {
    const name = displayName.trim();
    if (!name) throw new Error("名字不能为空");
    this.validatePassword(password);

    const { publicKey, privateKey } = generateKeyPairSync("ed25519");
    const publicJwk = publicKey.export({ format: "jwk" });
    if (!publicJwk.x) throw new Error("无法导出身份公钥");
    const rawPublicKey = Buffer.from(publicJwk.x, "base64url");
    const publicKeyBase64 = rawPublicKey.toString("base64");
    const subject = createHash("sha256").update(rawPublicKey).digest("hex");
    const issuer = `self:key:${subject}`;
    const privateKeyDer = privateKey.export({ format: "der", type: "pkcs8" });
    const encrypted = this.encryptPrivateKey(Buffer.from(privateKeyDer), password);

    const file: VaultFile = {
      version: 1,
      displayName: name,
      publicKey: publicKeyBase64,
      issuer,
      subject,
      ...encrypted,
    };
    this.writeVault(file, false);
    this.setActiveSubject(subject);
    this.privateKey = privateKey;
    this.unlockedIdentity = this.publicIdentity(file);
    return this.status();
  }

  unlock(password: string, subject = ""): IdentityVaultStatus {
    const file = this.requireAccount(subject || this.readIndex().activeSubject);
    try {
      const keyDer = this.decryptPrivateKey(file, password);
      const privateKey = createPrivateKey({ key: keyDer, format: "der", type: "pkcs8" });
      this.assertKeyMatches(file, privateKey);
      this.privateKey = privateKey;
      this.unlockedIdentity = this.publicIdentity(file);
      this.setActiveSubject(file.subject);
    } catch {
      this.privateKey = null;
      this.unlockedIdentity = null;
      throw new Error("密码不正确或身份文件已损坏");
    }
    return this.status();
  }

  /** Verify the active account password without changing the unlocked vault. */
  verifyPassword(password: string, subject = ""): boolean {
    const file = this.requireAccount(subject || this.requireActiveFile().subject);
    try {
      const keyDer = this.decryptPrivateKey(file, password);
      const privateKey = createPrivateKey({ key: keyDer, format: "der", type: "pkcs8" });
      this.assertKeyMatches(file, privateKey);
      return true;
    } catch {
      return false;
    }
  }

  select(subject: string): IdentityVaultStatus {
    const file = this.requireAccount(subject);
    this.privateKey = null;
    this.unlockedIdentity = null;
    this.setActiveSubject(file.subject);
    return this.status();
  }

  lock(): IdentityVaultStatus {
    this.privateKey = null;
    this.unlockedIdentity = null;
    return this.status();
  }

  changePassword(
    currentPassword: string,
    newPassword: string,
    subject = "",
  ): IdentityVaultStatus {
    this.validatePassword(newPassword);
    const file = this.requireAccount(subject || this.requireActiveFile().subject);
    const privateKeyDer = this.decryptPrivateKey(file, currentPassword);
    const privateKey = createPrivateKey({ key: privateKeyDer, format: "der", type: "pkcs8" });
    this.assertKeyMatches(file, privateKey);
    const updated: VaultFile = {
      ...file,
      ...this.encryptPrivateKey(privateKeyDer, newPassword),
    };
    this.writeVault(updated, true);
    if (this.unlockedIdentity?.subject === updated.subject) {
      this.privateKey = privateKey;
      this.unlockedIdentity = this.publicIdentity(updated);
    }
    return this.status();
  }

  remove(subject: string, password: string): IdentityVaultStatus {
    const file = this.requireAccount(subject);
    const activeBeforeRemoval = this.readIndex().activeSubject;
    try {
      const privateKeyDer = this.decryptPrivateKey(file, password);
      const privateKey = createPrivateKey({ key: privateKeyDer, format: "der", type: "pkcs8" });
      this.assertKeyMatches(file, privateKey);
    } catch {
      throw new Error("密码不正确，无法删除本机账户");
    }

    fs.unlinkSync(this.vaultPath(subject));
    if (this.unlockedIdentity?.subject === subject) {
      this.privateKey = null;
      this.unlockedIdentity = null;
    }
    const remaining = this.readAccounts();
    const nextActive = subject === activeBeforeRemoval
      ? remaining[0]?.subject || ""
      : remaining.some((account) => account.subject === activeBeforeRemoval)
        ? activeBeforeRemoval
        : remaining[0]?.subject || "";
    this.setActiveSubject(nextActive);
    return this.status();
  }

  exportBackup(destination: string, subject = ""): void {
    const file = this.requireAccount(subject || this.requireActiveFile().subject);
    fs.writeFileSync(destination, JSON.stringify(file, null, 2), {
      encoding: "utf-8",
      mode: 0o600,
      flag: "w",
    });
  }

  importBackup(source: string, password: string): IdentityVaultStatus {
    const imported = this.parseFile(fs.readFileSync(source, "utf-8"));
    if (fs.existsSync(this.vaultPath(imported.subject))) {
      throw new Error("这个身份已经存在于本机");
    }
    const privateKeyDer = this.decryptPrivateKey(imported, password);
    const privateKey = createPrivateKey({ key: privateKeyDer, format: "der", type: "pkcs8" });
    this.assertKeyMatches(imported, privateKey);
    this.writeVault(imported, false);
    this.setActiveSubject(imported.subject);
    this.privateKey = privateKey;
    this.unlockedIdentity = this.publicIdentity(imported);
    return this.status();
  }

  identity(): UnlockedIdentity {
    if (!this.privateKey || !this.unlockedIdentity) throw new Error("请先解锁本机身份");
    return this.unlockedIdentity;
  }

  signChallenge(challenge: string): string {
    if (!this.privateKey) throw new Error("请先解锁本机身份");
    return sign(null, Buffer.from(challenge, "utf-8"), this.privateKey).toString("base64");
  }

  private ensureStorage(): void {
    fs.mkdirSync(this.vaultDirectory, { recursive: true });
    if (!fs.existsSync(this.legacyFilePath)) return;

    const legacy = this.parseFile(fs.readFileSync(this.legacyFilePath, "utf-8"));
    const destination = this.vaultPath(legacy.subject);
    if (!fs.existsSync(destination)) {
      // Rename is atomic on the same volume and preserves the encrypted bytes.
      fs.renameSync(this.legacyFilePath, destination);
    } else {
      const backupPath = `${this.legacyFilePath}.migrated.bak`;
      if (!fs.existsSync(backupPath)) fs.renameSync(this.legacyFilePath, backupPath);
    }
    if (!this.readIndex().activeSubject) this.setActiveSubject(legacy.subject);
  }

  private validatePassword(password: string): void {
    if (password.length < 8) throw new Error("密码至少需要 8 个字符");
  }

  private encryptPrivateKey(privateKey: Buffer, password: string) {
    const salt = randomBytes(16);
    const iv = randomBytes(12);
    const key = scryptSync(password, salt, 32);
    const cipher = createCipheriv("aes-256-gcm", key, iv);
    const encrypted = Buffer.concat([cipher.update(privateKey), cipher.final()]);
    return {
      encryptedPrivateKey: encrypted.toString("base64"),
      salt: salt.toString("base64"),
      iv: iv.toString("base64"),
      authTag: cipher.getAuthTag().toString("base64"),
    };
  }

  private decryptPrivateKey(file: VaultFile, password: string): Buffer {
    const key = scryptSync(password, Buffer.from(file.salt, "base64"), 32);
    const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(file.iv, "base64"));
    decipher.setAuthTag(Buffer.from(file.authTag, "base64"));
    return Buffer.concat([
      decipher.update(Buffer.from(file.encryptedPrivateKey, "base64")),
      decipher.final(),
    ]);
  }

  private requireActiveFile(): VaultFile {
    return this.requireAccount(this.readIndex().activeSubject);
  }

  private requireAccount(subject: string): VaultFile {
    const normalized = subject.trim();
    if (!normalized) throw new Error("本机身份尚未创建");
    const filePath = this.vaultPath(normalized);
    if (!fs.existsSync(filePath)) throw new Error("找不到指定的本机身份");
    return this.parseFile(fs.readFileSync(filePath, "utf-8"));
  }

  private readAccounts(): VaultFile[] {
    if (!fs.existsSync(this.vaultDirectory)) return [];
    return fs.readdirSync(this.vaultDirectory, { withFileTypes: true })
      .filter((entry) => entry.isFile() && entry.name.endsWith(".vault.json"))
      .map((entry) => this.parseFile(
        fs.readFileSync(path.join(this.vaultDirectory, entry.name), "utf-8"),
      ))
      .sort((left, right) => left.displayName.localeCompare(right.displayName, "zh-CN"));
  }

  private resolveActiveSubject(accounts: VaultFile[]): string {
    const indexed = this.readIndex().activeSubject;
    if (accounts.some((file) => file.subject === indexed)) return indexed;
    this.setActiveSubject(accounts[0].subject);
    return accounts[0].subject;
  }

  private readIndex(): VaultIndex {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.indexPath, "utf-8")) as VaultIndex;
      if (parsed.version !== 1 || typeof parsed.activeSubject !== "string") {
        throw new Error("身份索引格式无效");
      }
      return parsed;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        return { version: 1, activeSubject: "" };
      }
      throw error;
    }
  }

  private setActiveSubject(subject: string): void {
    this.writeAtomic(this.indexPath, JSON.stringify({
      version: 1,
      activeSubject: subject,
    } satisfies VaultIndex, null, 2));
  }

  private parseFile(raw: string): VaultFile {
    const parsed = JSON.parse(raw) as VaultFile;
    if (
      parsed.version !== 1
      || !parsed.displayName
      || !parsed.publicKey
      || !parsed.issuer
      || !parsed.subject
      || !parsed.encryptedPrivateKey
      || !parsed.salt
      || !parsed.iv
      || !parsed.authTag
    ) {
      throw new Error("身份文件格式无效");
    }
    const publicKeyBytes = Buffer.from(parsed.publicKey, "base64");
    const expectedSubject = createHash("sha256").update(publicKeyBytes).digest("hex");
    if (
      publicKeyBytes.length !== 32
      || parsed.subject !== expectedSubject
      || parsed.issuer !== `self:key:${expectedSubject}`
    ) {
      throw new Error("身份文件中的公钥标识不一致");
    }
    return parsed;
  }

  private assertKeyMatches(file: VaultFile, privateKey: KeyObject): void {
    const privateJwk = privateKey.export({ format: "jwk" });
    const publicKey = privateJwk.x
      ? Buffer.from(privateJwk.x, "base64url").toString("base64")
      : "";
    if (publicKey !== file.publicKey) throw new Error("身份文件中的公钥与私钥不匹配");
  }

  private publicIdentity(file: VaultFile): UnlockedIdentity {
    return {
      displayName: file.displayName,
      publicKey: file.publicKey,
      issuer: file.issuer,
      subject: file.subject,
    };
  }

  private vaultPath(subject: string): string {
    if (!/^[a-f0-9]{64}$/.test(subject)) throw new Error("身份标识格式无效");
    return path.join(this.vaultDirectory, `${subject}.vault.json`);
  }

  private writeVault(file: VaultFile, overwrite: boolean): void {
    const target = this.vaultPath(file.subject);
    if (!overwrite) {
      fs.writeFileSync(target, JSON.stringify(file, null, 2), {
        encoding: "utf-8",
        mode: 0o600,
        flag: "wx",
      });
      return;
    }
    this.writeAtomic(target, JSON.stringify(file, null, 2));
  }

  private writeAtomic(target: string, payload: string): void {
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const temporaryPath = `${target}.${process.pid}.tmp`;
    fs.writeFileSync(temporaryPath, payload, {
      encoding: "utf-8",
      mode: 0o600,
      flag: "w",
    });
    // copyFile replaces an existing destination on Windows, where rename over
    // an existing file is not portable. The temporary file ensures a complete
    // payload is available before replacement starts.
    fs.copyFileSync(temporaryPath, target);
    fs.unlinkSync(temporaryPath);
  }
}
