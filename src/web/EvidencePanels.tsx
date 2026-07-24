import { useEffect, useMemo, useState } from 'react';
import type { DayDiagram, DailyEvidencePoint, RelationshipEvidence } from '../shared/types';
import { Icon } from './Icons';

export type EvidenceTab = 'timeline' | 'pattern' | 'stats' | 'summary';

interface EvidenceWorkspaceProps {
  day: DayDiagram;
  selectedEdgeId?: string;
  tab: EvidenceTab;
  onTabChange: (tab: EvidenceTab) => void;
}

const supportLabel = {
  supportive: 'Supportive',
  not_supportive: 'Not supportive',
  mixed: 'Mixed'
} as const;

function values(points: DailyEvidencePoint[], key: 'sourceValue' | 'targetValue') {
  return points.map((point) => point[key]);
}

function stats(series: number[]) {
  if (!series.length) return null;
  const total = series.reduce((sum, value) => sum + value, 0);
  return {
    min: Math.min(...series),
    max: Math.max(...series),
    mean: total / series.length
  };
}

function formatValue(value: number) {
  return Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(1).replace(/\.0$/, '');
}

function LineChart({ points, sourceLabel, targetLabel, sourceUnit, targetUnit, selectedIndex, onSelect }: {
  points: Array<{ label: string; sourceValue: number; targetValue: number }>;
  sourceLabel: string;
  targetLabel: string;
  sourceUnit?: string;
  targetUnit?: string;
  selectedIndex?: number;
  onSelect?: (index: number) => void;
}) {
  if (!points.length) return <EvidenceEmpty compact />;
  const width = 920;
  const height = 220;
  const padX = 38;
  const padY = 24;
  const xAt = (index: number) => padX + index * ((width - padX * 2) / Math.max(1, points.length - 1));
  const normalize = (series: number[], value: number, top: number, regionHeight: number) => {
    const min = Math.min(...series);
    const max = Math.max(...series);
    const range = max - min || 1;
    return top + regionHeight - ((value - min) / range) * regionHeight;
  };
  const source = points.map((point) => point.sourceValue);
  const target = points.map((point) => point.targetValue);
  const sourcePath = points.map((point, index) => `${xAt(index)},${normalize(source, point.sourceValue, 26, 58)}`).join(' ');
  const targetPath = points.map((point, index) => `${xAt(index)},${normalize(target, point.targetValue, 126, 58)}`).join(' ');
  const shownLabels = new Set([0, Math.floor((points.length - 1) / 2), points.length - 1]);

  return <div className="line-chart">
    <div className="chart-legend"><span><i className="legend-line source" />{sourceLabel} {sourceUnit ? `(${sourceUnit})` : ''}</span><span><i className="legend-line target" />{targetLabel} {targetUnit ? `(${targetUnit})` : ''}</span></div>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${sourceLabel} and ${targetLabel} aligned evidence`}>
      <path className="chart-grid" d={`M${padX} 100H${width - padX}M${padX} 200H${width - padX}`} />
      {selectedIndex !== undefined && <rect className="selected-column" x={xAt(selectedIndex) - 14} y="12" width="28" height="188" rx="8" />}
      <polyline className="chart-line source" points={sourcePath} />
      <polyline className="chart-line target" points={targetPath} />
      {points.map((point, index) => <g key={`${point.label}-${index}`} className={onSelect ? 'chart-point clickable' : 'chart-point'} onClick={() => onSelect?.(index)}>
        <circle className="source-point" cx={xAt(index)} cy={normalize(source, point.sourceValue, 26, 58)} r="3.4" />
        <circle className="target-point" cx={xAt(index)} cy={normalize(target, point.targetValue, 126, 58)} r="3.4" />
        {shownLabels.has(index) && <text x={xAt(index)} y="216" textAnchor="middle">{point.label}</text>}
      </g>)}
      <text className="axis-label" x="4" y="58">{sourceLabel}</text>
      <text className="axis-label" x="4" y="158">{targetLabel}</text>
    </svg>
  </div>;
}

function EvidenceEmpty({ compact = false }: { compact?: boolean }) {
  return <div className={`evidence-empty${compact ? ' compact' : ''}`}>
    <Icon name="timeline" size={24} />
    <div><strong>No aligned observations saved</strong><span>Import bounded relationship evidence through the MCP to populate this view.</span></div>
  </div>;
}

function relationshipFor(day: DayDiagram, selectedEdgeId?: string): RelationshipEvidence | undefined {
  const relationships = day.evidence?.relationships ?? [];
  return relationships.find((item) => item.edgeId === selectedEdgeId) ?? relationships[0];
}

export function EvidenceWorkspace({ day, selectedEdgeId, tab, onTabChange }: EvidenceWorkspaceProps) {
  const relationship = relationshipFor(day, selectedEdgeId);
  const edge = day.edges.find((item) => item.id === relationship?.edgeId) ?? day.edges.find((item) => item.id === selectedEdgeId) ?? day.edges[0];
  const sourceLabel = day.nodes.find((node) => node.id === edge?.source)?.label ?? 'Source';
  const targetLabel = day.nodes.find((node) => node.id === edge?.target)?.label ?? 'Target';
  const daily = relationship?.daily ?? [];
  const [selectedDay, setSelectedDay] = useState(0);
  useEffect(() => setSelectedDay(0), [relationship?.edgeId]);
  const selectedPoint = daily[Math.min(selectedDay, Math.max(0, daily.length - 1))];
  const sourceStats = useMemo(() => stats(values(daily, 'sourceValue')), [daily]);
  const targetStats = useMemo(() => stats(values(daily, 'targetValue')), [daily]);
  const supportCount = relationship?.supportCount ?? daily.filter((point) => point.support === 'supportive').length;
  const totalCount = relationship?.totalCount ?? daily.length;

  return <section className="evidence-workspace" aria-label="Evidence workspace">
    <div className="evidence-tabs" role="tablist" aria-label="Evidence views">
      <button role="tab" aria-selected={tab === 'timeline'} className={tab === 'timeline' ? 'active' : ''} onClick={() => onTabChange('timeline')}><Icon name="timeline" size={16} /> Timelines</button>
      <button role="tab" aria-selected={tab === 'pattern'} className={tab === 'pattern' ? 'active' : ''} onClick={() => onTabChange('pattern')}><Icon name="evidence" size={16} /> Day pattern</button>
      <button role="tab" aria-selected={tab === 'stats'} className={tab === 'stats' ? 'active' : ''} onClick={() => onTabChange('stats')}>Descriptive stats</button>
      <button role="tab" aria-selected={tab === 'summary'} className={tab === 'summary' ? 'active' : ''} onClick={() => onTabChange('summary')}>Summary</button>
      <span className="evidence-window">{day.evidence?.windowLabel ?? 'No time window supplied'}</span>
    </div>

    <div className="evidence-content">
      {tab === 'timeline' && <>
        <div className="section-heading"><div><h3>Aligned evidence timeline</h3><p>{edge ? `${sourceLabel} to ${targetLabel}` : 'Select an edge to inspect its observations.'}</p></div><span className="safe-label">Recorded summaries only</span></div>
        {daily.length ? <LineChart points={daily} sourceLabel={sourceLabel} targetLabel={targetLabel} sourceUnit={relationship?.sourceUnit} targetUnit={relationship?.targetUnit} selectedIndex={selectedDay} onSelect={setSelectedDay} /> : <EvidenceEmpty />}
      </>}

      {tab === 'pattern' && <>
        <div className="section-heading"><div><h3>Evidence strip</h3><p>{relationship?.summary ?? 'No relationship summary supplied.'}</p></div>{totalCount > 0 && <strong className="support-total">{supportCount} of {totalCount} supportive</strong>}</div>
        {daily.length ? <>
          <div className="pattern-legend"><span className="supportive">Supportive</span><span className="not-supportive">Not supportive</span><span className="mixed">Mixed</span></div>
          <div className="evidence-strip" role="list" aria-label="Daily evidence pattern">
            {daily.map((point, index) => <button role="listitem" key={`${point.label}-${index}`} className={`evidence-day ${point.support.replace('_', '-')}${selectedDay === index ? ' selected' : ''}`} title={`${point.label}: ${supportLabel[point.support]}`} onClick={() => setSelectedDay(index)}><small>{index + 1}</small><span>{point.support === 'supportive' ? '✓' : point.support === 'mixed' ? '◐' : '−'}</span></button>)}
          </div>
          <div className="drilldown-heading"><div><h3>Selected observation</h3><span>{selectedPoint?.label}</span></div><div><button disabled={selectedDay === 0} onClick={() => setSelectedDay((index) => Math.max(0, index - 1))}>Previous</button><button disabled={selectedDay === daily.length - 1} onClick={() => setSelectedDay((index) => Math.min(daily.length - 1, index + 1))}>Next</button></div></div>
          {relationship?.hourly?.length
            ? <LineChart points={relationship.hourly} sourceLabel={sourceLabel} targetLabel={targetLabel} sourceUnit={relationship.sourceUnit} targetUnit={relationship.targetUnit} />
            : <div className="selected-values"><span><small>{sourceLabel}</small><strong>{formatValue(selectedPoint.sourceValue)} {relationship?.sourceUnit}</strong></span><span><small>{targetLabel}</small><strong>{formatValue(selectedPoint.targetValue)} {relationship?.targetUnit}</strong></span><span><small>Classification</small><strong>{supportLabel[selectedPoint.support]}</strong></span></div>}
        </> : <EvidenceEmpty />}
      </>}

      {tab === 'stats' && <>
        <div className="section-heading"><div><h3>Descriptive statistics</h3><p>Simple summaries of the saved observations; no causal or inferential analysis.</p></div><span className="safe-label">No p-values or model fit</span></div>
        {sourceStats && targetStats ? <div className="stats-grid">
          <StatCard label={sourceLabel} unit={relationship?.sourceUnit} {...sourceStats} />
          <StatCard label={targetLabel} unit={relationship?.targetUnit} {...targetStats} />
          <div className="stat-card"><small>Supportive observations</small><strong>{supportCount} / {totalCount}</strong><span>{totalCount ? Math.round((supportCount / totalCount) * 100) : 0}% classified supportive</span></div>
          <div className="stat-card"><small>Evidence strength label</small><strong>{relationship?.strengthLabel ?? 'Not supplied'}</strong><span>User- or source-provided label</span></div>
        </div> : <EvidenceEmpty />}
      </>}

      {tab === 'summary' && <div className="summary-grid">
        <article><Icon name="graph" size={22} /><small>Diagram</small><strong>{day.nodes.length} boxes, {day.edges.length} edges</strong><p>All directed-cycle, duplicate-edge, and self-edge rules are enforced when saved.</p></article>
        <article><Icon name="data" size={22} /><small>Evidence source</small><strong>{day.evidence?.provider === 'ha_unofficial_ai' ? 'HA Unofficial AI' : day.evidence?.provider === 'synthetic_example' ? 'Synthetic example' : 'Manual diagram'}</strong><p>{day.evidence?.entityIds.length ?? 0} source entity IDs saved; no credentials are stored.</p></article>
        <article><Icon name="info" size={22} /><small>Question</small><strong>{day.evidence?.question ?? 'No evidence question supplied'}</strong><p>{day.evidence?.notes[0] ?? 'Add provenance and limitations through the MCP evidence fields.'}</p></article>
      </div>}
    </div>
  </section>;
}

function StatCard({ label, unit, min, max, mean }: { label: string; unit?: string; min: number; max: number; mean: number }) {
  return <div className="stat-card"><small>{label}</small><strong>{formatValue(mean)} {unit}</strong><span>Range {formatValue(min)}–{formatValue(max)} {unit}</span></div>;
}
