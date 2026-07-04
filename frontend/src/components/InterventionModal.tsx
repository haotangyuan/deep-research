import { useEffect, useState } from 'react';
import { AlertCircle, Loader2, Sparkles, X } from 'lucide-react';

import type { CreateInterventionRequest, ResearchIntervention } from '../services/api';
import { INTERVENTION_REINFORCE_MODE_OPTIONS, summarizeIntervention } from '../features/interventions';

interface InterventionModalProps {
  isOpen: boolean;
  pendingIntervention?: ResearchIntervention;
  isSubmitting: boolean;
  error?: string | null;
  onClose: () => void;
  onSubmit: (req: CreateInterventionRequest) => Promise<void>;
}

const REINFORCE_MODE_VALUES = new Set(INTERVENTION_REINFORCE_MODE_OPTIONS.map((option) => option.value));

export function InterventionModal({
  isOpen,
  pendingIntervention,
  isSubmitting,
  error,
  onClose,
  onSubmit,
}: InterventionModalProps) {
  const [sectionsText, setSectionsText] = useState('');
  const [selectedModes, setSelectedModes] = useState<CreateInterventionRequest['reinforceModes']>([]);
  const [note, setNote] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    if (pendingIntervention) {
      setSectionsText((pendingIntervention.focusSections || []).join('\n'));
      setSelectedModes(
        (pendingIntervention.reinforceModes || [])
          .filter((item): item is CreateInterventionRequest['reinforceModes'][number] => REINFORCE_MODE_VALUES.has(item as CreateInterventionRequest['reinforceModes'][number]))
          .slice(0, 2),
      );
      setNote(pendingIntervention.note || '');
      return;
    }
    setSectionsText('');
    setSelectedModes([]);
    setNote('');
  }, [isOpen, pendingIntervention]);

  if (!isOpen) return null;

  const focusSections = sectionsText
    .split(/\n|,|，/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 3);
  const trimmedNote = note.trim();
  const canSubmit = focusSections.length > 0 || selectedModes.length > 0 || Boolean(trimmedNote);
  const handleClose = () => {
    if (isSubmitting) return;
    onClose();
  };

  const toggleMode = (value: CreateInterventionRequest['reinforceModes'][number]) => {
    setSelectedModes((previous) => {
      if (previous.includes(value)) return previous.filter((item) => item !== value);
      if (previous.length >= 2) return previous;
      return [...previous, value];
    });
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    await onSubmit({
      focusSections,
      reinforceModes: selectedModes,
      note: trimmedNote || undefined,
      replacePending: Boolean(pendingIntervention),
    });
  };

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center">
      <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={handleClose} />
      <div className="relative mx-4 w-full max-w-2xl overflow-hidden rounded-[1.75rem] border border-gray-200 bg-white shadow-2xl">
        <button
          type="button"
          onClick={handleClose}
          disabled={isSubmitting}
          className="absolute right-4 top-4 rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="关闭追加关注点面板"
        >
          <X className="h-5 w-5" />
        </button>

        <div className="border-b border-gray-100 bg-[#fcfbf6] px-8 py-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gray-950 text-white">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-xl font-semibold tracking-tight text-gray-950">调整下一轮</h2>
              <p className="mt-1 text-sm text-gray-500">仅对 ULTRA 动态工作流生效，当前轮不会被中断。</p>
            </div>
          </div>
        </div>

        <div className="space-y-6 px-8 py-7">
          {pendingIntervention && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              <div className="flex items-start gap-2">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  <p className="font-medium">当前已有一条待生效的下一轮调整。</p>
                  <p className="mt-1">本次提交会按“最新提交覆盖旧调整”规则替换它。</p>
                  <p className="mt-1 text-amber-900/90">{summarizeIntervention(pendingIntervention) || '已记录下一轮偏置。'}</p>
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <section>
            <label className="mb-2 block text-sm font-medium text-gray-800">重点 section</label>
            <textarea
              value={sectionsText}
              onChange={(event) => setSectionsText(event.target.value)}
              rows={3}
              placeholder="每行一个，或用逗号分隔。最多 3 个。"
              className="w-full resize-none rounded-2xl border border-gray-200 bg-gray-50/70 px-4 py-3 text-sm text-gray-800 placeholder:text-gray-400 focus:border-gray-300 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gray-950/5"
            />
            <p className="mt-2 text-xs text-gray-500">已识别 {focusSections.length}/3 个重点 section。</p>
          </section>

          <section>
            <label className="mb-2 block text-sm font-medium text-gray-800">补强方向</label>
            <div className="grid gap-2 sm:grid-cols-2">
              {INTERVENTION_REINFORCE_MODE_OPTIONS.map((option) => {
                const selected = selectedModes.includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => toggleMode(option.value)}
                    className={`rounded-2xl border px-4 py-3 text-left text-sm transition-colors ${
                      selected
                        ? 'border-gray-950 bg-gray-950 text-white'
                        : 'border-gray-200 bg-gray-50 text-gray-700 hover:border-gray-300 hover:bg-white'
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            <p className="mt-2 text-xs text-gray-500">最多选择 2 个补强方向。</p>
          </section>

          <section>
            <label className="mb-2 block text-sm font-medium text-gray-800">自然语言备注</label>
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={4}
              maxLength={500}
              placeholder="补充你希望系统下一轮优先关注的角度、约束或判断标准。"
              className="w-full resize-none rounded-2xl border border-gray-200 bg-gray-50/70 px-4 py-3 text-sm text-gray-800 placeholder:text-gray-400 focus:border-gray-300 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gray-950/5"
            />
            <p className="mt-2 text-xs text-gray-500">{note.length}/500</p>
          </section>
        </div>

        <div className="flex items-center justify-between border-t border-gray-100 bg-white px-8 py-5">
          <p className="text-xs text-gray-500">提交后会在聊天区、时间线和 Agent Flow 中给出回显。</p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleClose}
              disabled={isSubmitting}
              className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              取消
            </button>
            <button
              type="button"
              disabled={isSubmitting || !canSubmit}
              onClick={handleSubmit}
              className="flex items-center gap-2 rounded-xl bg-gray-950 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {pendingIntervention ? '替换并提交' : '提交调整'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
