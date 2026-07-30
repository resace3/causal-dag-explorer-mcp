/** Simple outlined icons. Every icon is paired with a text label elsewhere. */

interface IconProps {
  size?: number;
  className?: string;
  strokeWidth?: number;
}

function base(size: number, className?: string, strokeWidth = 1.6) {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    className,
    'aria-hidden': true,
    focusable: false,
  };
}

export function ActivityIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <circle cx="13.5" cy="4.5" r="1.9" />
      <path d="M8 21l2.6-5.2L8.4 13 7 9.2 11 7.6l3.4 2.1 2.4 2.6" />
      <path d="M10.6 15.8L14 17l1.6 4" />
    </svg>
  );
}

export function HeartIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M12 20s-7-4.4-7-9.2A4 4 0 0 1 12 8a4 4 0 0 1 7 2.8C19 15.6 12 20 12 20z" />
    </svg>
  );
}

export function WaveIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M2 12h3l2.2-6 3 12 2.6-8.4L15.4 15 17 12h5" />
    </svg>
  );
}

export function GaugeIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M4.4 17a8.5 8.5 0 1 1 15.2 0" />
      <path d="M12 16.5l3.6-4.6" />
      <circle cx="12" cy="17" r="1.2" />
    </svg>
  );
}

export function MoonIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M20 14.2A8.2 8.2 0 0 1 9.8 4a8.4 8.4 0 1 0 10.2 10.2z" />
    </svg>
  );
}

export function ThermometerIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M13.5 13.6V5a1.9 1.9 0 0 0-3.8 0v8.6a4 4 0 1 0 3.8 0z" />
    </svg>
  );
}

export function HomeIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M4 10.6L12 4l8 6.6" />
      <path d="M6 10v9h12v-9" />
    </svg>
  );
}

export function PresenceIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <circle cx="12" cy="12" r="2" />
      <path d="M8.2 15.8a5.4 5.4 0 0 1 0-7.6M15.8 8.2a5.4 5.4 0 0 1 0 7.6" />
      <path d="M5.4 18.6a9.4 9.4 0 0 1 0-13.2M18.6 5.4a9.4 9.4 0 0 1 0 13.2" />
    </svg>
  );
}

export function SunIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <circle cx="12" cy="12" r="3.6" />
      <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.5 1.5M16.9 16.9l1.5 1.5M18.4 5.6l-1.5 1.5M7.1 16.9l-1.5 1.5" />
    </svg>
  );
}

export function ClockIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <circle cx="12" cy="12" r="8.4" />
      <path d="M12 7.4V12l3 1.8" />
    </svg>
  );
}

export function PulseIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M3 12h4l2.4-6 4 12 2.4-6H21" />
    </svg>
  );
}

export function CheckIcon({ size = 16, className, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M4.5 12.5l4.6 4.6L19.5 6.8" />
    </svg>
  );
}

export function CloseIcon({ size = 16, className, strokeWidth = 1.9 }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

export function ChevronDownIcon({ size = 16, className, strokeWidth = 1.9 }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M6 9.5l6 6 6-6" />
    </svg>
  );
}

export function RefreshIcon({ size = 16, className, strokeWidth = 1.7 }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M20 11a8 8 0 1 0-1.2 5.4" />
      <path d="M20 5.5V11h-5.5" />
    </svg>
  );
}

export function InfoIcon({ size = 16, className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <circle cx="12" cy="12" r="8.4" />
      <path d="M12 11.2v5M12 8.1v.1" />
    </svg>
  );
}

export function PlaceIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M5 8.5h5.5L12 5l1.5 3.5H19v9H5z" />
      <circle cx="12" cy="13" r="1.6" />
    </svg>
  );
}

export function PlugIcon({ size = 16, className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M9 4v5M15 4v5" />
      <path d="M6.5 9h11v2.5a5.5 5.5 0 0 1-11 0z" />
      <path d="M12 17v3" />
    </svg>
  );
}

export function WatchIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <rect x="7" y="7" width="10" height="10" rx="2.6" />
      <path d="M9.4 7V4.4h5.2V7M9.4 17v2.6h5.2V17" />
    </svg>
  );
}

export function LayersIcon({ size = 16, className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M12 4l8 4-8 4-8-4 8-4z" />
      <path d="M4 12.6l8 4 8-4" />
    </svg>
  );
}

export function ChevronUpIcon({ size = 16, className, strokeWidth = 1.9 }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M6 14.5l6-6 6 6" />
    </svg>
  );
}

/** The six-dot handle that says "this row can be dragged". */
export function GripIcon({ size = 16, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden
      focusable={false}
    >
      <circle cx="9" cy="6" r="1.6" />
      <circle cx="15" cy="6" r="1.6" />
      <circle cx="9" cy="12" r="1.6" />
      <circle cx="15" cy="12" r="1.6" />
      <circle cx="9" cy="18" r="1.6" />
      <circle cx="15" cy="18" r="1.6" />
    </svg>
  );
}

export function BedIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M3 18V8" />
      <path d="M3 12.5h13a4.5 4.5 0 0 1 4.5 4.5V18" />
      <path d="M3 18h18" />
      <circle cx="8" cy="9.4" r="2.1" />
    </svg>
  );
}

