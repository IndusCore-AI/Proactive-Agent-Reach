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
export interface XPostProps {
  id: string;
  title: string;
  post?: { author: string; handle: string; text: string; date: string; url: string } | null;
}

export function XEmbed({ id, title, post }: XPostProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  useEffect(() => {
    setTheme(window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
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
      { rootMargin: '600px 0px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div className="embed x-embed" ref={ref}>
      {post ? (
        <blockquote className="twitter-tweet embed-fallback x-card" data-dnt="true" data-conversation="none" data-theme={theme}>
          <span className="x-author">
            <b>{post.author}</b> <span>@{post.handle}</span>
          </span>
          <p>{post.text}</p>
          <a href={post.url}>
            {post.date ? `${post.date} · ` : ''}View on X
          </a>
        </blockquote>
      ) : (
        <blockquote className="twitter-tweet embed-fallback" data-dnt="true" data-conversation="none" data-theme={theme}>
          <p>A post about: {title}</p>
          <a href={`https://twitter.com/i/status/${id}`}>View this post on X</a>
        </blockquote>
      )}
    </div>
  );
}

/** YouTube's player, loaded only when asked for (privacy-enhanced domain).
 * Until then it shows YouTube's own poster frame for the video. */
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
            {/* eslint-disable-next-line @next/next/no-img-element -- YouTube's own poster frame */}
            <img src={`https://i.ytimg.com/vi/${encodeURIComponent(id)}/hqdefault.jpg`} alt="" loading="lazy" referrerPolicy="no-referrer" />
            <span className="yt-badge" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
            </span>
          </button>
        )}
      </div>
    </div>
  );
}
