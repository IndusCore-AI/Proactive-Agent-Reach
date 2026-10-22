'use client';

import { useState } from 'react';

import type { Category } from '@/lib/types';

/** A link to the publisher's own preview image (never a copy). If the image
 * is missing or its host refuses it, a designed cover in the story's
 * category colour takes its place, so a card never shows a broken image. */
export function Thumb({
  src,
  kind,
  publisher,
  category,
  eager = false,
}: {
  src?: string | null;
  kind?: 'cover' | 'logo' | null;
  publisher: string;
  category: Category;
  eager?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <div className={`thumb cover-tile cat-${category}`} aria-hidden="true">
        <span>{publisher}</span>
      </div>
    );
  }
  return (
    <div className={`thumb${kind === 'logo' ? ' logo-tile' : ''}`}>
      {/* eslint-disable-next-line @next/next/no-img-element -- the publisher's file, loaded from its own host */}
      <img
        src={src}
        alt=""
        loading={eager ? 'eager' : 'lazy'}
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
    </div>
  );
}
