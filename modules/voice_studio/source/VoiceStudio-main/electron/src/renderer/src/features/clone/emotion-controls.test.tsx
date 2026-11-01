import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@/i18n';
import { EmotionControls } from './emotion-controls';
import {
  cloneSettingsStore,
  DEFAULT_CLONE_SETTINGS,
  patchCloneSettings,
} from '@/lib/store/clone-settings';

const engine = vi.hoisted(() => ({ supportsEmotion: true }));
vi.mock('@/hooks/use-engines', () => ({
  useEngines: () => ({ activeTts: { id: 'indextts2', supports_emotion: engine.supportsEmotion } }),
}));

beforeEach(() => {
  cloneSettingsStore.setState(() => ({ ...DEFAULT_CLONE_SETTINGS }));
  engine.supportsEmotion = true;
});

describe('IndexTTS2 clone emotion controls', () => {
  it('is hidden for engines without emotion support', () => {
    engine.supportsEmotion = false;
    render(<EmotionControls />);
    expect(screen.queryByRole('button', { name: 'Emotion' })).not.toBeInTheDocument();
  });

  it('keeps the default take neutral and accepts a written emotion prompt', async () => {
    render(<EmotionControls />);
    fireEvent.click(screen.getByRole('button', { name: 'Emotion' }));
    expect(cloneSettingsStore.state.emotionMode).toBe('none');

    fireEvent.click(await screen.findByRole('button', { name: 'Description' }));
    const textarea = screen.getByRole('textbox', { name: 'Emotion description' });
    fireEvent.change(textarea, { target: { value: 'whispering with sadness' } });
    expect(cloneSettingsStore.state.emotionMode).toBe('text');
    expect(cloneSettingsStore.state.emotionText).toBe('whispering with sadness');
    expect(screen.getByText('0.60')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Off' }));
    expect(cloneSettingsStore.state.emotionMode).toBe('none');
    // The text is a draft and is restored if Description is selected again.
    expect(cloneSettingsStore.state.emotionText).toBe('whispering with sadness');
  });

  it('offers eight correctly ordered vector sliders and an isolated reset', async () => {
    patchCloneSettings({
      emotionMode: 'vector',
      emotionVector: [0.4, 0, 0, 0, 0, 0.2, 0, 0],
      speed: 1.5,
    });
    render(<EmotionControls />);
    fireEvent.click(screen.getByRole('button', { name: 'Emotion' }));
    expect(await screen.findByRole('button', { name: 'Sliders' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    // Base UI mounts slider groups before their measured thumbs in jsdom.
    // Assert the eight real controls plus labels; browser rendering supplies thumbs.
    expect(document.querySelectorAll('[data-slot="slider"]')).toHaveLength(8);
    for (const label of [
      'Happy',
      'Angry',
      'Sad',
      'Afraid',
      'Disgusted',
      'Melancholic',
      'Surprised',
      'Calm',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(cloneSettingsStore.state.emotionMode).toBe('none');
    expect(cloneSettingsStore.state.emotionVector).toEqual([0, 0, 0, 0, 0, 0, 0, 0]);
    expect(cloneSettingsStore.state.speed).toBe(1.5);
  });

  it('disables editing while a take is being synthesized', async () => {
    render(<EmotionControls disabled />);
    fireEvent.click(screen.getByRole('button', { name: 'Emotion' }));
    expect(await screen.findByRole('button', { name: 'Description' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Sliders' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reset' })).toBeDisabled();
  });
});
