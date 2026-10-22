'use client';

import { useEffect, useRef, useState } from 'react';

declare global {
  interface Window {
    twttr?: { widgets?: { load: (el?: HTMLElement) => void } };
  }
}

let widgetsRequested = false;

/** X's official embed. The server renders X's documented blockquote markup
 * (readable without JS and by crawlers); widgets.js upgrades it only once the
 * post nears the viewport, so a page of cards never loads X up front. */
export function XEmbed({ id, title, url }: { id: string; title: string; url: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        io.disconnect();
        if (window.twttr?.widgets) {
          window.twttr.widgets.load(el);
        } else if (!widgetsRequested) {
          widgetsRequested = true;
          const s = document.createElement('script');
          s.src = 'https://platform.twitter.com/widgets.js';
          s.async = true;
          s.charset = 'utf-8';
          document.body.appendChild(s);
        }
      },
      { rootMargin: '400px 0px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div className="embed" ref={ref}>
      <blockquote className="twitter-tweet embed-fallback" data-dnt="true" data-conversation="none">
        <p>{title}</p>
        <a href={`https://twitter.com/i/status/${id}`}>View this post on X</a>
        <span className="sr-only"> ({url})</span>
      </blockquote>
    </div>
  );
}

/** YouTube's player, loaded only when asked for (privacy-enhanced domain). */
export function YouTubeEmbed({ id, title }: { id: string; title: string }) {
  const [on, setOn] = useState(false);
  return (
    <div className="embed">
      <div className="yt">
        {on ? (
          <iframe
            src={`https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?autoplay=1&rel=0`}
            title={title}
            allow="autoplay; encrypted-media; picture-in-picture"
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
          />
        ) : (
          <button type="button" className="yt-play" onClick={() => setOn(true)} aria-label={`Play video: ${title}`}>
            <span>
              <span className="icon" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="#fff"><path d="M8 5v14l11-7z" /></svg>
              </span>
            </span>
            <span>
              Play on YouTube
              <small>Loads YouTube&apos;s player</small>
            </span>
          </button>
        )}
      </div>
    </div>
  );
}
