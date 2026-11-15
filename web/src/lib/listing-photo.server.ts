/** Public listing previews only: every connection is pinned to a checked public IPv4 address. */
import { lookup } from "node:dns/promises";
import { request } from "node:https";
import { isIP } from "node:net";

const HTML_LIMIT = 1024 * 1024;
const IMAGE_LIMIT = 5 * 1024 * 1024;
const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/avif", "image/gif"];

export interface Download {
  status: number;
  contentType: string;
  location?: string;
  body: Buffer;
}

interface Transport {
  resolve: (host: string) => Promise<string[]>;
  get: (url: URL, address: string, limit: number, signal: AbortSignal) => Promise<Download>;
}

/** Reject credentials, local names, IP literals and non-HTTPS/standard-port URLs. */
export function publicHttpsUrl(raw: string, base?: URL): URL {
  if (!raw.trim() || raw.length > 2048) throw new Error("Unsupported URL");
  const url = new URL(raw, base);
  if (url.protocol !== "https:" || url.username || url.password || url.port ||
      !url.hostname.includes(".") || isIP(url.hostname) || url.hostname.includes(":") ||
      /\.(?:localhost|local|internal|test|invalid|example)\.?$/i.test(url.hostname)) {
    throw new Error("Unsupported URL");
  }
  url.hash = "";
  return url;
}

/** Exclude private, loopback, link-local, documentation, multicast and reserved IPv4 ranges. */
export function publicIPv4(address: string): boolean {
  if (isIP(address) !== 4) return false;
  const [a, b, c] = address.split(".").map(Number);
  return !(a === 0 || a === 10 || a === 127 || a >= 224 ||
    (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && (b === 168 || b === 0 || (b === 88 && c === 99))) ||
    (a === 198 && (b === 18 || b === 19 || (b === 51 && c === 100))) ||
    (a === 203 && b === 0 && c === 113));
}

async function withinDeadline<T>(work: Promise<T>, signal: AbortSignal): Promise<T> {
  signal.throwIfAborted();
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    work.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}

/** Connect to the approved IP while retaining the original hostname for TLS and HTTP. */
export function getPinned(url: URL, address: string, limit: number, signal: AbortSignal): Promise<Download> {
  return new Promise((resolve, reject) => {
    const req = request({
      hostname: address, servername: url.hostname, port: 443, method: "GET",
      path: url.pathname + url.search, agent: false, signal,
      headers: {
        Host: url.hostname, Accept: "text/html,application/xhtml+xml,image/*",
        "Accept-Encoding": "identity", "User-Agent": "Warden-ListingPreview/1.0",
      },
    }, (res) => {
      res.on("error", reject);
      const result = {
        status: res.statusCode ?? 0,
        contentType: (res.headers["content-type"] ?? "").split(";")[0].trim().toLowerCase(),
        location: res.headers.location,
      };
      if (result.status !== 200) {
        resolve({ ...result, body: Buffer.alloc(0) });
        res.destroy();
        return;
      }
      if (Number(res.headers["content-length"]) > limit ||
          (res.headers["content-encoding"] && res.headers["content-encoding"] !== "identity")) {
        req.destroy(new Error("Preview exceeds limits or uses an unsupported encoding"));
        return;
      }
      let size = 0;
      const chunks: Buffer[] = [];
      res.on("data", (chunk: Buffer) => {
        size += chunk.length;
        if (size > limit) req.destroy(new Error("Preview exceeds limits"));
        else chunks.push(chunk);
      });
      res.on("end", () => resolve({ ...result, body: Buffer.concat(chunks) }));
    });
    req.on("error", reject);
    req.end();
  });
}

/** Recheck and pin DNS on every redirect; never send cookies, credentials or incoming headers. */
export async function fetchPublic(
  raw: string, limit: number, signal: AbortSignal, transport: Partial<Transport> = {},
): Promise<Download & { url: URL }> {
  const resolve = transport.resolve ?? (async (host: string) =>
    (await lookup(host, { family: 4, all: true })).map((record) => record.address));
  const get = transport.get ?? getPinned;
  let url = publicHttpsUrl(raw);
  for (let redirects = 0; redirects <= 3; redirects++) {
    signal.throwIfAborted();
    const addresses = await withinDeadline(resolve(url.hostname), signal);
    if (!addresses.length || !addresses.every(publicIPv4)) throw new Error("Non-public destination");
    const response = await withinDeadline(get(url, addresses[0], limit, signal), signal);
    if ([301, 302, 303, 307, 308].includes(response.status) && response.location) {
      url = publicHttpsUrl(response.location, url);
      continue;
    }
    if (response.body.length > limit) throw new Error("Preview exceeds limits");
    return { ...response, url };
  }
  throw new Error("Too many redirects");
}

