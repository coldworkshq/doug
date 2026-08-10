import { createHmac, timingSafeEqual } from "node:crypto";

type InstallFlow = {
  nonce: Uint8Array;
  expiresAt: number;
  subject: string | null;
  installationId: number | null;
};

type SealOptions = InstallFlow & { secret?: string };

type VerifyOptions = {
  now?: number;
  expectedSubject?: string;
  expectedInstallationId?: number;
  secret?: string;
};

const fields = ["exp", "installation_id", "nonce", "sub", "v"];

export class InstallFlowConfigurationError extends Error {
  constructor() {
    super("install flow not configured");
    this.name = "InstallFlowConfigurationError";
  }
}

function invalid(): Error {
  return new Error("invalid install flow");
}

function resolveSecret(secret?: string): string {
  const value = secret ?? process.env.DOUG_INSTALL_FLOW_SECRET;
  if (!value || Buffer.byteLength(value, "utf8") < 32) {
    throw new InstallFlowConfigurationError();
  }
  return value;
}

export function assertInstallFlowConfigured(): void {
  resolveSecret();
}

function decodeBase64Url(value: unknown): Buffer {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) throw invalid();
  const decoded = Buffer.from(value, "base64url");
  if (decoded.toString("base64url") !== value) throw invalid();
  return decoded;
}

function parsePayload(value: unknown): InstallFlow {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw invalid();
  const payload = value as Record<string, unknown>;
  if (JSON.stringify(Object.keys(payload).sort()) !== JSON.stringify(fields)) throw invalid();
  if (payload.v !== 1) throw invalid();
  if (typeof payload.nonce !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(payload.nonce)) {
    throw invalid();
  }
  const nonce = decodeBase64Url(payload.nonce);
  if (nonce.length !== 32) throw invalid();
  if (!Number.isSafeInteger(payload.exp) || (payload.exp as number) <= 0) throw invalid();
  if (payload.sub !== null && (typeof payload.sub !== "string" || payload.sub.length === 0)) {
    throw invalid();
  }
  if (
    payload.installation_id !== null &&
    (!Number.isSafeInteger(payload.installation_id) || (payload.installation_id as number) <= 0)
  ) {
    throw invalid();
  }
  return {
    nonce: Uint8Array.from(nonce),
    expiresAt: payload.exp as number,
    subject: payload.sub as string | null,
    installationId: payload.installation_id as number | null,
  };
}

export function sealInstallFlow({
  nonce,
  expiresAt,
  subject,
  installationId,
  secret,
}: SealOptions): string {
  const signingSecret = resolveSecret(secret);
  const payload = {
    v: 1,
    nonce: Buffer.from(nonce).toString("base64url"),
    exp: expiresAt,
    sub: subject,
    installation_id: installationId,
  };
  parsePayload(payload);
  const segment = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signature = createHmac("sha256", signingSecret)
    .update(segment)
    .digest("base64url");
  return `${segment}.${signature}`;
}

export function verifyInstallFlow(token: string, options: VerifyOptions = {}): InstallFlow {
  const signingSecret = resolveSecret(options.secret);
  try {
    const parts = token.split(".");
    if (parts.length !== 2) throw invalid();
    const [segment, suppliedSignature] = parts;
    const signature = decodeBase64Url(suppliedSignature);
    const expectedSignature = createHmac("sha256", signingSecret)
      .update(segment)
      .digest();
    if (signature.length !== expectedSignature.length || !timingSafeEqual(signature, expectedSignature)) {
      throw invalid();
    }
    const flow = parsePayload(JSON.parse(decodeBase64Url(segment).toString("utf8")));
    const now = options.now ?? Math.floor(Date.now() / 1000);
    if (flow.expiresAt <= now) throw invalid();
    if (options.expectedSubject !== undefined && flow.subject !== options.expectedSubject) {
      throw invalid();
    }
    if (
      options.expectedInstallationId !== undefined &&
      flow.installationId !== options.expectedInstallationId
    ) {
      throw invalid();
    }
    return flow;
  } catch {
    throw invalid();
  }
}
