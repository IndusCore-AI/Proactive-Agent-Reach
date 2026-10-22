import { ImageResponse } from 'next/og';

import { SITE_NAME } from '@/lib/format';

export const alt = SITE_NAME;
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

export default function OgImage() {
  return new ImageResponse(
    (
      <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', background: '#fbfaf7', padding: 72, color: '#16150f' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 30, fontWeight: 700 }}>
          <div style={{ width: 52, height: 52, borderRadius: 13, background: '#16150f', color: '#fbfaf7', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 22, fontWeight: 800 }}>SV</div>
          induscore.site/sv
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontSize: 92, fontWeight: 800, letterSpacing: -3, lineHeight: 1 }}>Keeping Up with</div>
          <div style={{ fontSize: 92, fontWeight: 800, letterSpacing: -3, lineHeight: 1.05 }}>Silicon Valley</div>
          <div style={{ fontSize: 32, color: '#47443d', marginTop: 28 }}>Funding, launches, founders and VCs. One source-linked edition a day.</div>
        </div>
        <div style={{ display: 'flex', gap: 14, fontSize: 22, fontWeight: 700, letterSpacing: 2 }}>
          <span style={{ color: '#1d7349' }}>FUNDING</span>
          <span style={{ color: '#1a5c93' }}>LAUNCHES</span>
          <span style={{ color: '#b0342c' }}>NEWS</span>
          <span style={{ color: '#9a5300' }}>DISCUSSIONS</span>
          <span style={{ color: '#0e6a73' }}>ANALYSIS</span>
        </div>
      </div>
    ),
    size,
  );
}
