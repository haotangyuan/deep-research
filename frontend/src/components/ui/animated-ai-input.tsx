"use client";

import {
  ArrowRight,
  Bot,
  Check,
  ChevronDown,
  Coins,
  Loader2,
  Paperclip,
  Plus,
  RefreshCw,
  Shield,
  User,
} from "lucide-react";
import {
  useState,
  useRef,
  useCallback,
  useEffect,
} from "react";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { motion, AnimatePresence } from "framer-motion";

interface UseAutoResizeTextareaProps {
  minHeight: number;
  maxHeight?: number;
}

function useAutoResizeTextarea({
  minHeight,
  maxHeight,
}: UseAutoResizeTextareaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const adjustHeight = useCallback(
    (reset?: boolean) => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      if (reset) {
        textarea.style.height = `${minHeight}px`;
        return;
      }

      textarea.style.height = `${minHeight}px`;

      const newHeight = Math.max(
        minHeight,
        Math.min(textarea.scrollHeight, maxHeight ?? Number.POSITIVE_INFINITY),
      );

      textarea.style.height = `${newHeight}px`;
    },
    [minHeight, maxHeight],
  );

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = `${minHeight}px`;
    }
  }, [minHeight]);

  useEffect(() => {
    const handleResize = () => adjustHeight();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [adjustHeight]);

  return { textareaRef, adjustHeight };
}