export function PercentIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <circle cx="7.6" cy="7.6" r="2.6" />
      <circle cx="16.4" cy="16.4" r="2.6" />
      <path d="M18 6L6 18" />
    </svg>
  );
}

export function FootstepsIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <ellipse cx="8.4" cy="8.6" rx="2.7" ry="4.1" transform="rotate(-14 8.4 8.6)" />
      <ellipse cx="15.6" cy="15.4" rx="2.7" ry="4.1" transform="rotate(-14 15.6 15.4)" />
    </svg>
  );
}

export function PhoneIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <rect x="7" y="3" width="10" height="18" rx="2.4" />
      <path d="M10.8 17.6h2.4" />
    </svg>
  );
}

export function DoorExitIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M13 4H6v16h7" />
      <path d="M17.5 12H10" />
      <path d="M15 9.4l2.8 2.6-2.8 2.6" />
    </svg>
  );
}

export function CalendarIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <rect x="4" y="5.5" width="16" height="14.5" rx="2.2" />
      <path d="M4 10h16M9 3.4v4M15 3.4v4" />
    </svg>
  );
}

export function BriefcaseIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <rect x="3" y="7.6" width="18" height="12" rx="2.2" />
      <path d="M9 7.6V5.8a1.8 1.8 0 0 1 1.8-1.8h2.4A1.8 1.8 0 0 1 15 5.8v1.8" />
    </svg>
  );
}

export function BoltIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M13.4 3L5.6 13.4h5.4L10.6 21l7.8-10.4H13z" />
    </svg>
  );
}

export function GlassIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M6 4h12l-6 7z" />
      <path d="M12 11v7M8.6 18h6.8" />
    </svg>
  );
}

export function CupIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M4.6 8.4h12v6.2a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4z" />
      <path d="M16.6 10h1.6a2.4 2.4 0 0 1 0 4.8h-1.6" />
      <path d="M8 5.6V4M12 5.6V4" />
    </svg>
  );
}

export function VirusIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <circle cx="12" cy="12" r="5.4" />
      <path d="M12 6.6V3.4M12 17.4v3.2M6.6 12H3.4M17.4 12h3.2M8.2 8.2L6 6M15.8 15.8l2.2 2.2M15.8 8.2L18 6M8.2 15.8L6 18" />
    </svg>
  );
}

export function SunsetIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M7.4 13a4.6 4.6 0 0 1 9.2 0" />
      <path d="M3 17h18" />
      <path d="M12 3.4v3M4.9 6.4l1.6 1.6M19.1 6.4l-1.6 1.6" />
    </svg>
  );
}

export function CycleIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M19.4 12a7.4 7.4 0 1 1-2.2-5.3" />
      <path d="M17.6 3.2v3.9h-3.9" />
      <circle cx="12" cy="12" r="1.8" />
    </svg>
  );
}

export function HouseThermoIcon({ size = 18, className, strokeWidth }: IconProps) {
  return (
    <svg {...base(size, className, strokeWidth)}>
      <path d="M3.6 10.8L12 4l8.4 6.8" />
      <path d="M5.8 10.2V20h12.4v-9.8" />
      <path d="M12 12v3.4" />
      <circle cx="12" cy="17" r="1.7" />
    </svg>
  );
}

const LANE_ICONS: Record<string, (props: IconProps) => JSX.Element> = {
  activity: ActivityIcon,
  heart_rate: HeartIcon,
  hrv: WaveIcon,
  readiness: GaugeIcon,
  sleep: MoonIcon,
  temperature: ThermometerIcon,
  environment: HomeIcon,
  presence: PresenceIcon,
  location: PlaceIcon,
};

export function LaneIcon({ laneId, ...props }: IconProps & { laneId: string }) {
  const Component = LANE_ICONS[laneId] ?? PulseIcon;
  return <Component {...props} />;
}

/**
 * Icons for the causal variables, which are finer-grained than lanes: sleep
 * duration, onset and efficiency all live in the sleep lane but are three
 * different quantities, and a graph node has to say which one it is.
 */
const VARIABLE_ICONS: Record<string, (props: IconProps) => JSX.Element> = {
  exercise: ActivityIcon,
  step_count: FootstepsIcon,
  sleep_duration: BedIcon,
  sleep_onset: MoonIcon,
  sleep_efficiency: PercentIcon,
  resting_heart_rate: HeartIcon,
  hrv: WaveIcon,
  readiness: GaugeIcon,
  skin_temperature: ThermometerIcon,
  room_temperature: HouseThermoIcon,
  light_morning: SunIcon,
  light_evening: SunsetIcon,
  device_use: PhoneIcon,
  time_away: DoorExitIcon,
  location: PlaceIcon,
  day_of_week: CalendarIcon,
  circadian_phase: CycleIcon,
  stress: BoltIcon,
  alcohol: GlassIcon,
  caffeine: CupIcon,
  illness: VirusIcon,
  work_schedule: BriefcaseIcon,
};

export function VariableIcon({ variable, ...props }: IconProps & { variable: string }) {
  const Component = VARIABLE_ICONS[variable] ?? PulseIcon;
  return <Component {...props} />;
}
