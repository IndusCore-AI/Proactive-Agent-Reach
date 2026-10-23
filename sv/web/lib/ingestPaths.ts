// The ingest API calls the public site forwards to the VM, by method. Pure,
// so `npm test` checks it. Anything else answers 404 before it leaves Vercel.
const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const DATE = '\\d{4}-\\d{2}-\\d{2}';
const MOVER = '[a-z0-9][a-z0-9-]{1,59}';

const ALLOWED: Record<'GET' | 'POST', RegExp[]> = {
  GET: [
    new RegExp(`^runs/${UUID}$`), // a run's status
    new RegExp(`^editions/${DATE}$`), // what an edition holds, for verification
    /^movers$/, // every mover, so a run can match stories to them
    /^movers\/feedback$/, // the founders' votes and stages, so a run learns what they want
    /^research$/, // the research runs stored, for verification
  ],
  POST: [
    /^runs$/,
    new RegExp(`^runs/${UUID}/(items|finish)$`),
    /^movers$/, // propose, add or update movers
    new RegExp(`^movers/${MOVER}/(link|archive|notes)$`), // notes: the founders' take or score only
    /^research$/, // record research runs for the founders' Research page
  ],
};

export function ingestPathAllowed(method: 'GET' | 'POST', segments: string[]): boolean {
  const path = segments.join('/');
  return ALLOWED[method].some((re) => re.test(path));
}