const OPENAI_ICON = (
  <>
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 256 260"
      aria-label="OpenAI Icon"
      className="block h-4 w-4 dark:hidden"
    >
      <title>OpenAI Icon Light</title>
      <path d="M239.184 106.203a64.716 64.716 0 0 0-5.576-53.103C219.452 28.459 191 15.784 163.213 21.74A65.586 65.586 0 0 0 52.096 45.22a64.716 64.716 0 0 0-43.23 31.36c-14.31 24.602-11.061 55.634 8.033 76.74a64.665 64.665 0 0 0 5.525 53.102c14.174 24.65 42.644 37.324 70.446 31.36a64.72 64.72 0 0 0 48.754 21.744c28.481.025 53.714-18.361 62.414-45.481a64.767 64.767 0 0 0 43.229-31.36c14.137-24.558 10.875-55.423-8.083-76.483Zm-97.56 136.338a48.397 48.397 0 0 1-31.105-11.255l1.535-.87 51.67-29.825a8.595 8.595 0 0 0 4.247-7.367v-72.85l21.845 12.636c.218.111.37.32.409.563v60.367c-.056 26.818-21.783 48.545-48.601 48.601Zm-104.466-44.61a48.345 48.345 0 0 1-5.781-32.589l1.534.921 51.722 29.826a8.339 8.339 0 0 0 8.441 0l63.181-36.425v25.221a.87.87 0 0 1-.358.665l-52.335 30.184c-23.257 13.398-52.97 5.431-66.404-17.803ZM23.549 85.38a48.499 48.499 0 0 1 25.58-21.333v61.39a8.288 8.288 0 0 0 4.195 7.316l62.874 36.272-21.845 12.636a.819.819 0 0 1-.767 0L41.353 151.53c-23.211-13.454-31.171-43.144-17.804-66.405v.256Zm179.466 41.695-63.08-36.63L161.73 77.86a.819.819 0 0 1 .768 0l52.233 30.184a48.6 48.6 0 0 1-7.316 87.635v-61.391a8.544 8.544 0 0 0-4.4-7.213Zm21.742-32.69-1.535-.922-51.619-30.081a8.39 8.39 0 0 0-8.492 0L99.98 99.808V74.587a.716.716 0 0 1 .307-.665l52.233-30.133a48.652 48.652 0 0 1 72.236 50.391v.205ZM88.061 139.097l-21.845-12.585a.87.87 0 0 1-.41-.614V65.685a48.652 48.652 0 0 1 79.757-37.346l-1.535.87-51.67 29.825a8.595 8.595 0 0 0-4.246 7.367l-.051 72.697Zm11.868-25.58 28.138-16.217 28.188 16.218v32.434l-28.086 16.218-28.188-16.218-.052-32.434Z" />
    </svg>
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 256 260"
      aria-label="OpenAI Icon"
      className="hidden h-4 w-4 dark:block"
    >
      <title>OpenAI Icon Dark</title>
      <path
        fill="#fff"
        d="M239.184 106.203a64.716 64.716 0 0 0-5.576-53.103C219.452 28.459 191 15.784 163.213 21.74A65.586 65.586 0 0 0 52.096 45.22a64.716 64.716 0 0 0-43.23 31.36c-14.31 24.602-11.061 55.634 8.033 76.74a64.665 64.665 0 0 0 5.525 53.102c14.174 24.65 42.644 37.324 70.446 31.36a64.72 64.72 0 0 0 48.754 21.744c28.481.025 53.714-18.361 62.414-45.481a64.767 64.767 0 0 0 43.229-31.36c14.137-24.558 10.875-55.423-8.083-76.483Zm-97.56 136.338a48.397 48.397 0 0 1-31.105-11.255l1.535-.87 51.67-29.825a8.595 8.595 0 0 0 4.247-7.367v-72.85l21.845 12.636c.218.111.37.32.409.563v60.367c-.056 26.818-21.783 48.545-48.601 48.601Zm-104.466-44.61a48.345 48.345 0 0 1-5.781-32.589l1.534.921 51.722 29.826a8.339 8.339 0 0 0 8.441 0l63.181-36.425v25.221a.87.87 0 0 1-.358.665l-52.335 30.184c-23.257 13.398-52.97 5.431-66.404-17.803ZM23.549 85.38a48.499 48.499 0 0 1 25.58-21.333v61.39a8.288 8.288 0 0 0 4.195 7.316l62.874 36.272-21.845 12.636a.819.819 0 0 1-.767 0L41.353 151.53c-23.211-13.454-31.171-43.144-17.804-66.405v.256Zm179.466 41.695-63.08-36.63L161.73 77.86a.819.819 0 0 1 .768 0l52.233 30.184a48.6 48.6 0 0 1-7.316 87.635v-61.391a8.544 8.544 0 0 0-4.4-7.213Zm21.742-32.69-1.535-.922-51.619-30.081a8.39 8.39 0 0 0-8.492 0L99.98 99.808V74.587a.716.716 0 0 1 .307-.665l52.233-30.133a48.652 48.652 0 0 1 72.236 50.391v.205ZM88.061 139.097l-21.845-12.585a.87.87 0 0 1-.41-.614V65.685a48.652 48.652 0 0 1 79.757-37.346l-1.535.87-51.67 29.825a8.595 8.595 0 0 0-4.246 7.367l-.051 72.697Zm11.868-25.58 28.138-16.217 28.188 16.218v32.434l-28.086 16.218-28.188-16.218-.052-32.434Z"
      />
    </svg>
  </>
);

const GEMINI_ICON = (
  <svg
    height="1em"
    className="h-4 w-4"
    viewBox="0 0 24 24"
    xmlns="http://www.w3.org/2000/svg"
  >
    <title>Gemini</title>
    <defs>
      <linearGradient
        id="lobe-icons-gemini-fill"
        x1="0%"
        x2="68.73%"
        y1="100%"
        y2="30.395%"
      >
        <stop offset="0%" stopColor="#1C7DFF" />
        <stop offset="52.021%" stopColor="#1C69FF" />
        <stop offset="100%" stopColor="#F0DCD6" />
      </linearGradient>
    </defs>
    <path
      d="M12 24A14.304 14.304 0 000 12 14.304 14.304 0 0012 0a14.305 14.305 0 0012 12 14.305 14.305 0 00-12 12"
      fill="url(#lobe-icons-gemini-fill)"
      fillRule="nonzero"
    />
  </svg>
);

