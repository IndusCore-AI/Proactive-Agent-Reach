// The desk's next steps for a mover: prompts a founder copies into Claude
// Code. Pure (no Next imports), so `npm test` checks them. PRIVATE: they carry
// the founders' take and score, so they are only built for an unlocked page.
import type { DeskMover, RubricLine } from './types.ts';

export const RUBRIC: { key: RubricLine; label: string; max: number }[] = [
  { key: 'demand', label: 'Demand evidence', max: 25 },
  { key: 'problem', label: 'Problem sharpness', max: 10 },
  { key: 'fit', label: 'Founder fit', max: 15 },
  { key: 'wedge', label: 'Wedge speed', max: 10 },
  { key: 'market', label: 'Market size', max: 10 },
  { key: 'future', label: 'Future fit', max: 15 },
  { key: 'moat', label: 'Defensibility', max: 10 },
  { key: 'whitespace', label: 'Whitespace', max: 5 },
];

/** The rubric's bands (teamctx k:878): where a total lands. */
export function band(total: number): { key: 'drop' | 'watch' | 'interview' | 'strong'; label: string } {
  if (total >= 70) return { key: 'strong', label: 'Strong' };
  if (total >= 55) return { key: 'interview', label: 'Worth interviews' };
  if (total >= 40) return { key: 'watch', label: 'Watch' };
  return { key: 'drop', label: 'Below the cutoff' };
}

export interface NextStep {
  key: 'rea' | 'build' | 'score';
  title: string;
  why: string;
  prompt: string;
}

const RULES =
  'Rules: every number gets a source link and a date; mark anything unchecked "unverified"; say "not found" rather than guess. ' +
  'Never put customer names or customer data into a search or outside tool.';

function marketOf(m: DeskMover): string {
  return m.score?.market ?? (m.notes.localize ? 'the market named under "Where to localize" below' : 'a market you name first (India, Southeast Asia, Europe or Australia and New Zealand)');
}

function facts(m: DeskMover, pageUrl: string): string {
  const lines = [`Reference: ${m.name} (${m.url}), ${m.one_liner}`, `Desk page: ${pageUrl}`];
  if (m.summary) lines.push(`Summary: ${m.summary}`);
  for (const t of m.traction) lines.push(`- ${t.label}: ${t.value} (${t.source_url}, as of ${t.as_of})`);
  if (m.markets_live.length) lines.push(`Live in: ${m.markets_live.join(', ')}`);
  return lines.join('\n');
}

function take(m: DeskMover): string {
  const out: string[] = [];
  if (m.notes.take) out.push(`How it helps us: ${m.notes.take}`);
  if (m.notes.learn) out.push(`What to learn: ${m.notes.learn}`);
  if (m.notes.localize) out.push(`Where to localize: ${m.notes.localize}`);
  return out.join('\n');
}

function scoreLine(m: DeskMover): string {
  if (!m.score) return 'Not scored yet.';
  const lines = RUBRIC.map((r) => `${r.label.toLowerCase()} ${m.score!.lines[r.key]}/${r.max}`).join(', ');
  return `${m.score.total}/100 for ${m.score.market} (${band(m.score.total).label.toLowerCase()}): ${lines}.${m.score.verdict ? ` Verdict: ${m.score.verdict}` : ''}`;
}

function votes(m: DeskMover): string {
  if (!m.votes.length) return '';
  return `Founders' votes: ${m.votes.map((v) => `${v.voter} ${v.vote > 0 ? 'up' : 'down'}${v.reason ? ` ("${v.reason}")` : ''}`).join('; ')}`;
}

function block(...parts: string[]): string {
  return parts.filter(Boolean).join('\n\n');
}

