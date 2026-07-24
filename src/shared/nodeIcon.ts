export type NodeIconKind =
  | 'activity'
  | 'sleep'
  | 'stress'
  | 'mood'
  | 'productivity'
  | 'caffeine'
  | 'meditation'
  | 'temperature'
  | 'humidity'
  | 'light'
  | 'generic';

const aliases: Record<string, NodeIconKind> = {
  activity: 'activity',
  exercise: 'activity',
  movement: 'activity',
  steps: 'activity',
  workout: 'activity',
  sleep: 'sleep',
  asleep: 'sleep',
  bed: 'sleep',
  rest: 'sleep',
  stress: 'stress',
  anxiety: 'stress',
  mood: 'mood',
  emotion: 'mood',
  smile: 'mood',
  productivity: 'productivity',
  work: 'productivity',
  focus: 'productivity',
  rocket: 'productivity',
  caffeine: 'caffeine',
  coffee: 'caffeine',
  meditation: 'meditation',
  meditate: 'meditation',
  mindful: 'meditation',
  temperature: 'temperature',
  temp: 'temperature',
  heat: 'temperature',
  humidity: 'humidity',
  water: 'humidity',
  light: 'light',
  lamp: 'light',
  bulb: 'light',
  generic: 'generic'
};

const labelRules: Array<[NodeIconKind, RegExp]> = [
  ['activity', /\b(activity|active|exercise|movement|steps?|walk|walking|workout|running|run)\b/i],
  ['sleep', /\b(sleep|asleep|bed|bedtime|rest|wake|waking|insomnia)\b/i],
  ['stress', /\b(stress|anxiety|anxious|worry|overwhelm|tension)\b/i],
  ['mood', /\b(mood|emotion|happy|happiness|sad|wellbeing|well-being)\b/i],
  ['productivity', /\b(productivity|productive|work|focus|task|performance|energy)\b/i],
  ['caffeine', /\b(caffeine|coffee|espresso|tea)\b/i],
  ['meditation', /\b(meditation|meditate|mindful|mindfulness|breathing)\b/i],
  ['temperature', /\b(temperature|temp|heat|hot|cold|climate)\b/i],
  ['humidity', /\b(humidity|humid|water|moisture)\b/i],
  ['light', /\b(light|lamp|brightness|illuminance)\b/i]
];

export function resolveNodeIcon(label: string, explicitIcon?: string): NodeIconKind {
  const explicit = explicitIcon?.trim().toLowerCase();
  if (explicit && aliases[explicit]) return aliases[explicit];

  for (const [kind, pattern] of labelRules) {
    if (pattern.test(label)) return kind;
  }
  return 'generic';
}
