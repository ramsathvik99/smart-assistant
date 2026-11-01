/**
 * Regional PyPI file mirrors for the locked dependency install (#3444, #3411).
 *
 * `uv sync --frozen` downloads the exact artifact URLs pinned in uv.lock, so an
 * index setting (`UV_INDEX_URL`, `UV_DEFAULT_INDEX`) never redirects them. The
 * mirrors below serve PyPI's file store byte for byte under the same
 * `/packages/<hash path>/<file>` layout, so swapping only the host keeps every
 * pinned sha256 valid: uv still verifies each file against the lock.
 *
 * Only hosts the region picker already sanctions are listed. PyTorch's own
 * index (`download-r2.pytorch.org`, `download.pytorch.org`) has no sanctioned
 * mirror and is left untouched.
 */

export const PYPI_FILES_ORIGIN = 'https://files.pythonhosted.org/packages/';

/** Region to the mirror prefix that replaces {@link PYPI_FILES_ORIGIN}. */
const PYPI_FILES_MIRRORS: Readonly<Record<string, string>> = {
  china: 'https://mirrors.aliyun.com/pypi/packages/',
};

/** Every prefix a staged lock may carry instead of the origin. */
const KNOWN_MIRRORS = [...new Set(Object.values(PYPI_FILES_MIRRORS))];

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');

/** The PyPI file mirror prefix for a resolved download region, or null. */
export function pypiFilesMirror(region: string): string | null {
  return PYPI_FILES_MIRRORS[region] ?? null;
}

/** Host that serves the PyPI-hosted wheels for a resolved download region. */
export function pypiFilesHost(region: string): string {
  return new URL(pypiFilesMirror(region) ?? PYPI_FILES_ORIGIN).host;
}

/**
 * Point every `url = "https://files.pythonhosted.org/packages/..."` artifact in
 * a lock at `mirror`. Only the host prefix of artifact URLs changes; hashes,
 * sizes, `source` registries and every other host stay byte-identical. A null
 * mirror returns the lock unchanged.
 */
export function mirrorLockUrls(lock: string, mirror: string | null): string {
  if (!mirror) return lock;
  return lock.replace(new RegExp(`(\\burl = ")${escape(PYPI_FILES_ORIGIN)}`, 'g'), `$1${mirror}`);
}

/** Inverse of {@link mirrorLockUrls} for any known mirror: compare locks by content, not host. */
export function normalizeLockHosts(lock: string): string {
  let result = lock;
  for (const mirror of KNOWN_MIRRORS) {
    result = result.replace(
      new RegExp(`(\\burl = ")${escape(mirror)}`, 'g'),
      `$1${PYPI_FILES_ORIGIN}`,
    );
  }
  return result;
}
