import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import '@/i18n';
import { GeneratePanel, type GenerateSession } from './generate-panel';

const idle: GenerateSession = {
  active: null,
  stage: 'idle',
  completed: 0,
  total: 0,
  failed: 0,
  stopped: false,
  chapters: [],
};

it('says why Generate is unavailable instead of going silently grey', () => {
  render(
    <GeneratePanel
      mode="stories"
      session={idle}
      blocker="voice"
      onGenerate={vi.fn()}
      onStop={vi.fn()}
    />,
  );
  const button = screen.getByRole('button', { name: 'Generate' });
  expect(button).toBeDisabled();
  expect(screen.getByText('Choose a default voice, or give every line a voice.')).toBeVisible();
  expect(button).toHaveAttribute('aria-describedby', 'generate-status');
});

it('generates when nothing blocks it and swaps to Stop with the tracker while rendering', () => {
  const onGenerate = vi.fn();
  const onStop = vi.fn();
  const view = render(
    <GeneratePanel
      mode="stories"
      session={idle}
      blocker={null}
      onGenerate={onGenerate}
      onStop={onStop}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Generate' }));
  expect(onGenerate).toHaveBeenCalledOnce();

  view.rerender(
    <GeneratePanel
      mode="stories"
      session={{
        ...idle,
        active: 'stories',
        stage: 'rendering',
        total: 2,
        chapters: [
          { title: 'One', status: 'done' },
          { title: 'Two', status: 'rendering' },
        ] as GenerateSession['chapters'],
      }}
      blocker={null}
      onGenerate={onGenerate}
      onStop={onStop}
    />,
  );
  expect(screen.queryByRole('button', { name: 'Generate' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
  expect(onStop).toHaveBeenCalledOnce();
  expect(screen.getByText('Two')).toBeVisible();
});

it('explains that the other longform mode is rendering', () => {
  render(
    <GeneratePanel
      mode="stories"
      session={{ ...idle, active: 'audiobook', stage: 'rendering' }}
      blocker="busy"
      onGenerate={vi.fn()}
      onStop={vi.fn()}
    />,
  );
  expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled();
  expect(screen.getByText(/already rendering/i)).toBeVisible();
});

it('leaves a missing engine to the page notice instead of repeating it', () => {
  render(
    <GeneratePanel
      mode="audiobook"
      session={idle}
      blocker="engine"
      onGenerate={vi.fn()}
      onStop={vi.fn()}
    />,
  );
  const status = screen.getByText('The voice engine is not ready. Check Settings → Models.');
  // Still read out with the disabled button, but not shown twice on screen.
  expect(status).toHaveClass('sr-only');
  expect(screen.getByRole('button', { name: 'Create audiobook' })).toHaveAttribute(
    'aria-describedby',
    'generate-status',
  );
});
