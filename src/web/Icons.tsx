type IconName = 'graph' | 'timeline' | 'evidence' | 'data' | 'settings' | 'plus' | 'save' | 'trash' | 'edit' | 'close' | 'info' | 'link';

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  const content: Record<IconName, React.ReactNode> = {
    graph: <><circle cx="6" cy="6" r="2.4" /><circle cx="18" cy="5" r="2.4" /><circle cx="12" cy="18" r="2.4" /><path d="M8.4 5.8l7.2-.5M7.2 8.1l3.6 7.6m5.9-8.5l-3.5 8.5" /></>,
    timeline: <><path d="M4 19V5m0 14h16" /><path d="M6.5 15l4-5 3 2 5-7" /><circle cx="10.5" cy="10" r=".8" fill="currentColor" /></>,
    evidence: <><path d="M12 3l1.3 3.7L17 8l-3.7 1.3L12 13l-1.3-3.7L7 8l3.7-1.3L12 3z" /><path d="M5 13l.8 2.2L8 16l-2.2.8L5 19l-.8-2.2L2 16l2.2-.8L5 13zm13-1l.8 2.2 2.2.8-2.2.8L18 18l-.8-2.2L15 15l2.2-.8L18 12z" /></>,
    data: <><ellipse cx="12" cy="5.5" rx="7" ry="3" /><path d="M5 5.5v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6M5 11.5v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.8 1.8 0 00.4 2l.1.1-2.8 2.8-.1-.1a1.8 1.8 0 00-2-.4 1.8 1.8 0 00-1.1 1.7V21h-4v-.1A1.8 1.8 0 008.8 19a1.8 1.8 0 00-2 .4l-.1.1-2.8-2.8.1-.1a1.8 1.8 0 00.4-2A1.8 1.8 0 002.7 13H2V9h.7a1.8 1.8 0 001.7-1.1 1.8 1.8 0 00-.4-2l-.1-.1L6.7 3l.1.1a1.8 1.8 0 002 .4A1.8 1.8 0 009.9 1.8V2h4v-.2A1.8 1.8 0 0015 3.5a1.8 1.8 0 002-.4l.1-.1 2.8 2.8-.1.1a1.8 1.8 0 00-.4 2A1.8 1.8 0 0021.1 9h.9v4h-.9a1.8 1.8 0 00-1.7 2z" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    save: <><path d="M5 4h12l2 2v14H5z" /><path d="M8 4v6h8V4m-8 16v-6h8v6" /></>,
    trash: <><path d="M5 7h14M9 7V4h6v3m2 0l-1 13H8L7 7" /><path d="M10 11v5m4-5v5" /></>,
    edit: <><path d="M5 19l1-4L16.5 4.5a2.1 2.1 0 013 3L9 18z" /><path d="M14.8 6.2l3 3" /></>,
    close: <path d="M6 6l12 12M18 6L6 18" />,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10h.01" /></>,
    link: <><path d="M10 13a4 4 0 010-5.7l1.5-1.5a4 4 0 015.7 5.7L16 12.7" /><path d="M14 11a4 4 0 010 5.7l-1.5 1.5a4 4 0 01-5.7-5.7L8 11.3" /></>
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" {...common}>{content[name]}</svg>;
}

export function GraphLogo() {
  return <span className="graph-logo" aria-hidden="true"><Icon name="graph" size={27} /></span>;
}