function decodeAttribute(value: string): string {
  const named: Record<string, string> = { amp: "&", quot: '"', apos: "'", lt: "<", gt: ">" };
  return value.replace(/&(#x[\da-f]+|#\d+|amp|quot|apos|lt|gt);/gi, (entity, code: string) => {
    if (!code.startsWith("#")) return named[code.toLowerCase()] ?? entity;
    const point = code[1].toLowerCase() === "x" ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
    return point > 0 && point <= 0x10ffff ? String.fromCodePoint(point) : entity;
  });
}

function attributes(tag: string): Record<string, string> {
  return Object.fromEntries([...tag.matchAll(/([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))/g)]
    .map((m) => [m[1].toLowerCase(), decodeAttribute(m[2] ?? m[3] ?? m[4]) ]));
}

/** Read declared preview images, not arbitrary images such as page adverts or tracking pixels. */
export function imageCandidates(html: string, page: URL): string[] {
  const candidates: string[] = [];
  const meta = [...html.matchAll(/<meta\b(?:[^"'<>]|"[^"]*"|'[^']*')*>/gi)].map((m) => attributes(m[0]));
  for (const key of ["og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src"]) {
    for (const tag of meta) {
      if ((tag.property ?? tag.name ?? "").toLowerCase() === key && tag.content) candidates.push(tag.content);
    }
  }
  // Some listings expose their photos only through JSON-LD. Bound recursion to avoid hostile input.
  function visit(value: unknown, depth = 0) {
    if (!value || typeof value !== "object" || depth > 8 || candidates.length >= 20) return;
    if (Array.isArray(value)) { value.slice(0, 30).forEach((item) => visit(item, depth + 1)); return; }
    const object = value as Record<string, unknown>;
    const images = Array.isArray(object.image) ? object.image : [object.image];
    for (const item of images) {
      if (typeof item === "string") candidates.push(item);
      else if (item && typeof item === "object") {
        const image = item as Record<string, unknown>;
        const url = image.contentUrl ?? image.url;
        if (typeof url === "string") candidates.push(url);
      }
    }
    Object.values(object).slice(0, 30).forEach((item) => visit(item, depth + 1));
  }
  for (const script of html.matchAll(/<script\b((?:[^"'<>]|"[^"]*"|'[^']*')*)>([\s\S]*?)<\/script\s*>/gi)) {
    if (attributes(script[1]).type?.toLowerCase() !== "application/ld+json") continue;
    try { visit(JSON.parse(script[2])); } catch { /* Malformed metadata is not a failed case. */ }
  }
  const urls: string[] = [];
  for (const candidate of candidates) {
    try {
      const url = publicHttpsUrl(candidate, page);
      if (!/(?:^|[\/_.-])(?:logos?|placeholders?|favicons?)(?:[\/_.-]|$)/i.test(url.pathname)) urls.push(url.href);
    } catch { /* Ignore unusable metadata and try the next image. */ }
  }
  return [...new Set(urls)].slice(0, 3);
}

/** Return a listing's image bytes, or null so the UI can show its labelled placeholder. */
export async function listingPhoto(raw: string, transport: Partial<Transport> = {}): Promise<Download | null> {
  const signal = AbortSignal.timeout(10_000);
  try {
    const page = await fetchPublic(raw, HTML_LIMIT, signal, transport);
    if (page.status !== 200 || !["text/html", "application/xhtml+xml"].includes(page.contentType)) return null;
    for (const image of imageCandidates(page.body.toString("utf8"), page.url)) {
      try {
        const photo = await fetchPublic(image, IMAGE_LIMIT, signal, transport);
        if (photo.status === 200 && photo.body.length && IMAGE_TYPES.includes(photo.contentType)) return photo;
      } catch { /* A broken image should not prevent another declared photo from loading. */ }
    }
  } catch { /* Inaccessible listings, deadlines and blocked destinations use the fallback. */ }
  return null;
}
