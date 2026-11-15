import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import https from "node:https";
import test from "node:test";
import { load } from "./load-typescript.mjs";

const { publicHttpsUrl, publicIPv4, imageCandidates, fetchPublic, getPinned, listingPhoto } =
  load("../src/lib/listing-photo.server.ts");
const PAGE = "https://homes.example.org/listing/123";
const IP = "93.184.216.34";
const response = (body, contentType = "text/html", status = 200) => ({
  status, contentType, body: Buffer.from(body),
});
const signal = () => AbortSignal.timeout(1000);

test("preview metadata supports attribute order, casing, relative URLs and escaped query strings", () => {
  const html = `<META content='/front.jpg?a=1&amp;b=2' property='OG:IMAGE'>
    <meta name="twitter:image" content="//images.example.org/back.jpg">
    <meta property=og:image content='/front.jpg?a=1&#38;b=2'>`;
  assert.deepEqual(imageCandidates(html, new URL(PAGE)), [
    "https://homes.example.org/front.jpg?a=1&b=2", "https://images.example.org/back.jpg",
  ]);
});

test("JSON-LD image objects and arrays work without executing scripts", () => {
  const html = `<script type="application/ld+json">{"@graph":[{"image":["/one.jpg",{"contentUrl":"/two.jpg"}]}]}</script>
    <script type="application/ld+json">broken json</script>
    <script>throw new Error('must not execute')</script>`;
  assert.deepEqual(imageCandidates(html, new URL(PAGE)), [
    "https://homes.example.org/one.jpg", "https://homes.example.org/two.jpg",
  ]);
});

test("logos and unsafe metadata do not masquerade as property photographs", () => {
  const html = `<meta property="og:image" content="/site-logo.png">
    <meta property="og:image" content="/images/logos/meta/share-graphic.jpg">
    <meta property="og:image" content="javascript:alert(1)">
    <meta property="og:image" content="http://images.example.org/house.jpg">
    <meta property="og:image" content="https://127.0.0.1/secret">
    <img src="/an-advert.jpg">`;
  assert.deepEqual(imageCandidates(html, new URL(PAGE)), []);
});

test("a generic portal share graphic is skipped in favour of the listing's JSON-LD photo", () => {
  const html = `<meta property="og:image" content="https://cdn.example.org/images/logos/share.jpg">
    <script type="application/ld+json">{"@type":"Apartment","image":"https://photos.example.org/listings/123/front.JPG"}</script>`;
  assert.deepEqual(imageCandidates(html, new URL(PAGE)), ["https://photos.example.org/listings/123/front.JPG"]);
});

test("URL validation rejects credentials, IP spelling tricks, unsafe schemes and ports", () => {
  for (const url of [
    "http://homes.example.org/", "file:///secret", "https://user:password@homes.example.org/",
    "https://127.1/", "https://2130706433/", "https://0x7f000001/", "https://[::1]/",
    "https://localhost/", "https://machine.local/", "https://homes.example.org:8443/", "",
  ]) assert.throws(() => publicHttpsUrl(url), undefined, url);
  assert.equal(publicHttpsUrl("https://homes.example.org:443/flat#photos").href, "https://homes.example.org/flat");
});

test("DNS checks reject private, reserved, IPv6 and metadata-service addresses", () => {
  for (const address of [
    "0.0.0.0", "10.0.0.1", "127.0.0.1", "169.254.169.254", "100.100.100.200",
    "172.16.2.1", "192.168.1.1", "192.0.2.1", "198.18.0.1", "198.51.100.2",
    "203.0.113.1", "224.0.0.1", "255.255.255.255", "::ffff:127.0.0.1", "::1",
  ]) assert.equal(publicIPv4(address), false, address);
  assert.equal(publicIPv4(IP), true);
});

test("mixed public/private DNS answers are rejected before any connection", async () => {
  await assert.rejects(fetchPublic(PAGE, 100, signal(), {
    resolve: async () => [IP, "10.0.0.1"],
    get: async () => assert.fail("must not connect"),
  }), /Non-public/);
});

test("redirects are resolved afresh and private redirect hosts cannot be fetched", async () => {
  const calls = [];
  await assert.rejects(fetchPublic(PAGE, 100, signal(), {
    resolve: async (host) => host.startsWith("private.") ? ["169.254.169.254"] : [IP],
    get: async (url, address) => {
      calls.push([url.href, address]);
      return { ...response("", "text/html", 302), location: "https://private.example.org/" };
    },
  }), /Non-public/);
  assert.deepEqual(calls, [[PAGE, IP]]);
});

