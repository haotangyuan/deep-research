import { useEffect, useMemo, useState, ChangeEvent, FormEvent, ReactNode } from 'react';
import { AlertCircle, CheckCircle2, Plus, RefreshCw, Shield, Trash2, User as UserIcon, X } from 'lucide-react';
import { modelApi, ModelInfo } from '../services/api';

interface ModelManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  models: ModelInfo[];
  onRefresh: () => Promise<void> | void;
  onModelCreated?: (modelId: string) => Promise<void> | void;
}

const emptyForm = {
  name: '',
  model: '',
  baseUrl: '',
  apiKey: '',
};

export function ModelManagerModal({
  isOpen,
  onClose,
  models,
  onRefresh,
  onModelCreated,
}: ModelManagerModalProps) {
  const [form, setForm] = useState(emptyForm);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteIntentId, setDeleteIntentId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setFeedback(null);
    setDeleteIntentId(null);
    setForm(emptyForm);
  }, [isOpen]);

  useEffect(() => {
    if (!deleteIntentId) return;
    const timer = window.setTimeout(() => setDeleteIntentId(null), 4000);
    return () => window.clearTimeout(timer);
  }, [deleteIntentId]);

  const groupedModels = useMemo(() => {
    return {
      GLOBAL: models.filter((m) => m.type === 'GLOBAL'),
      USER: models.filter((m) => m.type === 'USER'),
    };
  }, [models]);

  const triggerRefresh = async () => {
    setIsRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleInputChange = (field: keyof typeof emptyForm) => (e: ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => ({ ...prev, [field]: e.target.value }));
  };

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;
    setFeedback(null);
    setIsSubmitting(true);
    try {
      const modelId = await modelApi.addCustomModel({
        name: form.name.trim(),
        model: form.model.trim(),
        baseUrl: form.baseUrl.trim(),
        apiKey: form.apiKey.trim(),
      });
      setForm(emptyForm);
      setFeedback({ type: 'success', message: '模型已创建并可用于新的研究。' });
      if (onModelCreated) {
        await onModelCreated(modelId);
      } else {
        await triggerRefresh();
      }
    } catch (error: any) {
      setFeedback({ type: 'error', message: error?.message || '创建模型失败，请稍后再试。' });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async (modelId: string) => {
    if (deletingId) return;
    setFeedback(null);
    setDeletingId(modelId);
    try {
      await modelApi.deleteCustomModel(modelId);
      setFeedback({ type: 'success', message: '模型已删除。' });
      await triggerRefresh();
    } catch (error: any) {
      setFeedback({ type: 'error', message: error?.message || '删除失败，请稍后重试。' });
    } finally {
      setDeletingId(null);
      setDeleteIntentId(null);
    }
  };

  const requestDelete = (modelId: string) => {
    if (deleteIntentId === modelId) {
      handleDelete(modelId);
    } else {
      setDeleteIntentId(modelId);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white w-full max-w-4xl rounded-2xl shadow-2xl border border-gray-100 flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">模型管理</h2>
            <p className="text-xs text-gray-500 mt-1">创建并维护可供研究会话选择的模型凭证。</p>
          </div>
          <button onClick={onClose} className="p-2 rounded-full hover:bg-gray-100 text-gray-500">
            <X className="w-4 h-4" />
          </button>
        </div>

        {feedback && (
          <div className={`mx-6 mt-4 px-3 py-2 rounded-lg text-sm flex items-center gap-2 ${feedback.type === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'}`}>
            {feedback.type === 'success' ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
            {feedback.message}
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-gray-900">可用模型</h3>
                <p className="text-xs text-gray-500">平台内置与个人模型均可在此查看。</p>
              </div>
              <button
                onClick={triggerRefresh}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
                disabled={isRefreshing}
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
                刷新
              </button>
            </div>

            <div className="space-y-4">
              <ModelList title="平台内置模型" icon={<Shield className="w-4 h-4 text-gray-500" />} models={groupedModels.GLOBAL} isUserModel={false} />
              <ModelList
                title="我的模型"
                icon={<UserIcon className="w-4 h-4 text-gray-500" />}
                models={groupedModels.USER}
                isUserModel
                onDelete={requestDelete}
                deletingId={deletingId}
                deleteIntentId={deleteIntentId}
              />
            </div>
          </section>

          <section className="border border-dashed border-gray-300 rounded-2xl p-4 bg-gray-50/60">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-xl bg-white flex items-center justify-center border border-gray-200">
                <Plus className="w-4 h-4 text-gray-700" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-gray-900">新增自定义模型</h3>
                <p className="text-xs text-gray-500">凭证将仅对你本人可见，删除前需保证未被研究使用。</p>
              </div>
            </div>

            <form onSubmit={handleCreate} className="space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-gray-600 mb-1 block">展示名称</label>
                  <input
                    type="text"
                    required
                    value={form.name}
                    onChange={handleInputChange('name')}
                    placeholder="例如：我的 DeepSeek"
                    className="w-full px-3 py-2.5 rounded-lg border border-gray-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-black/5"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-600 mb-1 block">模型 ID</label>
                  <input
                    type="text"
                    required
                    value={form.model}
                    onChange={handleInputChange('model')}
                    placeholder="例如：deepseek-chat"
                    className="w-full px-3 py-2.5 rounded-lg border border-gray-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-black/5"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-600 mb-1 block">Base URL</label>
                  <input
                    type="url"
                    required
                    value={form.baseUrl}
                    onChange={handleInputChange('baseUrl')}
                    placeholder="https://api.xxx.com/v1"
                    className="w-full px-3 py-2.5 rounded-lg border border-gray-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-black/5"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-600 mb-1 block">API Key</label>
                  <input
                    type="password"
                    required
                    value={form.apiKey}
                    onChange={handleInputChange('apiKey')}
                    placeholder="sk-..."
                    className="w-full px-3 py-2.5 rounded-lg border border-gray-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-black/5"
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-gray-500">首条研究消息会锁定模型与凭证，过程中无法修改。</p>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium ${
                    isSubmitting ? 'bg-gray-200 text-gray-400' : 'bg-black text-white hover:bg-gray-900'
                  }`}
                >
                  <Plus className="w-4 h-4" />
                  保存模型
                </button>
              </div>
            </form>
          </section>
        </div>
      </div>
    </div>
  );
}

interface ModelListProps {
  title: string;
  icon: ReactNode;
  models: ModelInfo[];
  isUserModel: boolean;
  onDelete?: (modelId: string) => void;
  deletingId?: string | null;
  deleteIntentId?: string | null;
}

function ModelList({ title, icon, models, isUserModel, onDelete, deletingId, deleteIntentId }: ModelListProps) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <div className="w-8 h-8 rounded-xl bg-gray-100 flex items-center justify-center">
          {icon}
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-900">{title}</p>
          <p className="text-xs text-gray-500">{models.length} 个</p>
        </div>
      </div>
      {models.length === 0 ? (
        <div className="px-4 py-3 rounded-xl border border-dashed border-gray-200 text-xs text-gray-500">
          {isUserModel ? '暂无自定义模型，点击下方按钮立即添加。' : '暂无可用的内置模型，请联系管理员配置。'}
        </div>
      ) : (
        <ul className="space-y-2">
          {models.map((model) => {
            const isPendingDelete = deleteIntentId === model.id;
            const showDelete = isUserModel && onDelete;
            return (
              <li key={model.id} className="p-3 border border-gray-200 rounded-xl bg-white flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center flex-wrap gap-2">
                    <p className="text-sm font-semibold text-gray-900">{model.name || model.model || '未命名模型'}</p>
                    <span className="text-[11px] uppercase tracking-wide px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
                      {model.model || '未知模型'}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1 break-all">Base URL：{model.baseUrl || '由平台维护'}</p>
                </div>
                {showDelete && (
                  <button
                    onClick={() => onDelete?.(model.id)}
                    disabled={deletingId === model.id}
                    className={`text-xs font-medium flex items-center gap-1 px-3 py-1.5 rounded-lg border transition-colors ${
                      isPendingDelete
                        ? 'border-red-200 text-red-600 bg-red-50'
                        : 'border-gray-200 text-gray-500 hover:bg-gray-50'
                    }`}
                    title={isPendingDelete ? '再次点击确认删除' : '删除该模型'}
                  >
                    <Trash2 className={`w-3.5 h-3.5 ${deletingId === model.id ? 'animate-pulse' : ''}`} />
                    {deletingId === model.id ? '删除中...' : isPendingDelete ? '确认删除' : '删除'}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