const CLAUDE_ICON = (
  <>
    <svg
      fill="#000"
      fillRule="evenodd"
      className="block h-4 w-4 dark:hidden"
      viewBox="0 0 24 24"
      width="1em"
      xmlns="http://www.w3.org/2000/svg"
    >
      <title>Anthropic Icon Light</title>
      <path d="M13.827 3.52h3.603L24 20h-3.603l-6.57-16.48zm-7.258 0h3.767L16.906 20h-3.674l-1.343-3.461H5.017l-1.344 3.46H0L6.57 3.522zm4.132 9.959L8.453 7.687 6.205 13.48H10.7z" />
    </svg>
    <svg
      fill="#fff"
      fillRule="evenodd"
      className="hidden h-4 w-4 dark:block"
      viewBox="0 0 24 24"
      width="1em"
      xmlns="http://www.w3.org/2000/svg"
    >
      <title>Anthropic Icon Dark</title>
      <path d="M13.827 3.52h3.603L24 20h-3.603l-6.57-16.48zm-7.258 0h3.767L16.906 20h-3.674l-1.343-3.461H5.017l-1.344 3.46H0L6.57 3.522zm4.132 9.959L8.453 7.687 6.205 13.48H10.7z" />
    </svg>
  </>
);

type SelectOption = {
  value: string;
  label: string;
  caption?: string;
  type?: string;
  disabled?: boolean;
};

interface AnimatedAIInputProps {
  value?: string;
  onValueChange?: (value: string) => void;
  onSubmit?: (value: string) => void;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
  isSubmitting?: boolean;
  showAttachment?: boolean;
  showModel?: boolean;
  modelDisabled?: boolean;
  showBudget?: boolean;
  budgetOptions?: SelectOption[];
  selectedBudget?: string;
  onBudgetChange?: (value: string) => void;
  models?: SelectOption[];
  selectedModel?: string;
  onModelChange?: (value: string) => void;
  modelLoading?: boolean;
  onRefreshModels?: () => void;
  onManageModels?: () => void;
}

const FALLBACK_MODELS: SelectOption[] = [
  { value: "o3-mini", label: "o3-mini" },
  { value: "Gemini 2.5 Flash", label: "Gemini 2.5 Flash" },
  { value: "Claude 3.5 Sonnet", label: "Claude 3.5 Sonnet" },
  { value: "GPT-4-1 Mini", label: "GPT-4-1 Mini" },
  { value: "GPT-4-1", label: "GPT-4-1" },
];

function getModelIcon(label = "") {
  const normalized = label.toLowerCase();
  if (normalized.includes("gemini")) return GEMINI_ICON;
  if (normalized.includes("claude") || normalized.includes("anthropic")) {
    return CLAUDE_ICON;
  }
  if (
    normalized.includes("gpt") ||
    normalized.includes("openai") ||
    normalized.includes("o3") ||
    normalized.includes("o4")
  ) {
    return OPENAI_ICON;
  }
  return <Bot className="h-4 w-4 opacity-50" />;
}

