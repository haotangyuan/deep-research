import { useCallback, useMemo, useState } from 'react';

import { researchApi, type CreateInterventionRequest, type ResearchIntervention } from '../services/api';

const ACTIVE_INTERVENTION_STATUSES = new Set([
  'QUEUE',
  'START',
  'RUNNING',
  'IN_SCOPE',
  'AWAITING_DIRECTION_CONFIRM',
  'IN_RESEARCH',
  'IN_REPORT',
]);

type InterventionCapableResearch = {
  id: string;
  budget?: string;
  status: string;
  pendingIntervention?: ResearchIntervention;
};

export function useResearchIntervention({
  research,
  connectSSE,
  syncResearchSnapshot,
}: {
  research: InterventionCapableResearch | null;
  connectSSE: (researchId: string) => void;
  syncResearchSnapshot: (researchId: string) => Promise<unknown>;
}) {
  const [isInterventionModalOpen, setIsInterventionModalOpen] = useState(false);
  const [isSubmittingIntervention, setIsSubmittingIntervention] = useState(false);
  const [interventionError, setInterventionError] = useState<string | null>(null);

  const canAdjustIntervention = useMemo(() => {
    if (!research) return false;
    const status = (research.status || '').toUpperCase();
    return research.budget === 'ULTRA' && ACTIVE_INTERVENTION_STATUSES.has(status);
  }, [research]);

  const openInterventionModal = useCallback(() => {
    setInterventionError(null);
    setIsInterventionModalOpen(true);
  }, []);

  const closeInterventionModal = useCallback(() => {
    setIsInterventionModalOpen(false);
  }, []);

  const submitIntervention = useCallback(async (req: CreateInterventionRequest) => {
    if (!research) return;
    setIsSubmittingIntervention(true);
    setInterventionError(null);
    try {
      connectSSE(research.id);
      await researchApi.createIntervention(research.id, req);
      await syncResearchSnapshot(research.id);
      setIsInterventionModalOpen(false);
    } catch (e: any) {
      setInterventionError(e?.message || '追加关注点失败');
    } finally {
      setIsSubmittingIntervention(false);
    }
  }, [connectSSE, research, syncResearchSnapshot]);

  return {
    canAdjustIntervention,
    interventionError,
    isInterventionModalOpen,
    isSubmittingIntervention,
    closeInterventionModal,
    openInterventionModal,
    submitIntervention,
  };
}