export function reaPrompt(m: DeskMover, pageUrl: string): NextStep {
  const market = marketOf(m);
  if (m.kind === 'skill') {
    return {
      key: 'rea',
      title: 'Take it apart',
      why: 'Read the source, try it, and see what people would pay for.',
      prompt: block(
        `Take apart the skill or open-source tool ${m.name} (${m.url}) so we can decide whether to package something like it for ${market}.`,
        facts(m, pageUrl),
        take(m),
        'Steps:\n1. Stage it with the skill-radar skill (scripts/install_skill.py owner/repo, without --yes) and read every file before running anything.\n2. Say what it does, what it needs (keys, accounts, platforms), and what breaks outside its home market.\n3. Find who already sells something like it, at what price, with what proof of customers.\n4. Write the smallest paid version for that market: who pays, the price, and the channel.',
        `Save to ~/Desktop/research/rea-${m.id}.md and record the verdict in teamctx with remember (kind fact, status assumption, related k:1008).`,
        RULES,
      ),
    };
  }
  return {
    key: 'rea',
    title: 'Reverse-engineer it with REA',
    why: 'See exactly how it onboards, charges and keeps people, with evidence.',
    prompt: block(
      `Use the reverse-engineer-anything skill (REA) on ${m.name} (${m.url}). Goal: understand it well enough to build a localized version for ${market}.`,
      facts(m, pageUrl),
      take(m),
      'Capture with REA, keeping evidence ids for every claim:\n1. The public site and the sign-up or onboarding flow: every step, field and default.\n2. Pricing and paywall: plans, prices, trial, and where the paywall appears.\n3. The core loop: what a user does each day and what the product does for them.\n4. The stack: framework, AI providers, payments, analytics and other third parties seen in the bundle and network calls.\n5. Reach: languages offered, sign-in methods, app store listings.',
      `Then write a reconstruction plan for ${market}: what to copy as is, what to change (language, payments, channel, pricing), and the smallest version a stranger could pay for within two weeks.`,
      `Save to ~/Desktop/research/rea-${m.id}.md and record the plan in teamctx with remember (kind fact, status assumption, related k:1008).`,
      RULES,
    ),
  };
}

export function buildBrief(m: DeskMover, pageUrl: string): NextStep {
  const market = marketOf(m);
  return {
    key: 'build',
    title: 'Build brief',
    why: 'Plan it, then build only the two-week test.',
    prompt: block(
      `Build brief: a localized ${m.name} for ${market}.`,
      facts(m, pageUrl),
      take(m),
      `Our score: ${scoreLine(m)}`,
      votes(m),
      'Plan before building:\n1. Run /office-hours (startup mode) on this brief. Confirm the buyer, the pain in their own words, and the cheapest two-week test.\n2. Run /plan-ceo-review on the result, then /plan-eng-review for the smallest build.\n3. Build only the two-week test: a landing page with a real price, or a concierge version run by hand. Run the Apple design pass on any UI.\n4. Say what result in two weeks means "keep going" and what means "stop".',
      'Record each decision in teamctx with remember (kind decision, related k:1008).',
      RULES,
    ),
  };
}

export function scorePrompt(m: DeskMover, pageUrl: string): NextStep {
  const market = marketOf(m);
  const scoreJson = JSON.stringify(
    { score: { lines: Object.fromEntries(RUBRIC.map((r) => [r.key, 0])), market: m.score?.market ?? 'NAMED MARKET', verdict: 'one line' } },
    null,
    1,
  );
  return {
    key: 'score',
    title: m.score ? 'Score it again' : 'Score it',
    why: 'Run office hours on the localized idea and put the score on the desk.',
    prompt: block(
      `Run /office-hours (startup mode) on one idea: a localized ${m.name} for ${market}.`,
      facts(m, pageUrl),
      take(m),
      `Current score: ${scoreLine(m)}`,
      votes(m),
      'Score the localized version (not the original product) with our rubric in teamctx k:878, unchanged: 8 lines, 100 points (demand evidence 25, problem sharpness 10, founder fit 15, wedge speed 10, market size 10, future fit 15, defensibility 10, whitespace 5), bands at 40, 55 and 70. Compare it with our current best-scored idea (search teamctx for the latest office-hours scores). Below 40, say plainly that it does not make the list.',
      `Then put the score on the desk with the aggregate-silicon-valley skill:\n  python3 scripts/ingest.py notes ${m.id} score.json\nwhere score.json is:\n${scoreJson}`,
      RULES,
    ),
  };
}

export function nextSteps(m: DeskMover, pageUrl: string): NextStep[] {
  return [reaPrompt(m, pageUrl), buildBrief(m, pageUrl), scorePrompt(m, pageUrl)];
}
