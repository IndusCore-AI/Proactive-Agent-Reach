'use client';

import { useEffect, useRef, useState } from 'react';

/** Copies a next-step prompt. Without JavaScript the prompt is still there to
 * select by hand inside the "See the prompt" disclosure next to it. */
export function CopyPrompt({ text, label }: { text: string; label: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  async function copy() {
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch {
      // Older browsers, or clipboard permission refused: select a hidden copy instead.
      const area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      ok = document.execCommand('copy');
      area.remove();
    }
    setState(ok ? 'copied' : 'failed');
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState('idle'), 1800);
  }

  return (
    <>
      <button type="button" className={`btn copy${state === 'copied' ? ' done' : ''}`} onClick={copy} aria-label={`Copy prompt: ${label}`}>
        {state === 'copied' ? (
          <>
            <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
              <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="m3.5 8.5 3 3 6-7" />
            </svg>
            Copied
          </>
        ) : (
          <>
            <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
              <rect x="5" y="5" width="8.5" height="8.5" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
              <path fill="none" stroke="currentColor" strokeWidth="1.5" d="M10.5 3.5v-.25A1.75 1.75 0 0 0 8.75 1.5h-5.5A1.75 1.75 0 0 0 1.5 3.25v5.5c0 .97.78 1.75 1.75 1.75h.25" />
            </svg>
            Copy prompt
          </>
        )}
      </button>
      <span className="sr-only" role="status" aria-live="polite">
        {state === 'copied' ? 'Prompt copied' : state === 'failed' ? 'Could not copy; open the prompt and select it' : ''}
      </span>
    </>
  );
}
