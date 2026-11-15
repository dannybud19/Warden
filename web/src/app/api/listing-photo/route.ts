import { listingPhoto } from "@/lib/listing-photo.server";

/** Fetch a bounded public preview without changing the case or treating the photo as evidence. */
export async function GET(request: Request) {
  const url = new URL(request.url).searchParams.get("url");
  const photo = url ? await listingPhoto(url) : null;
  if (!photo) {
    return new Response(null, { status: 404, headers: { "Cache-Control": "private, max-age=60" } });
  }
  return new Response(new Uint8Array(photo.body), {
    headers: {
      "Content-Type": photo.contentType,
      "Cache-Control": "private, max-age=3600",
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'none'; sandbox",
    },
  });
}
