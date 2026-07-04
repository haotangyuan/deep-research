import type { CreateInterventionRequest, ResearchIntervention } from '../services/api';

export const INTERVENTION_REINFORCE_MODE_LABELS: Record<CreateInterventionRequest['reinforceModes'][number], string> = {
  official: '官方来源',
  data: '数据证据',
  comparison: '对比观点',
  latest: '最新信息',
};
export const INTERVENTION_REINFORCE_MODE_OPTIONS: Array<{
  value: CreateInterventionRequest['reinforceModes'][number];
  label: string;
}> = Object.entries(INTERVENTION_REINFORCE_MODE_LABELS).map(([value, label]) => ({
  value: value as CreateInterventionRequest['reinforceModes'][number],
  label,
}));

export function interventionReinforceModeLabel(mode: string) {
  return INTERVENTION_REINFORCE_MODE_LABELS[mode as keyof typeof INTERVENTION_REINFORCE_MODE_LABELS] || mode;
}

export function summarizeIntervention(intervention?: Pick<ResearchIntervention, 'focusSections' | 'reinforceModes' | 'note'> | null) {
  if (!intervention) return '';
  const parts: string[] = [];
  if (intervention.focusSections?.length) parts.push(`重点：${intervention.focusSections.join('、')}`);
  if (intervention.reinforceModes?.length) {
    parts.push(`补强：${intervention.reinforceModes.map(interventionReinforceModeLabel).join('、')}`);
  }
  if (intervention.note) parts.push(`备注：${intervention.note}`);
  return parts.join(' | ');
}
