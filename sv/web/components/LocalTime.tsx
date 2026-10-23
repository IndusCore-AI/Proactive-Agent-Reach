import { TZ, formatMoment, type TimeStyle } from '@/lib/format';

import { ClientTime } from './ClientTime';

/** A moment in the reader's own time zone. The server renders Pacific time
 * (what crawlers, feeds and readers without JavaScript get) and hands that exact
 * text to the browser, which swaps in its own zone after hydration, so the two
 * renders always match. */
export function LocalTime({ ts, style = 'datetime' }: { ts: string; style?: TimeStyle }) {
  return <ClientTime ts={ts} style={style} pacific={formatMoment(ts, style, TZ)} />;
}
