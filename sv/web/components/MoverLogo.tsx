'use client';

import { useEffect, useRef, useState } from 'react';

/** The mover's own logo, loaded from its host (never a copy). If it is
 * missing or refused, a monogram tile takes its place. */
export function MoverLogo({
  src,
  kind,
  name,
  large = false,
}: {
  src?: string | null;
  kind?: 'cover' | 'logo' | null;
  name: string;
  large?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const img = useRef<HTMLImageElement>(null);
  // An image that failed before hydration never fires onError for React;
  // catch it on mount so the monogram still replaces a broken icon.
  useEffect(() => {
    if (img.current?.complete && img.current.naturalWidth === 0) setFailed(true);
  }, [src]);
  const size = large ? ' large' : '';
  if (!src || failed) {
    return (
      <div className={`mover-logo mono${size}`} aria-hidden="true">
        {name.trim().charAt(0).toUpperCase() || '·'}
      </div>
    );
  }
  return (
    <div className={`mover-logo${kind === 'cover' ? ' cover' : ''}${size}`}>
      {/* eslint-disable-next-line @next/next/no-img-element -- the mover's own file, loaded from its host */}
      <img ref={img} src={src} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
    </div>
  );
}
