// @vitest-environment node
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  PYPI_FILES_ORIGIN,
  mirrorLockUrls,
  normalizeLockHosts,
  pypiFilesHost,
  pypiFilesMirror,
} from './pypi-mirror';

const LOCK = readFileSync(join(__dirname, '..', '..', '..', 'uv.lock'), 'utf8');
const urls = (lock: string) => [...lock.matchAll(/\burl = "([^"]+)"/g)].map((m) => m[1]!);
const hashes = (lock: string) => [...lock.matchAll(/\bhash = "([^"]+)"/g)].map((m) => m[1]!);

describe('regional PyPI file mirror for the locked install (#3444)', () => {
  const mirror = pypiFilesMirror('china')!;
  const mirrored = mirrorLockUrls(LOCK, mirror);

  it('maps only the china region to a sanctioned mirror', () => {
    expect(mirror).toBe('https://mirrors.aliyun.com/pypi/packages/');
    expect(pypiFilesHost('china')).toBe('mirrors.aliyun.com');
    for (const region of ['auto', 'global', 'russia', 'restricted']) {
      expect(pypiFilesMirror(region)).toBeNull();
      expect(pypiFilesHost(region)).toBe('files.pythonhosted.org');
    }
  });

  it('keeps every pinned hash and changes only the PyPI host', () => {
    expect(LOCK).toContain(PYPI_FILES_ORIGIN);
    expect(mirrored).not.toContain(PYPI_FILES_ORIGIN);
    expect(hashes(mirrored)).toEqual(hashes(LOCK));
    const before = urls(LOCK);
    const after = urls(mirrored);
    expect(after).toHaveLength(before.length);
    after.forEach((url, i) => {
      const original = before[i]!;
      if (original.startsWith(PYPI_FILES_ORIGIN)) {
        expect(url).toBe(mirror + original.slice(PYPI_FILES_ORIGIN.length));
      } else {
        // PyTorch's index, GitHub and registry sources have no sanctioned mirror.
        expect(url).toBe(original);
      }
    });
    // Nothing but those URL prefixes differs.
    expect(mirrored.split(mirror).join(PYPI_FILES_ORIGIN)).toBe(LOCK);
    expect(mirrored).toContain('https://download-r2.pytorch.org/');
  });

  it('leaves the lock byte-identical without a mirror', () => {
    expect(mirrorLockUrls(LOCK, null)).toBe(LOCK);
    expect(mirrorLockUrls(LOCK, pypiFilesMirror('global'))).toBe(LOCK);
  });

  it('normalizes a mirrored lock back to the original', () => {
    expect(normalizeLockHosts(mirrored)).toBe(LOCK);
    expect(normalizeLockHosts(LOCK)).toBe(LOCK);
  });
});
