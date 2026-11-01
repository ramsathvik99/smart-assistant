// @vitest-environment node
import { fixture, runner, report, recipe } from './runtime-windows-rocm.fixture';
import { execFile } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { afterEach, expect, it, vi } from 'vitest';
import { installRuntime, runtimeDependenciesReady } from './runtime-project';
const host = vi.hoisted(() => ({ data: '' }));
const originalResources = Object.getOwnPropertyDescriptor(process, 'resourcesPath');
afterEach(() => {
  if (originalResources) Object.defineProperty(process, 'resourcesPath', originalResources);
  else delete (process as { resourcesPath?: string }).resourcesPath;
});
vi.mock('electron', () => ({ app: { isPackaged: true, getPath: () => host.data } }));
vi.mock('./distribution', () => ({ runtimeSetupSupported: () => true }));
import { BackendSupervisor } from './backend';

async function prepared() {
  const { bundle, project } = await fixture();
  host.data = join(dirname(project), 'user');
  await mkdir(host.data);
  await writeFile(
    join(host.data, 'runtime-location.json'),
    JSON.stringify({
      root: dirname(project),
      owned: true,
    }),
  );
  // The production resolver appends project to the configured root.
  const target = join(dirname(project), 'project');
  Object.defineProperty(process, 'resourcesPath', { configurable: true, value: bundle });
  await installRuntime(
    bundle,
    target,
    'uv',
    runner(target),
    new AbortController().signal,
    undefined,
    'global',
  );
  vi.mocked(execFile).mockClear();
  const supervisor = new BackendSupervisor();
  const internal = supervisor as unknown as {
    resolveRuntimeProject: () => Promise<{ ready: boolean }>;
    runtimeProject: string;
    stage: string;
  };
  return { bundle, target, supervisor, internal };
}
function nativeCalls() {
  return vi
    .mocked(execFile)
    .mock.calls.filter(([, args]) => (args as string[]).includes('--verify-only'));
}

it('resolves a healthy project with one native verification and fresh independent checks', async () => {
  const { internal, target } = await prepared();
  expect((await internal.resolveRuntimeProject()).ready).toBe(true);
  expect(nativeCalls()).toHaveLength(1);
  expect(await runtimeDependenciesReady(target)).toBe(true);
  expect(nativeCalls()).toHaveLength(2);
});

it('setup reuse makes one native verification in its readiness decision', async () => {
  // This drives the Windows ROCm installer, which runs only on x64.
  vi.spyOn(process, 'arch', 'get').mockReturnValue('x64');
  const { internal, supervisor, target } = await prepared();
  internal.runtimeProject = target;
  internal.stage = 'setup_required';
  vi.spyOn(supervisor, 'start').mockResolvedValue(undefined);
  await supervisor.setupRuntime();
  expect(nativeCalls()).toHaveLength(1);
  expect(supervisor.start).toHaveBeenCalledOnce();
});

it('failed ready/compatible fallback shares failure but a later retry rechecks', async () => {
  const { internal } = await prepared();
  vi.mocked(execFile).mockImplementationOnce(((
    _c: unknown,
    _a: unknown,
    _o: unknown,
    callback: (error: Error | null, out: string, err: string) => void,
  ) => callback(Error('driver'), '', '')) as never);
  expect((await internal.resolveRuntimeProject()).ready).toBe(false);
  expect(nativeCalls()).toHaveLength(1);
  expect((await internal.resolveRuntimeProject()).ready).toBe(true);
  expect(nativeCalls()).toHaveLength(2);
});

it('changed recipe cannot reuse earlier success and repair requires fresh verification', async () => {
  const { internal, bundle, target } = await prepared();
  expect((await internal.resolveRuntimeProject()).ready).toBe(true);
  await writeFile(join(bundle, 'scripts/windows-rocm-recipe.json'), recipe + '\n');
  expect((await internal.resolveRuntimeProject()).ready).toBe(false);
  expect(nativeCalls()).toHaveLength(1);
  await installRuntime(
    bundle,
    target,
    'uv',
    runner(target),
    new AbortController().signal,
    undefined,
    'global',
  );
  vi.mocked(execFile).mockImplementationOnce(((
    _c: unknown,
    _a: unknown,
    _o: unknown,
    callback: (error: Error | null, out: string, err: string) => void,
  ) => callback(Error('still broken after repair'), report, '')) as never);
  expect((await internal.resolveRuntimeProject()).ready).toBe(false);
  expect(nativeCalls()).toHaveLength(2);
});
