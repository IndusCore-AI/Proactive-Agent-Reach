'use client';

import { useState } from 'react';

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
      <img src={src} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
    </div>
  );
}
