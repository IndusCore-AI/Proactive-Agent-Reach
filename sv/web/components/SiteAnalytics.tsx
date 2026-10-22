'use client';

import { Analytics } from '@vercel/analytics/next';

// Visitors reach this zone through induscore.site, whose Vercel project
// (ai-native-crm-website) already has Web Analytics on. Loading the script and
// sending page views to the host root records /sv/* in that same dashboard;
// the basePath default (/sv/_vercel/...) would point at this zone's project,
// where Vercel only lets analytics be switched on from the dashboard.
// Search terms are dropped before sending: page views keep the path and the
// filter, never what someone typed.
export function SiteAnalytics() {
  return (
    <Analytics
      scriptSrc="/_vercel/insights/script.js"
      endpoint="/_vercel/insights"
      beforeSend={(event) => {
        const url = new URL(event.url);
        url.searchParams.delete('q');
        return { ...event, url: url.toString() };
      }}
    />
  );
}
