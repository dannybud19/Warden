"use client";

import Image from "next/image";
import { useState } from "react";

/** A listing's declared photo, with an honest fallback while loading or after any failure. */
export function ListingPhoto({
  listingUrl, fallback = "/warden/photo-mile-end-front.png", sizes, priority = false, compact = false,
}: {
  listingUrl?: string | null; fallback?: string; sizes: string; priority?: boolean; compact?: boolean;
}) {
  // Bump when image selection changes so an earlier cached portal logo is not reused.
  const source = listingUrl ? `/api/listing-photo?v=2&url=${encodeURIComponent(listingUrl)}` : null;
  const [loaded, setLoaded] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const available = source !== null && failed !== source;
  const showingListing = available && loaded === source;

  return (
    <div className="absolute inset-0" data-photo-state={showingListing ? "listing" : "placeholder"}>
      <Image src={fallback} alt={showingListing ? "" : "Default placeholder, not a photo of this listing"}
        fill sizes={sizes} className="object-cover" loading={priority ? "eager" : "lazy"} />
      {available && (
        <Image key={source} src={source} alt="Photo provided by the property listing" fill sizes={sizes}
          unoptimized loading={priority ? "eager" : "lazy"} fetchPriority={priority ? "high" : "auto"}
          className={`object-cover transition-opacity ${showingListing ? "opacity-100" : "opacity-0"}`}
          onLoad={() => setLoaded(source)} onError={() => setFailed(source)} />
      )}
      {!showingListing && (
        <span className={`absolute z-10 rounded bg-ink/75 text-center font-medium text-white ${compact
          ? "inset-x-1 bottom-1 px-1 py-1 text-[9px] leading-[1.2]"
          : "left-3 top-3 px-2.5 py-1.5 text-[11.5px] leading-none"}`}>
          Default placeholder
        </span>
      )}
    </div>
  );
}
