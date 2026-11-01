import { useId, useState } from 'react';
import { HeartPulseIcon, RotateCcwIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useEngines } from '@/hooks/use-engines';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/popover';
import { Button, buttonVariants } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import {
  DEFAULT_CLONE_SETTINGS,
  patchCloneSettings,
  setCloneSetting,
  useCloneSettings,
  type CloneSettings,
} from '@/lib/store/clone-settings';
import { cn } from '@/lib/utils';

/** IndexTTS2's documented eight-value emotion order (do not reorder). */
const EMOTIONS = [
  'happy',
  'angry',
  'sad',
  'afraid',
  'disgusted',
  'melancholic',
  'surprised',
  'calm',
] as const;
type EmotionMode = CloneSettings['emotionMode'];

/** Clear all expressive direction without modifying voice or audio quality. */
function resetEmotion() {
  patchCloneSettings({
    emotionMode: DEFAULT_CLONE_SETTINGS.emotionMode,
    emotionText: DEFAULT_CLONE_SETTINGS.emotionText,
    emotionAlpha: DEFAULT_CLONE_SETTINGS.emotionAlpha,
    emotionVector: [...DEFAULT_CLONE_SETTINGS.emotionVector],
  });
}

/** Engine-gated, per-take emotion controls for cloning (not Voice Design). */
export function EmotionControls({ disabled = false }: { disabled?: boolean }) {
  const { t } = useTranslation();
  const { activeTts } = useEngines();
  const settings = useCloneSettings();
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!activeTts?.supports_emotion) return null;

  const modes: { mode: EmotionMode; label: string }[] = [
    { mode: 'none', label: t('cloneEmotion.off') },
    { mode: 'text', label: t('cloneEmotion.text') },
    { mode: 'vector', label: t('cloneEmotion.vector') },
  ];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label={t('cloneEmotion.title')}
        className={cn(
          buttonVariants({ variant: 'ghost', size: 'icon-lg' }),
          'relative text-muted-foreground hover:text-foreground data-popup-open:bg-secondary data-popup-open:text-foreground',
        )}
      >
        <HeartPulseIcon aria-hidden="true" />
        {settings.emotionMode !== 'none' && (
          <span
            className="absolute top-1 right-1 size-1.5 rounded-full bg-primary"
            aria-hidden="true"
          />
        )}
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        sideOffset={10}
        aria-labelledby={id}
        className="flex max-h-[min(560px,var(--available-height))] w-[min(420px,calc(100vw-32px))] flex-col p-0"
      >
        <header className="flex shrink-0 items-center justify-between px-4 pt-3 pb-2">
          <h3 id={id} className="text-sm font-semibold">
            {t('cloneEmotion.title')}
          </h3>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            disabled={disabled}
            aria-label={t('audiobook.reset')}
            onClick={resetEmotion}
          >
            <RotateCcwIcon aria-hidden="true" />
          </Button>
        </header>
        <div className="min-h-0 space-y-3 overflow-y-auto px-4 pb-4">
          <div className="grid grid-cols-3 gap-1 rounded-lg bg-muted/40 p-1">
            {modes.map(({ mode, label }) => (
              <Button
                key={mode}
                type="button"
                size="sm"
                variant={settings.emotionMode === mode ? 'secondary' : 'ghost'}
                disabled={disabled}
                aria-pressed={settings.emotionMode === mode}
                onClick={() => setCloneSetting('emotionMode', mode)}
              >
                {label}
              </Button>
            ))}
          </div>
          {settings.emotionMode === 'text' && (
            <div className="space-y-3">
              <label htmlFor={id + '-text'} className="block text-xs font-medium">
                {t('audiobook.emotion_text')}
              </label>
              <textarea
                id={id + '-text'}
                className="min-h-20 w-full resize-y rounded-lg border border-input bg-background/60 p-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                maxLength={500}
                value={settings.emotionText}
                disabled={disabled}
                placeholder={t('audiobook.emotion_text_ph')}
                onChange={(event) => setCloneSetting('emotionText', event.target.value)}
              />
              <div className="space-y-2">
                <div className="flex justify-between gap-2 text-xs">
                  <span id={id + '-strength'} className="font-medium">
                    {t('audiobook.emotion_alpha')}
                  </span>
                  <output className="tabular-nums">{settings.emotionAlpha.toFixed(2)}</output>
                </div>
                <Slider
                  thumbProps={{ 'aria-labelledby': id + '-strength' }}
                  min={0}
                  max={0.6}
                  step={0.05}
                  value={[settings.emotionAlpha]}
                  disabled={disabled}
                  onValueChange={(v) =>
                    setCloneSetting('emotionAlpha', Array.isArray(v) ? v[0] : v)
                  }
                />
              </div>
            </div>
          )}
          {settings.emotionMode === 'vector' && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">{t('audiobook.emotion_help')}</p>
              <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2">
                {EMOTIONS.map((emotion, index) => (
                  <div key={emotion} className="space-y-1.5">
                    <div className="flex justify-between gap-2 text-xs">
                      <span id={id + '-' + emotion} className="font-medium">
                        {t('cloneEmotion.' + emotion)}
                      </span>
                      <output className="tabular-nums">
                        {(settings.emotionVector[index] ?? 0).toFixed(2)}
                      </output>
                    </div>
                    <Slider
                      thumbProps={{ 'aria-labelledby': id + '-' + emotion }}
                      min={0}
                      max={1}
                      step={0.05}
                      value={[settings.emotionVector[index] ?? 0]}
                      disabled={disabled}
                      onValueChange={(value) => {
                        const next = [...settings.emotionVector];
                        next[index] = Array.isArray(value) ? value[0] : value;
                        setCloneSetting('emotionVector', next);
                      }}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