export function AI_Prompt({
  value: controlledValue,
  onValueChange,
  onSubmit,
  placeholder = "What can I do for you?",
  className,
  disabled = false,
  isSubmitting = false,
  showAttachment = true,
  showModel = true,
  modelDisabled = false,
  showBudget = false,
  budgetOptions = [],
  selectedBudget,
  onBudgetChange,
  models,
  selectedModel,
  onModelChange,
  modelLoading = false,
  onRefreshModels,
  onManageModels,
}: AnimatedAIInputProps = {}) {
  const [uncontrolledValue, setUncontrolledValue] = useState("");
  const value = controlledValue ?? uncontrolledValue;
  const { textareaRef, adjustHeight } = useAutoResizeTextarea({
    minHeight: 72,
    maxHeight: 300,
  });
  const modelOptions = models === undefined ? FALLBACK_MODELS : models;
  const [uncontrolledModel, setUncontrolledModel] = useState(
    modelOptions[0]?.value || "",
  );
  const selectedModelValue = selectedModel ?? uncontrolledModel;
  const selectedModelOption =
    modelOptions.find((model) => model.value === selectedModelValue) ??
    (selectedModelValue
      ? { value: selectedModelValue, label: selectedModelValue }
      : modelOptions[0]);

  useEffect(() => {
    adjustHeight();
  }, [adjustHeight, value]);

  useEffect(() => {
    if (
      selectedModel === undefined &&
      !modelOptions.some((model) => model.value === uncontrolledModel)
    ) {
      setUncontrolledModel(modelOptions[0]?.value || "");
    }
  }, [modelOptions, selectedModel, uncontrolledModel]);

  const updateValue = (nextValue: string) => {
    if (controlledValue === undefined) {
      setUncontrolledValue(nextValue);
    }
    onValueChange?.(nextValue);
  };

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled || isSubmitting) return;
    onSubmit?.(trimmed);
    if (controlledValue === undefined) {
      setUncontrolledValue("");
      adjustHeight(true);
    }
  };

  const handleModelSelect = (nextModel: string) => {
    if (selectedModel === undefined) {
      setUncontrolledModel(nextModel);
    }
    onModelChange?.(nextModel);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && value.trim()) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const hasValue = Boolean(value.trim());

  return (
    <div className={cn("w-full py-4", className)}>
      <div className="rounded-2xl border border-gray-200 bg-white p-1.5 shadow-lg shadow-gray-900/5">
        <div className="relative">
          <div className="relative flex flex-col">
            <div className="overflow-y-auto" style={{ maxHeight: "400px" }}>
              <Textarea
                id="ai-input-15"
                value={value}
                placeholder={placeholder}
                disabled={disabled}
                className={cn(
                  "min-h-[72px] w-full resize-none rounded-xl rounded-b-none border-none bg-gray-50 px-4 py-3 text-base text-gray-950 placeholder:text-gray-500 focus-visible:ring-0 focus-visible:ring-offset-0 disabled:opacity-70 sm:text-sm",
                )}
                ref={textareaRef}
                onKeyDown={handleKeyDown}
                onChange={(e) => {
                  updateValue(e.target.value);
                  adjustHeight();
                }}
              />
            </div>

            <div className="min-h-14 rounded-b-xl bg-gray-50">
              <div className="flex w-full flex-col gap-2 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  {showModel && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          disabled={modelDisabled}
                          className="flex h-8 max-w-full items-center gap-1 rounded-md pl-1 pr-2 text-xs text-gray-700 hover:bg-gray-200/70 focus-visible:ring-1 focus-visible:ring-gray-400 focus-visible:ring-offset-0 disabled:opacity-100"
                        >
                          <AnimatePresence mode="wait">
                            <motion.div
                              key={selectedModelOption?.value || "none"}
                              initial={{ opacity: 0, y: -5 }}
                              animate={{ opacity: 1, y: 0 }}
                              exit={{ opacity: 0, y: 5 }}
                              transition={{ duration: 0.15 }}
                              className="flex min-w-0 items-center gap-1"
                            >
                              {getModelIcon(selectedModelOption?.label)}
                              <span className="max-w-[160px] truncate">
                                {selectedModelOption?.label || "选择模型"}
                              </span>
                              {!modelDisabled && (
                                <ChevronDown className="h-3 w-3 shrink-0 opacity-50" />
                              )}
                            </motion.div>
                          </AnimatePresence>
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent
                        align="start"
                        className={cn(
                          "min-w-[15rem]",
                          "border-gray-200 bg-white",
                        )}
                      >
                        {onRefreshModels && (
                          <DropdownMenuItem
                            onSelect={(event) => {
                              event.preventDefault();
                              onRefreshModels();
                            }}
                            disabled={modelLoading}
                            className="flex items-center gap-2"
                          >
                            <RefreshCw
                              className={cn(
                                "h-4 w-4",
                                modelLoading && "animate-spin",
                              )}
                            />
                            <span>刷新模型</span>
                          </DropdownMenuItem>
                        )}
                        {modelOptions.map((model) => (
                          <DropdownMenuItem
                            key={model.value}
                            disabled={model.disabled}
                            onSelect={() => handleModelSelect(model.value)}
                            className="flex items-center justify-between gap-2"
                          >
                            <div className="flex min-w-0 items-center gap-2">
                              {model.type === "GLOBAL" ? (
                                <Shield className="h-4 w-4 text-gray-500" />
                              ) : model.type === "USER" ? (
                                <User className="h-4 w-4 text-gray-500" />
                              ) : (
                                getModelIcon(model.label)
                              )}
                              <div className="min-w-0">
                                <span className="block truncate">
                                  {model.label}
                                </span>
                                {model.caption && (
                                  <span className="block truncate text-[11px] text-gray-500">
                                    {model.caption}
                                  </span>
                                )}
                              </div>
                            </div>
                            {selectedModelValue === model.value && (
                              <Check className="h-4 w-4 text-blue-500" />
                            )}
                          </DropdownMenuItem>
                        ))}
                        {modelOptions.length === 0 && (
                          <DropdownMenuItem disabled>
                            暂无可用模型
                          </DropdownMenuItem>
                        )}
                        {onManageModels && (
                          <DropdownMenuItem
                            onSelect={(event) => {
                              event.preventDefault();
                              onManageModels();
                            }}
                            className="flex items-center gap-2"
                          >
                            <Plus className="h-4 w-4" />
                            <span>管理模型</span>
                          </DropdownMenuItem>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}

                  {showModel && showBudget && budgetOptions.length > 0 && (
                    <>
                      <div className="mx-0.5 h-4 w-px bg-gray-200" />
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="ghost"
                            className="flex h-8 items-center gap-1 rounded-md px-2 text-xs text-gray-700 hover:bg-gray-200/70 focus-visible:ring-1 focus-visible:ring-gray-400 focus-visible:ring-offset-0"
                          >
                            <Coins className="h-4 w-4 opacity-70" />
                            <span>
                              {budgetOptions.find(
                                (option) => option.value === selectedBudget,
                              )?.label || "研究预算"}
                            </span>
                            <ChevronDown className="h-3 w-3 opacity-50" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                          align="start"
                          className="min-w-[12rem] border-gray-200 bg-white"
                        >
                          {budgetOptions.map((option) => (
                            <DropdownMenuItem
                              key={option.value}
                              onSelect={() => onBudgetChange?.(option.value)}
                              className="flex items-center justify-between gap-2"
                            >
                              <div className="min-w-0">
                                <span className="block text-sm">
                                  {option.label}
                                </span>
                                {option.caption && (
                                  <span className="block truncate text-[11px] text-gray-500">
                                    {option.caption}
                                  </span>
                                )}
                              </div>
                              {selectedBudget === option.value && (
                                <Check className="h-4 w-4 text-blue-500" />
                              )}
                            </DropdownMenuItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </>
                  )}

                  {showAttachment && (
                    <>
                      <div className="mx-0.5 h-4 w-px bg-gray-200" />
                      <label
                        className={cn(
                          "rounded-lg bg-gray-100 p-2",
                          "cursor-pointer hover:bg-gray-200 focus-visible:ring-1 focus-visible:ring-gray-400 focus-visible:ring-offset-0",
                          "text-gray-500 hover:text-gray-950",
                        )}
                        aria-label="Attach file"
                      >
                        <input type="file" className="hidden" />
                        <Paperclip className="h-4 w-4 transition-colors" />
                      </label>
                    </>
                  )}
                </div>

                <button
                  type="button"
                  className={cn(
                    "rounded-lg bg-gray-100 p-2 text-gray-950",
                    "hover:bg-gray-200 focus-visible:ring-1 focus-visible:ring-gray-400 focus-visible:ring-offset-0",
                    "disabled:cursor-not-allowed disabled:text-gray-400",
                  )}
                  aria-label="Send message"
                  disabled={!hasValue || disabled || isSubmitting}
                  onClick={handleSubmit}
                >
                  {isSubmitting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <ArrowRight
                      className={cn(
                        "h-4 w-4 transition-opacity duration-200",
                        hasValue ? "opacity-100" : "opacity-30",
                      )}
                    />
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function AI_Prompt_Demo() {
  return <AI_Prompt />;
}

export type { AnimatedAIInputProps, SelectOption as AnimatedAIInputOption };