test("redirects preserve the final base URL and stop after three hops", async () => {
  const moved = await fetchPublic(PAGE, 100, signal(), {
    resolve: async () => [IP],
    get: async (url) => url.pathname.startsWith("/listing")
      ? { ...response("", "text/html", 302), location: "/new/flat" } : response("done"),
  });
  assert.equal(moved.url.href, "https://homes.example.org/new/flat");
  let calls = 0;
  await assert.rejects(fetchPublic(PAGE, 100, signal(), {
    resolve: async () => [IP],
    get: async () => { calls++; return { ...response("", "text/html", 302), location: "/loop" }; },
  }), /Too many redirects/);
  assert.equal(calls, 4);
});

test("a slow DNS resolver is cut off by the shared request deadline", async () => {
  const controller = new AbortController();
  const work = fetchPublic(PAGE, 100, controller.signal, {
    resolve: () => new Promise(() => {}), get: async () => assert.fail("must not connect"),
  });
  controller.abort(new Error("deadline"));
  await assert.rejects(work, /deadline/);
});

test("HTML and image hosts both go through the pinned transport", async () => {
  const calls = [];
  const photo = await listingPhoto(PAGE, {
    resolve: async () => [IP],
    get: async (url, address) => {
      calls.push([url.href, address]);
      return url.href === PAGE ? response('<meta property="og:image" content="https://images.example.org/flat.jpg">')
        : response("image bytes", "image/jpeg");
    },
  });
  assert.equal(photo.contentType, "image/jpeg");
  assert.deepEqual(calls, [[PAGE, IP], ["https://images.example.org/flat.jpg", IP]]);
});

test("a broken primary image falls through to another declared image", async () => {
  const photo = await listingPhoto(PAGE, {
    resolve: async () => [IP],
    get: async (url) => url.href === PAGE
      ? response('<meta property="og:image" content="/broken.jpg"><meta name="twitter:image" content="/good.webp">')
      : url.pathname === "/broken.jpg" ? response("", "text/html", 404) : response("image", "image/webp"),
  });
  assert.equal(photo.contentType, "image/webp");
});

test("missing images, blocked listings, SVG and non-image responses use the fallback", async () => {
  for (const type of ["image/svg+xml", "text/html", "application/octet-stream"]) {
    assert.equal(await listingPhoto(PAGE, {
      resolve: async () => [IP],
      get: async (url) => url.href === PAGE
        ? response('<meta property="og:image" content="/image">') : response("untrusted", type),
    }), null);
  }
  for (const page of [response("No photo"), response("Blocked", "text/html", 403)]) {
    assert.equal(await listingPhoto(PAGE, { resolve: async () => [IP], get: async () => page }), null);
  }
});

test("private image metadata and oversized resources are rejected", async () => {
  assert.equal(await listingPhoto(PAGE, {
    resolve: async (host) => host.startsWith("private.") ? ["10.0.0.1"] : [IP],
    get: async (url) => {
      assert.equal(url.href, PAGE);
      return response('<meta property="og:image" content="https://private.example.org/secret">');
    },
  }), null);
  await assert.rejects(fetchPublic(PAGE, 3, signal(), {
    resolve: async () => [IP], get: async () => response("too large"),
  }), /exceeds limits/);
});

test("the HTTPS connection uses the checked IP, original TLS name and no forwarded credentials", async (t) => {
  const seen = [];
  t.mock.method(https, "request", (options, callback) => {
    seen.push(options);
    const req = new EventEmitter();
    req.end = () => {
      const res = new EventEmitter();
      res.statusCode = 200;
      res.headers = { "content-type": "image/jpeg" };
      callback(res);
      res.emit("data", Buffer.from("ok"));
      res.emit("end");
    };
    return req;
  });
  assert.equal((await getPinned(new URL(PAGE), IP, 10, signal())).body.toString(), "ok");
  assert.equal(seen[0].hostname, IP);
  assert.equal(seen[0].servername, "homes.example.org");
  assert.equal(seen[0].headers.Host, "homes.example.org");
  assert.equal(seen[0].agent, false);
  assert.equal(seen[0].headers.Cookie, undefined);
  assert.equal(seen[0].headers.Authorization, undefined);
  assert.notEqual(seen[0].rejectUnauthorized, false);
});

test("the real transport stops oversized streamed bodies even without Content-Length", async (t) => {
  let destroyed = false;
  t.mock.method(https, "request", (_options, callback) => {
    const req = new EventEmitter();
    req.destroy = (error) => { destroyed = true; req.emit("error", error); };
    req.end = () => {
      const res = new EventEmitter();
      res.statusCode = 200; res.headers = { "content-type": "image/jpeg" };
      callback(res);
      res.emit("data", Buffer.alloc(11));
    };
    return req;
  });
  await assert.rejects(getPinned(new URL(PAGE), IP, 10, signal()), /exceeds limits/);
  assert.equal(destroyed, true);
});
