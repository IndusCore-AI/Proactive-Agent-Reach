'use client';

import { useEffect, useState } from 'react';

import { formatMoment, type TimeStyle } from '@/lib/format';

// Engines differ in the space before AM/PM (a narrow no-break space or a plain one).
const same = (a: string, b: string) => a.replace(/\s/gu, ' ') === b.replace(/\s/gu, ' ');

export function ClientTime({ ts, style, pacific }: { ts: string; style: TimeStyle; pacific: string }) {
  const [text, setText] = useState(pacific);
  useEffect(() => {
    try {
      setText(formatMoment(ts, style));
    } catch {
      // an unusual runtime without the zone data: keep Pacific
    }
  }, [ts, style]);
  return (
    <time dateTime={ts} title={same(text, pacific) ? undefined : pacific}>
      {text}
    </time>
  );
}
