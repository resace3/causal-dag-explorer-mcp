import { resolveNodeIcon, type NodeIconKind } from '../shared/nodeIcon';

interface NodeLogoProps {
  label: string;
  icon?: string;
  className?: string;
}

function LogoPaths({ kind }: { kind: NodeIconKind }) {
  switch (kind) {
    case 'activity':
      return <>
        <circle cx="15.5" cy="4.5" r="2" />
        <path d="m13.5 8-3.4 3.2-3.6.7M13.5 8l3 3 3.5 1M12.2 10.2l-1 4.2-3.7 5.1M11.2 14.4l4.5 1.7 2 3.4" />
      </>;
    case 'sleep':
      return <>
        <path d="M4 16.5V9.7M4 13.5h16v5M7.2 9.5h4.1a2.2 2.2 0 0 1 2.2 2.2v1.8H7.2v-4Z" />
        <path d="M4 18.5v1M20 18.5v1M15.5 5.2h3l-3 3h3" />
      </>;
    case 'stress':
      return <>
        <path d="M12.8 3.5a7.5 7.5 0 0 0-6.6 11v3.7h5v2.3h4.6v-3.8a7.5 7.5 0 0 0-3-13.2Z" />
        <path d="m12.6 7-2.7 4h2.4l-1 4.2 3.5-5h-2.5L12.6 7Z" />
      </>;
    case 'mood':
      return <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M8.8 10h.01M15.2 10h.01M8.5 14.2c1.8 2 5.2 2 7 0" />
      </>;
    case 'productivity':
      return <>
        <path d="M14.2 4.2c2.4-.9 4.5-.8 5.6-.5.3 1.2.4 3.3-.5 5.7l-5.2 5.2-4.7-4.7 4.8-5.7Z" />
        <circle cx="16.2" cy="7.6" r="1.3" />
        <path d="m9.8 11.1-3.9.6-2 2 4.3.8M12.9 14.2l-.6 3.9-2 2-.8-4.3M7.4 17.1l-2.5 2.5" />
      </>;
    case 'caffeine':
      return <>
        <path d="M5 8.5h11v6.2a4.3 4.3 0 0 1-4.3 4.3H9.3A4.3 4.3 0 0 1 5 14.7V8.5Z" />
        <path d="M16 10h1.4a2.6 2.6 0 0 1 0 5.2H16M8 5.5c-1-1 .9-1.7 0-2.7M12 5.5c-1-1 .9-1.7 0-2.7" />
      </>;
    case 'meditation':
      return <>
        <circle cx="12" cy="5" r="2" />
        <path d="M8.5 10.2c2.3 1.3 4.7 1.3 7 0M12 7v6M12 13l-3.2 3.4M12 13l3.2 3.4M8.8 16.4 5 18.2h14l-3.8-1.8" />
      </>;
    case 'temperature':
      return <>
        <path d="M10 5a2 2 0 0 1 4 0v9.1a4.3 4.3 0 1 1-4 0V5Z" />
        <path d="M12 7v9M17 7h2M17 11h2" />
      </>;
    case 'humidity':
      return <path d="M12 3.2S6.2 10 6.2 14.7a5.8 5.8 0 0 0 11.6 0C17.8 10 12 3.2 12 3.2ZM9.3 15.2c.3 1.6 1.3 2.5 2.9 2.8" />;
    case 'light':
      return <>
        <path d="M8.4 15.6a6.2 6.2 0 1 1 7.2 0c-.8.6-1.1 1.4-1.1 2.4h-5c0-1-.3-1.8-1.1-2.4Z" />
        <path d="M9.8 21h4.4M12 1V.5M4.2 4.2l-1-1M19.8 4.2l1-1M2 11H.5M23.5 11H22" />
      </>;
    default:
      return <>
        <circle cx="6" cy="12" r="2.4" />
        <circle cx="18" cy="6" r="2.4" />
        <circle cx="18" cy="18" r="2.4" />
        <path d="m8.2 10.9 7.6-3.8M8.2 13.1l7.6 3.8" />
      </>;
  }
}

export function NodeLogo({ label, icon, className = '' }: NodeLogoProps) {
  const kind = resolveNodeIcon(label, icon);
  return <span className={`node-logo${className ? ` ${className}` : ''}`} data-icon-kind={kind} aria-hidden="true">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <LogoPaths kind={kind} />
    </svg>
  </span>;
}
