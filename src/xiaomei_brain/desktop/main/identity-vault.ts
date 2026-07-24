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

export interface IdentityVaultStatus {
  exists: boolean;
  unlocked: boolean;
  displayName?: string;
  issuer?: string;
  subject?: string;
}

export interface UnlockedIdentity {
  displayName: string;
  publicKey: string;
  issuer: string;
  subject: string;
}

/**
 * Stores the Desktop identity key encrypted at rest. The renderer can ask the
 * vault to sign a Gateway challenge, but it can never read the private key.
 */
export class IdentityVault {
  private readonly filePath: string;
  private privateKey: KeyObject | null = null;
  private unlockedIdentity: UnlockedIdentity | null = null;

  constructor() {
    this.filePath = path.join(app.getPath("userData"), "identity-vault.json");
  }

  status(): IdentityVaultStatus {
    const file = this.readFile();
    if (!file) return { exists: false, unlocked: false };
    return {
      exists: true,
      unlocked: this.privateKey !== null,
      displayName: file.displayName,
      issuer: file.issuer,
      subject: file.subject,
    };
  }

  create(displayName: string, password: string): IdentityVaultStatus {
    if (this.readFile()) throw new Error("本机身份已经存在");
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
    this.writeFile(file, false);
    this.privateKey = privateKey;
    this.unlockedIdentity = { displayName: name, publicKey: publicKeyBase64, issuer, subject };
    return this.status();
  }

  unlock(password: string): IdentityVaultStatus {
    const file = this.requireFile();
    try {
      const keyDer = this.decryptPrivateKey(file, password);
      this.privateKey = createPrivateKey({ key: keyDer, format: "der", type: "pkcs8" });
      this.assertKeyMatches(file, this.privateKey);
      this.unlockedIdentity = {
        displayName: file.displayName,
        publicKey: file.publicKey,
        issuer: file.issuer,
        subject: file.subject,
      };
    } catch {
      this.privateKey = null;
      this.unlockedIdentity = null;
      throw new Error("密码不正确或身份文件已损坏");
    }
    return this.status();
  }

  lock(): IdentityVaultStatus {
    this.privateKey = null;
    this.unlockedIdentity = null;
    return this.status();
  }

  changePassword(currentPassword: string, newPassword: string): IdentityVaultStatus {
    this.validatePassword(newPassword);
    const file = this.requireFile();
    const privateKeyDer = this.decryptPrivateKey(file, currentPassword);
    const privateKey = createPrivateKey({ key: privateKeyDer, format: "der", type: "pkcs8" });
    this.assertKeyMatches(file, privateKey);
    const updated: VaultFile = {
      ...file,
      ...this.encryptPrivateKey(privateKeyDer, newPassword),
    };
    this.writeFile(updated, true);
    this.privateKey = privateKey;
    this.unlockedIdentity = this.publicIdentity(updated);
    return this.status();
  }

  exportBackup(destination: string): void {
    const file = this.requireFile();
    // Exporting copies the encrypted envelope and never exposes plaintext key material.
    fs.writeFileSync(destination, JSON.stringify(file, null, 2), {
      encoding: "utf-8",
      mode: 0o600,
      flag: "w",
    });
  }

  importBackup(source: string, password: string): IdentityVaultStatus {
    if (this.readFile()) throw new Error("本机身份已经存在，不能覆盖导入");
    const imported = this.parseFile(fs.readFileSync(source, "utf-8"));
    const privateKeyDer = this.decryptPrivateKey(imported, password);
    const privateKey = createPrivateKey({ key: privateKeyDer, format: "der", type: "pkcs8" });
    this.assertKeyMatches(imported, privateKey);
    this.writeFile(imported, false);
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

  private requireFile(): VaultFile {
    const file = this.readFile();
    if (!file) throw new Error("本机身份尚未创建");
    return file;
  }

  private readFile(): VaultFile | null {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.filePath, "utf-8")) as VaultFile;
      if (
        parsed.version !== 1
        || !parsed.displayName
        || !parsed.publicKey
        || !parsed.issuer
        || !parsed.subject
        || !parsed.encryptedPrivateKey
      ) {
        throw new Error("身份文件格式无效");
      }
      return parsed;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw error;
    }
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

  private writeFile(file: VaultFile, overwrite: boolean): void {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
    const payload = JSON.stringify(file, null, 2);
    if (!overwrite) {
      fs.writeFileSync(this.filePath, payload, {
        encoding: "utf-8", mode: 0o600, flag: "wx",
      });
      return;
    }
    const temporaryPath = `${this.filePath}.tmp`;
    fs.writeFileSync(temporaryPath, payload, {
      encoding: "utf-8", mode: 0o600, flag: "w",
    });
    fs.copyFileSync(temporaryPath, this.filePath);
    fs.unlinkSync(temporaryPath);
  }
}
